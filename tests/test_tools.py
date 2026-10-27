"""Parsing the ways humans and banks actually write money and dates."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from vme.currencies import (
    GROUP_SPACE,
    compact_money,
    format_money,
    normalise_code,
    sniff_currency,
)
from vme.models import AUTO, EXPENSE, INCOME
from vme.tools import (
    coerce_row,
    coerce_rows,
    infer_dayfirst,
    looks_like_income,
    month_bounds,
    parse_amount,
    parse_date,
    parse_kind,
    parse_period,
    period_label,
    pick,
    shorten,
)


class TestParseAmount:
    @pytest.mark.parametrize("text,expected", [
        ("1234.56", "1234.56"),
        ("1,234.56", "1234.56"),          # anglophone grouping
        ("1.234,56", "1234.56"),          # continental grouping
        ("1 234,56", "1234.56"),          # PLN / UAH style
        ("1 234 567,89", "1234567.89"),
        ("1,234,567", "1234567"),         # grouped thousands, no decimals
        ("$1,234.56", "1234.56"),
        ("1234,56 zł", "1234.56"),
        ("-12.00", "-12.00"),
        ("(12.00)", "-12.00"),            # accounting negative
        ("120.00-", "-120.00"),           # trailing minus
        ("+45", "45"),
        ("1,5", "1.5"),                   # a lone comma with 1 digit: decimal
        ("1,50", "1.50"),                 # ... with 2 digits: still decimal
        ("2,500", "2500"),                # ... with 3 digits: grouped thousands
        ("1.234.567", "1234567"),         # dots grouping thousands, no decimals
        (".50", "0.50"),                  # a leading decimal point ...
        ("$.50", "0.50"),
        ("-.50", "-0.50"),
        ("CHF 1'234.50", "1234.50"),
        (12.5, "12.5"),
        (Decimal("7.25"), "7.25"),
    ])
    def test_reads(self, text, expected):
        assert parse_amount(text) == Decimal(expected)

    @pytest.mark.parametrize("text,expected", [
        # issue #6: the dot of an abbreviation was read as a decimal point
        ("Rs. 500", "500"),
        ("Rs. 1,500", "1500"),
        ("Rs.500", "500"),
        ("kr. 500", "500"),
        ("500 kr.", "500"),
        ("kr. 1.234,50", "1234.50"),
        ("S/. 1,500.00", "1500.00"),
        ("(Rs. 500)", "-500"),
        ("USD -12.00", "-12.00"),
    ])
    def test_a_currency_around_the_number_is_dropped_whole(self, text, expected):
        assert parse_amount(text) == Decimal(expected)

    @pytest.mark.parametrize("text,expected", [
        ("1.5E+3", "1500"), ("1,5E+3", "1500"), ("2.5e-2", "0.025"), ("1e3", "1000"),
    ])
    def test_exponent_notation(self, text, expected):
        amount = parse_amount(text)
        assert amount == Decimal(expected)
        assert "E" not in str(amount)              # written out, as money is

    @pytest.mark.parametrize("text,expected", [
        ("500,-", "500"), ("500.-", "500"), ("20,- zł", "20"), ("20,– zł", "20"),
    ])
    def test_a_whole_amount_written_with_a_dash_is_not_negative(self, text, expected):
        assert parse_amount(text) == Decimal(expected)

    @pytest.mark.parametrize("bad", ["", "   ", None, "abc", "zł", "Rs.", "-"])
    def test_rejects(self, bad):
        with pytest.raises(ValueError):
            parse_amount(bad)

    def test_rejects_booleans(self):
        with pytest.raises(ValueError):
            parse_amount(True)


class TestParseDate:
    @pytest.mark.parametrize("text,expected", [
        ("2026-08-15", _dt.date(2026, 8, 15)),
        ("2026/08/15", _dt.date(2026, 8, 15)),
        ("15.08.2026", _dt.date(2026, 8, 15)),
        ("20260815", _dt.date(2026, 8, 15)),          # OFX
        ("20260815120000[-5:EST]", _dt.date(2026, 8, 15)),
        ("8/15'26", _dt.date(2026, 8, 15)),           # QIF
        ("2026-08-15T09:30:00", _dt.date(2026, 8, 15)),
        ("15 Aug 2026", _dt.date(2026, 8, 15)),
        (_dt.date(2026, 8, 15), _dt.date(2026, 8, 15)),
    ])
    def test_reads(self, text, expected):
        assert parse_date(text) == expected

    def test_ambiguous_respects_dayfirst(self):
        assert parse_date("03/04/2026", dayfirst=True) == _dt.date(2026, 4, 3)
        assert parse_date("03/04/2026", dayfirst=False) == _dt.date(2026, 3, 4)

    @pytest.mark.parametrize("text", [
        # issue #10: a time after a non-ISO date used to lose the whole date
        "15.08.2026 10:23", "15/08/2026 10:23", "08/15/2026 10:23:00",
        "08/15/2026 10:23:00 PM", "15 Aug 2026 10:23", "2026-08-15 10:23",
        "15.08.2026T10:23:45Z", "2026-08-15T09:30:00+02:00",
        "Aug 15, 2026", "August 15, 2026", "Aug 15, 2026, 9:05 am",
    ])
    def test_a_time_after_the_date(self, text):
        assert parse_date(text) == _dt.date(2026, 8, 15)

    def test_a_time_keeps_the_day_month_order(self):
        assert parse_date("03/04/2026 08:00", dayfirst=False) == _dt.date(2026, 3, 4)
        assert parse_date("03/04/2026 08:00", dayfirst=True) == _dt.date(2026, 4, 3)

    @pytest.mark.parametrize("text", ["10:23", "15.08.2026 soon"])
    def test_a_time_alone_or_trailing_words_are_not_dates(self, text):
        assert parse_date(text) is None

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_blank_is_none(self, blank):
        assert parse_date(blank) is None

    def test_nonsense_is_none(self):
        assert parse_date("not a date") is None


class TestPeriods:
    def test_month(self):
        assert parse_period("2026-08") == (_dt.date(2026, 8, 1), _dt.date(2026, 8, 31))

    def test_year(self):
        assert parse_period("2026") == (_dt.date(2026, 1, 1), _dt.date(2026, 12, 31))

    def test_range(self):
        assert parse_period("2026-08-05..2026-08-09") == (
            _dt.date(2026, 8, 5), _dt.date(2026, 8, 9))

    def test_february_in_a_leap_year(self):
        assert month_bounds(2028, 2)[1] == _dt.date(2028, 2, 29)

    def test_december_rolls_the_year(self):
        assert month_bounds(2026, 12)[1] == _dt.date(2026, 12, 31)

    def test_label(self):
        assert period_label(*parse_period("2026-08")) == "August 2026"
        assert period_label(*parse_period("2026")) == "2026"

    def test_rejects_nonsense(self):
        with pytest.raises(ValueError, match="cannot read period"):
            parse_period("last tuesday")


class TestKind:
    @pytest.mark.parametrize("text", ["credit", "CRDT", "in", "income", "deposit", "+"])
    def test_income_words(self, text):
        assert parse_kind(text) == INCOME

    @pytest.mark.parametrize("text", ["debit", "DBIT", "out", "expense", "payment", "-"])
    def test_expense_words(self, text):
        assert parse_kind(text) == EXPENSE

    def test_unknown_falls_back(self):
        assert parse_kind("wibble", default=EXPENSE) == EXPENSE
        assert parse_kind(None) is None

    @pytest.mark.parametrize("text,expected", [
        ("Credited", INCOME), ("Incoming", INCOME), ("Debited", EXPENSE),
        ("Direct Dep", INCOME),            # a known phrase, written with a space
    ])
    def test_one_word_and_known_phrases(self, text, expected):
        assert parse_kind(text) == expected

    @pytest.mark.parametrize("text", [
        "Credit Card", "Debit Card", "Credit Card Payment", "Debit Card Purchase",
        "CARD_PAYMENT", "Credit transfer",
    ])
    def test_a_phrase_naming_the_transaction_leaves_it_to_the_sign(self, text):
        # "credit" in "Credit Card" says how it was paid, not which way it went
        assert parse_kind(text) is None

    @pytest.mark.parametrize("text,expected", [
        ("Incoming transfer", INCOME), ("Outgoing transfer", EXPENSE),
        ("Inbound wire", INCOME), ("Outflow - card", EXPENSE),
    ])
    def test_a_phrase_with_an_unmistakable_direction_word(self, text, expected):
        assert parse_kind(text) == expected

    def test_a_phrase_with_both_directions_says_nothing(self):
        assert parse_kind("incoming or outgoing") is None


class TestLooksLikeIncome:
    @pytest.mark.parametrize("category,label", [
        ("Income", "Tax refund"),          # the category speaks first
        ("Work", "Salary"),
        ("Uncategorized", "ACME payroll"),
        ("Wages", ""),
        ("Bonuses", "Q3"),
    ])
    def test_income(self, category, label):
        assert looks_like_income(category, label)

    @pytest.mark.parametrize("category,label", [
        ("Taxes", "Income tax"),
        ("Housing", "Income tax"),
        ("Utilities", "Water & sewage"),   # "sewage" is not a wage
        ("Insurance", "Income protection"),
        ("Payroll tax", ""),
        ("Groceries", "Lidl"),
    ])
    def test_not_income(self, category, label):
        assert not looks_like_income(category, label)


class TestInferDayfirst:
    def test_one_unambiguous_date_settles_day_first(self):
        assert infer_dayfirst(["01/02/2026", "13/02/2026", "05/02/2026"]) is True

    def test_one_unambiguous_date_settles_month_first(self):
        assert infer_dayfirst(["01/02/2026", "02/13/2026", "05/02/2026"]) is False

    @pytest.mark.parametrize("values", [
        ["01/02/2026", "03/04/2026"],      # could be either
        ["2026-08-15", "2026-08-31"],      # ISO is never ambiguous
        ["26-08-15", "26-08-31"],          # two-digit year with dashes: year first
        [_dt.date(2026, 8, 15), 20260815, None, ""],
        [],
    ])
    def test_undecided(self, values):
        assert infer_dayfirst(values) is None

    def test_dashes_and_short_years_count(self):
        assert infer_dayfirst(["13-02-2026"]) is True
        assert infer_dayfirst(["02/13/26"]) is False

    def test_both_orders_in_one_column_is_an_error(self):
        with pytest.raises(ValueError, match=r"'13/01/2026'.*'01/13/2026'"):
            infer_dayfirst(["13/01/2026", "01/02/2026", "01/13/2026"])


class TestCurrencyFormatting:
    @pytest.mark.parametrize("amount,code,expected", [
        (1234.5, "USD", "$1,234.50"),
        (1234.5, "EUR", "€1,234.50"),
        (1234.5, "PLN", "1{s}234,50{s}zł"),
        (1234.5, "UAH", "1{s}234,50{s}₴"),
        (1234.5, "JPY", "¥1,235"),              # no minor unit, and rounds half up
        (1234.5, "XYZ", "1{s}234.50{s}XYZ"),    # unknown code still readable
    ])
    def test_format(self, amount, code, expected):
        assert format_money(amount, code) == expected.format(s=GROUP_SPACE)

    def test_money_rounds_half_away_from_zero(self):
        # float formatting would round half to even and show 1,234 here
        assert format_money(1234.5, "JPY") == "¥1,235"
        assert format_money(0.125, "USD") == "$0.13"

    def test_decimal_override(self):
        assert format_money(1234.5, "PLN", 0) == f"1{GROUP_SPACE}235{GROUP_SPACE}zł"

    def test_compact(self):
        assert compact_money(12_300, "PLN") == f"12.3k{GROUP_SPACE}zł"
        assert compact_money(1_200_000, "USD") == "$1.2M"

    @pytest.mark.parametrize("given,expected", [
        ("pln", "PLN"), ("zł", "PLN"), ("€", "EUR"), ("", "USD"), (None, "USD"),
    ])
    def test_normalise(self, given, expected):
        assert normalise_code(given, "USD") == expected

    @pytest.mark.parametrize("text,expected", [
        ("12.00 PLN", "PLN"), ("$12", "USD"), ("1 840,00 ₴", "UAH"), ("12", None),
    ])
    def test_sniff(self, text, expected):
        assert sniff_currency(text) == expected


class TestCoerceRow:
    def test_dict_with_aliases(self):
        row = coerce_row({"Posted Date": "2026-08-15", "Description": "Lidl",
                          "Category": "Groceries", "Amount": "-123,45",
                          "Currency": "PLN"})
        assert row.category == "Groceries"
        assert row.label == "Lidl"
        assert row.amount == Decimal("-123.45")   # sign settled later
        assert row.currency == "PLN"
        assert row.date == _dt.date(2026, 8, 15)

    def test_namedtuple(self):
        from collections import namedtuple

        Expense_ = namedtuple("Expense", ["category", "label", "amount", "currency"])
        row = coerce_row(Expense_("Housing", "Rent", 2000, "PLN"))
        assert (row.category, row.label, row.amount) == ("Housing", "Rent", Decimal("2000"))

    def test_bare_sequence(self):
        row = coerce_row(["Housing", "Rent", "2000", "PLN"])
        assert row.category == "Housing" and row.currency == "PLN"

    def test_label_stands_in_for_a_missing_category(self):
        assert coerce_row({"label": "Rent", "amount": 10}).category == "Rent"

    def test_missing_amount_is_an_error(self):
        with pytest.raises(ValueError, match="missing an amount"):
            coerce_row({"category": "Housing"})

    def test_unusable_type_is_an_error(self):
        with pytest.raises(TypeError):
            coerce_row(object())

    def test_currency_comes_from_the_amount_when_absent(self):
        assert coerce_row({"label": "x", "amount": "12,00 zł"}).currency == "PLN"

    def test_explicit_direction_wins(self):
        assert coerce_row({"label": "Pay", "amount": "-100", "type": "CREDIT"}).kind == INCOME

    def test_income_words_alone_do_not_decide_the_direction(self):
        # apply_sign_convention decides, once it knows whether the file is signed
        row = coerce_row({"category": "Taxes", "label": "Income tax", "amount": "-500"})
        assert row.kind == AUTO


class TestCoerceRows:
    def test_a_us_file_reads_every_date_month_first(self):
        days = (2, 5, 10, 14, 20, 28)
        rows = coerce_rows([{"date": f"01/{d:02d}/2026", "label": "Shop", "amount": 10}
                            for d in days])
        assert [r.date for r in rows] == [_dt.date(2026, 1, d) for d in days]

    def test_dayfirst_given_is_used(self):
        rows = coerce_rows([{"date": "03/04/2026", "amount": 1}], dayfirst=False)
        assert rows[0].date == _dt.date(2026, 3, 4)

    def test_both_orders_is_an_error_that_says_what_to_do(self):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            coerce_rows([{"date": "13/01/2026", "amount": 1},
                         {"date": "01/13/2026", "amount": 1}])


def test_pick_is_case_and_punctuation_insensitive():
    assert pick({"Posted Date": "x"}, "date") == "x"
    assert pick({"transaction_amount": 5}, "amount") == 5
    assert pick({}, "amount", "fallback") == "fallback"


def test_shorten():
    assert shorten("short", 10) == "short"
    assert shorten("a very long label indeed", 10).endswith("…")
    assert len(shorten("a very long label indeed", 10)) == 10
