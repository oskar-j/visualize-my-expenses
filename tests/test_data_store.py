"""Sign conventions, currency conversion, filtering and validation."""

from __future__ import annotations

import datetime as _dt
import io
from decimal import Decimal

import pytest

from vme.currencies import RateError, load_rates
from vme.data_store import (
    Calculator,
    CurrencyError,
    apply_sign_convention,
    convert,
    currencies_used,
)
from vme.models import AUTO, EXPENSE, INCOME, Expense


def row(amount, kind=AUTO, currency="PLN", category="Food", date=None):
    return Expense(category=category, label="x", amount=Decimal(str(amount)),
                   currency=currency, kind=kind, date=date)


class TestSignConvention:
    def test_auto_reads_negatives_as_spending(self):
        out = apply_sign_convention([row("-100"), row("2000")])
        assert [r.kind for r in out] == [EXPENSE, INCOME]
        assert [r.amount for r in out] == [Decimal("100"), Decimal("2000")]

    def test_auto_treats_an_all_positive_file_as_expenses(self):
        out = apply_sign_convention([row("100"), row("250")])
        assert all(r.kind == EXPENSE for r in out)

    def test_statement_is_explicit(self):
        out = apply_sign_convention([row("100")], "statement")
        assert out[0].kind == INCOME

    def test_expenses_forces_spending(self):
        out = apply_sign_convention([row("100"), row("-50")], "expenses")
        assert all(r.kind == EXPENSE for r in out)
        assert [r.amount for r in out] == [Decimal("100"), Decimal("50")]

    def test_income_forces_income(self):
        assert apply_sign_convention([row("100")], "income")[0].kind == INCOME

    def test_a_stated_direction_is_never_overridden(self):
        out = apply_sign_convention([row("-100", kind=INCOME)], "statement")
        assert out[0].kind == INCOME and out[0].amount == Decimal("100")

    def test_amounts_come_out_unsigned(self):
        assert all(r.amount >= 0 for r in apply_sign_convention([row("-7"), row("7")]))

    def test_an_unknown_convention_is_rejected(self):
        with pytest.raises(ValueError, match="unknown sign convention"):
            apply_sign_convention([row("1")], "sideways")


class TestConvert:
    def test_a_single_currency_needs_no_rate(self):
        out = convert([row(100, currency="PLN")], "PLN")
        assert out[0].amount == Decimal("100")

    def test_converts_with_a_rate(self):
        out = convert([row(100, currency="EUR")], "PLN", {"EUR": "4.30"})
        assert out[0].amount == Decimal("430.00") and out[0].currency == "PLN"

    def test_mixes_currencies(self):
        rows = [row(100, currency="EUR"), row(1000, currency="UAH"),
                row(50, currency="PLN")]
        out = convert(rows, "PLN", {"EUR": 4.3, "UAH": 0.095})
        assert [r.currency for r in out] == ["PLN"] * 3
        assert out[1].amount == Decimal("95.0")

    def test_a_missing_rate_names_the_currency_and_the_flag(self):
        with pytest.raises(CurrencyError) as caught:
            convert([row(100, currency="UAH")], "PLN")
        message = str(caught.value)
        assert "UAH" in message and "Ukrainian hryvnia" in message and "--rate" in message

    def test_a_non_positive_rate_is_rejected(self):
        with pytest.raises(CurrencyError, match="must be positive"):
            convert([row(1, currency="EUR")], "PLN", {"EUR": 0})

    def test_currencies_used_is_ordered_by_frequency(self):
        rows = [row(1, currency="PLN"), row(1, currency="EUR"), row(1, currency="PLN")]
        assert currencies_used(rows) == ["PLN", "EUR"]


class TestRatesFiles:
    def test_flat_json(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text('{"EUR": 4.3, "USD": 3.95}')
        assert load_rates(str(path))["EUR"] == Decimal("4.3")

    def test_json_with_a_base(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text('{"base": "PLN", "rates": {"EUR": 4.3}}')
        assert load_rates(str(path), "PLN")["EUR"] == Decimal("4.3")

    def test_a_mismatched_base_is_refused(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text('{"base": "PLN", "rates": {"EUR": 4.3}}')
        with pytest.raises(RateError, match="against PLN"):
            load_rates(str(path), "USD")

    def test_csv(self, tmp_path):
        path = tmp_path / "r.csv"
        path.write_text("currency,rate\nEUR,4.30\nUAH,0.095\n")
        rates = load_rates(str(path))
        assert rates["UAH"] == Decimal("0.095")

    def test_csv_without_the_right_columns(self, tmp_path):
        path = tmp_path / "r.csv"
        path.write_text("a,b\n1,2\n")
        with pytest.raises(RateError, match="need a 'currency' column"):
            load_rates(str(path))

    def test_a_negative_rate_is_refused(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text('{"EUR": -1}')
        with pytest.raises(RateError, match="must be positive"):
            load_rates(str(path))

    def test_a_missing_file_is_reported(self, tmp_path):
        with pytest.raises(RateError, match="cannot open"):
            load_rates(str(tmp_path / "nope.json"))


class TestCalculator:
    def test_set_and_append(self):
        calc = Calculator(currency="PLN")
        assert calc.rows == []
        calc.set_rows([{"category": "Food", "amount": 10}])
        calc.append_rows([{"category": "Fuel", "amount": 20}])
        calc.insert_row({"category": "Rent", "amount": 30})
        assert len(calc.rows) == 3

    def test_append_before_set_still_works(self):
        # the old Calculator read self.rows before it existed
        calc = Calculator.__new__(Calculator)
        calc.verbose = False
        calc.currency = "PLN"
        calc._last_graph = None
        calc.append_rows([{"category": "Food", "amount": 10}])
        assert len(calc.rows) == 1

    def test_period_filter_keeps_the_month(self, rows):
        calc = Calculator(rows, currency="PLN")
        calc._prepare(period="2026-08")
        assert len(calc.rows) == len(rows)
        assert calc.subtitle == "August 2026"

    def test_an_empty_period_is_an_error(self, rows):
        calc = Calculator(rows, currency="PLN")
        with pytest.raises(ValueError, match="no rows fall inside"):
            calc._prepare(period="2026-09")

    def test_period_filter_narrows(self, rows):
        calc = Calculator(rows, currency="PLN")
        calc._prepare(period="2026-08-01..2026-08-04")
        assert len(calc.rows) == 4

    def test_date_range(self, rows):
        calc = Calculator(rows, currency="PLN")
        assert calc.date_range() == (_dt.date(2026, 8, 1), _dt.date(2026, 8, 20))

    def test_totals(self, rows):
        totals = Calculator(rows, currency="PLN").totals()
        assert totals["income"] == Decimal("7000")
        assert totals["spent"] == Decimal("3500")
        assert totals["net"] == Decimal("3500")

    def test_verbose_reports_the_conversion(self, capsys):
        calc = Calculator([row(10, currency="EUR")], currency="PLN", verbose=True)
        calc._prepare(rates={"EUR": 4.3})
        assert "converting EUR into PLN" in capsys.readouterr().err


class TestValidation:
    def test_clean_rows_pass(self, rows):
        calc = Calculator(rows, currency="PLN")
        calc._prepare()
        assert calc.problems() == []
        assert calc._verify() is True

    def test_no_rows_is_a_problem(self):
        assert Calculator([]).problems() == ["no rows to plot"]

    def test_negative_amounts_are_a_problem(self):
        calc = Calculator(currency="PLN")
        calc.rows = [row("-5", kind=EXPENSE)]
        assert any("negative amount" in p for p in calc.problems())

    def test_an_undecided_direction_is_a_problem(self):
        calc = Calculator(currency="PLN")
        calc.rows = [row("5")]
        assert any("undecided" in p for p in calc.problems())

    def test_mixed_currencies_are_a_problem(self):
        calc = Calculator(currency="PLN")
        calc.rows = [row(1, EXPENSE, "PLN"), row(1, EXPENSE, "EUR")]
        assert any("mixed currencies" in p for p in calc.problems())

    def test_all_zero_is_a_problem(self):
        calc = Calculator(currency="PLN")
        calc.rows = [row(0, EXPENSE)]
        assert any("every amount is zero" in p for p in calc.problems())

    def test_verify_lists_problems_when_verbose(self, capsys):
        calc = Calculator([])
        assert calc._verify(verbose=True) is False
        assert "no rows to plot" in capsys.readouterr().err

    def test_console_output_covers_the_categories(self, rows):
        calc = Calculator(rows, currency="PLN")
        calc._prepare()
        buffer = io.StringIO()
        calc.print_to_console(file=buffer)
        text = buffer.getvalue()
        for expected in ("Housing", "Rent", "Groceries", "Income", "Spent", "Left over"):
            assert expected in text

    def test_console_output_without_rows(self):
        buffer = io.StringIO()
        Calculator([]).print_to_console(file=buffer)
        assert "No expenses loaded" in buffer.getvalue()
