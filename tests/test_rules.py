"""Categorisation rules: matching, reading, suggesting and writing them."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from vme.models import AUTO, EXPENSE, INCOME, Expense
from vme.rules import (
    Rule,
    Rules,
    RulesError,
    fold,
    load_rules,
    suggest,
    write_rules,
)


def row(label, amount="10", category="Card payments", note="", kind=EXPENSE, day=1):
    return Expense(category=category, label=label, amount=Decimal(amount), currency="PLN",
                   kind=kind, note=note, date=_dt.date(2026, 9, day))


def decide(rules, *rows):
    return load_rules(rules).categorise(rows)


class TestMatching:
    def test_case_does_not_matter(self):
        assert Rule("lidl", "Groceries").matches(row("CARD PAYMENT LIDL SP. Z O.O."))

    @pytest.mark.parametrize("match,label", [
        ("żabka", "ZABKA Z4521"), ("zabka", "Żabka Polska"),
        ("lodz", "ŁÓDŹ KALISKA"), ("strasse", "Hauptstraße 5"), ("cafe", "CAFÉ NERO"),
    ])
    def test_accents_do_not_matter(self, match, label):
        assert Rule(match, "x").matches(row(label))

    def test_runs_of_spaces_count_as_one(self):
        assert Rule("lidl  sp", "x").matches(row("LIDL   SP. Z O.O."))

    def test_bar_separates_alternatives(self):
        rule = Rule("orlen|shell | bp", "Transport")
        assert all(rule.matches(row(name)) for name in ("ORLEN 44", "SHELL 10", "BP 7"))
        assert not rule.matches(row("BIEDRONKA"))

    def test_re_starts_a_regular_expression(self):
        rule = Rule(r"re:^card payment \d\d\.\d\d netflix", "Subscriptions")
        assert rule.matches(row("CARD PAYMENT 03.09 NETFLIX.COM"))
        assert not rule.matches(row("BLIK NETFLIX.COM"))

    def test_the_note_is_searched_too(self):
        assert Rule("rent", "Housing").matches(row("TRANSFER OUT", note="Rent for May"))

    def test_the_category_is_not(self):
        # "car" would otherwise catch every row the bank calls "Card payments".
        assert not Rule("car", "Car").matches(row("LIDL", category="Card payments"))

    def test_fold(self):
        assert fold("  Żabka \t Polska ") == "Zabka Polska"


class TestDeciding:
    def test_the_first_rule_that_matches_wins(self):
        done = decide([("lidl sp", "Groceries"), ("lidl", "Shopping")], row("LIDL SP. Z O.O."))
        assert done.rows[0].category == "Groceries"

    def test_category_and_label_are_replaced(self):
        done = decide([("lidl", "Groceries", "Lidl")], row("LIDL SP. Z O.O. 0571"))
        assert (done.rows[0].category, done.rows[0].label) == ("Groceries", "Lidl")

    def test_without_a_label_the_label_stays(self):
        done = decide({"lidl": "Groceries"}, row("LIDL SP. Z O.O. 0571"))
        assert done.rows[0].label == "LIDL SP. Z O.O. 0571"

    def test_skip_drops_the_row(self):
        done = decide({"own account": "skip"}, row("TRANSFER OWN ACCOUNT"), row("LIDL"))
        assert [r.label for r in done.rows] == ["LIDL"]
        assert [r.label for r in done.skipped] == ["TRANSFER OWN ACCOUNT"]

    def test_skip_is_read_in_any_case(self):
        assert Rule("x", "Skip").skips and not Rule("x", "Skipping").skips

    def test_unmatched_rows_are_left_alone(self):
        original = row("BIEDRONKA")
        done = decide({"lidl": "Groceries"}, original)
        assert done.rows == [original] and done.rules == [None]

    def test_a_rule_with_no_category_does_nothing(self):
        rules = load_rules([("lidl", "", "Lidl"), ("lidl", "Groceries")])
        assert [rule.match for rule in rules.incomplete] == ["lidl"]
        assert rules.categorise([row("LIDL")]).rows[0].category == "Groceries"

    def test_the_direction_is_left_alone(self):
        refund = row("LIDL REFUND", kind=INCOME)
        assert decide({"lidl": "Groceries"}, refund).rows[0].kind == INCOME

    def test_rules_that_matched_are_named(self):
        rules = load_rules([("lidl", "Groceries"), ("netflix", "Subscriptions")])
        assert [rule.match for rule in rules.categorise([row("LIDL")]).used] == ["lidl"]

    @pytest.mark.parametrize("match", ["", "   ", "|", "re:"])
    def test_a_rule_must_look_for_something(self, match):
        with pytest.raises(RulesError):
            Rule(match, "Groceries")

    def test_a_bad_expression_names_the_rule(self):
        with pytest.raises(RulesError, match="rules.csv line 4: '\\(lidl' is not a regular"):
            Rule("re:(lidl", "Groceries", where="rules.csv line 4")


class TestReadingCsv:
    def write(self, tmp_path, text, name="rules.csv", encoding="utf-8"):
        path = tmp_path / name
        path.write_text(text, encoding=encoding)
        return path

    def test_a_plain_file(self, tmp_path):
        rules = load_rules(self.write(tmp_path, "match,category,label\nlidl,Groceries,Lidl\n"))
        assert [(r.match, r.category, r.label) for r in rules] == [("lidl", "Groceries", "Lidl")]
        assert rules.source.endswith("rules.csv") and rules.rules[0].where.endswith("line 2")

    @pytest.mark.parametrize("separator", [";", "\t"])
    def test_semicolons_and_tabs(self, tmp_path, separator):
        text = f"match{separator}category\nlidl{separator}Food, drinks\n"
        rules = load_rules(self.write(tmp_path, text))
        assert rules.rules[0].category == "Food, drinks"

    def test_excel_byte_order_mark_and_accents(self, tmp_path):
        rules = load_rules(self.write(tmp_path, "match,category\nżabka,Zakupy\n",
                                      encoding="utf-8-sig"))
        assert rules.rules[0].match == "żabka"

    def test_columns_in_any_order_and_case(self, tmp_path):
        rules = load_rules(self.write(tmp_path, "Label,MATCH,Category\nLidl,lidl,Groceries\n"))
        assert (rules.rules[0].match, rules.rules[0].label) == ("lidl", "Lidl")

    def test_comments_and_blank_lines(self, tmp_path):
        text = ("# my rules\nmatch,category,comment\n\n# lidl,Groceries\n"
                "netflix,Subscriptions,cancel in May\n")
        rules = load_rules(self.write(tmp_path, text))
        assert [r.match for r in rules] == ["netflix"]
        assert rules.rules[0].where.endswith("line 5")

    def test_only_a_match_column(self, tmp_path):
        rules = load_rules(self.write(tmp_path, "match\nlidl\n"))
        assert rules.incomplete == rules.rules

    @pytest.mark.parametrize("text,message", [
        ("", "is empty"),
        ("category,label\nGroceries,Lidl\n", "no match column"),
        ("match,catgory\nlidl,Groceries\n", "unknown column 'catgory'"),
        ("match,category\nlidl,Food, drinks\n", "line 2: 3 values but 2 columns"),
        ("match,category\n,Groceries\n", "line 2: the match is empty"),
    ])
    def test_mistakes_name_the_file_and_line(self, tmp_path, text, message):
        with pytest.raises(RulesError, match=message):
            load_rules(self.write(tmp_path, text))

    def test_a_missing_file(self, tmp_path):
        with pytest.raises(RulesError, match="cannot open"):
            load_rules(tmp_path / "nope.csv")


class TestReadingJsonAndPython:
    def test_a_json_list(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text('[{"match": "lidl", "category": "Groceries", "label": "Lidl"}]')
        assert load_rules(path).rules[0].label == "Lidl"

    def test_a_json_object(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text('{"lidl": "Groceries", "orlen": ["Transport", "Fuel"]}')
        assert [(r.category, r.label) for r in load_rules(path)] == [
            ("Groceries", ""), ("Transport", "Fuel")]

    def test_bad_json_names_the_line(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text('[\n{"match": "lidl",}\n]')
        with pytest.raises(RulesError, match="rules.json line 2"):
            load_rules(path)

    def test_an_unknown_key(self):
        with pytest.raises(RulesError, match="unknown key 'catgory'"):
            load_rules([{"match": "lidl", "catgory": "Groceries"}])

    def test_python_shapes(self):
        rules = load_rules([Rule("lidl", "Groceries"), ("orlen", "Transport", "Fuel"),
                            {"match": "netflix", "category": "Subscriptions"}])
        assert [r.match for r in rules] == ["lidl", "orlen", "netflix"]

    def test_nothing_is_no_rules(self):
        assert len(load_rules(None)) == 0

    def test_rules_pass_through(self):
        rules = Rules([Rule("lidl", "Groceries")])
        assert load_rules(rules) is rules

    def test_the_wrong_type(self):
        with pytest.raises(TypeError, match="rules must be"):
            load_rules(42)


class TestSuggest:
    def test_words_every_row_shares_are_passed_over(self):
        rows = [row("CARD PAYMENT 02.09 LIDL SP. Z O.O. 0571 WARSZAWA", day=2),
                row("CARD PAYMENT 09.09 LIDL SP. Z O.O. 0571 WARSZAWA", day=9),
                row("CARD PAYMENT 03.09 NETFLIX.COM", day=3),
                row("CARD PAYMENT 16.09 ZABKA Z4521 K.1 WARSZAWA", day=16)]
        groups = suggest(rows)
        assert [(g.match, len(g.rows)) for g in groups] == [
            ("lidl sp. z o.o.", 2), ("netflix.com", 1), ("zabka", 1)]

    def test_the_label_offered_is_tidied(self):
        assert suggest([row("BLIK 19.09 ALLEGRO.PL")])[0].label == "Allegro.pl"
        assert suggest([row("Netflix")])[0].label == "Netflix"

    def test_more_rows_tell_shared_words_apart(self):
        # Alone, "card payment" looks as much like a payee as "zabka" does.
        alone = row("CARD PAYMENT 16.09 ZABKA Z4521")
        context = [row("CARD PAYMENT 04.09 LIDL"), row("CARD PAYMENT 03.09 NETFLIX"), alone]
        assert suggest([alone])[0].match == "card payment"
        assert suggest([alone], among=context)[0].match == "zabka"

    def test_biggest_total_first(self):
        groups = suggest([row("A SHOP", "5"), row("B SHOP 1", "20"), row("C SHOP 2", "3")])
        assert [g.total for g in groups] == [Decimal("20"), Decimal("5"), Decimal("3")]

    def test_income_is_marked(self):
        groups = suggest([row("ACME SALARY", "9800", kind=INCOME), row("LIDL")])
        assert [g.is_income for g in groups] == [True, False]

    def test_a_row_with_only_numbers(self):
        group = suggest([row("0571 12.09")])[0]
        assert group.match == "0571 12.09"

    def test_the_suggested_match_finds_its_rows(self):
        rows = [row("CARD PAYMENT 02.09 LIDL SP. Z O.O. 0571"),
                row("PŁATNOŚĆ KARTĄ 12.09 ŻABKA Z1 KRAKÓW")]
        for group in suggest(rows):
            assert all(Rule(group.match, "x").matches(r) for r in group.rows)


class TestWriteRules:
    def groups(self):
        return suggest([row("CARD PAYMENT 02.09 LIDL SP. Z O.O.", "124.15"),
                        row("CARD PAYMENT 03.09 NETFLIX.COM", "60"),
                        row("TRANSFER IN ACME SALARY", "9800", kind=INCOME)])

    def test_a_new_file_to_fill_in(self, tmp_path):
        path = tmp_path / "rules.csv"
        assert write_rules(str(path), self.groups(), "PLN") == 3
        raw = path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")             # so Excel reads it as UTF-8
        lines = raw.decode("utf-8-sig").splitlines()
        assert lines[0] == "match,category,label,comment"
        assert lines[1].startswith("transfer in acme salary,,Transfer In Acme Salary,")
        assert "+9\u202f800\u202fzł" in lines[1]          # GROUP_SPACE, as format_money writes
        rules = load_rules(path)
        assert len(rules) == 3 and rules.incomplete == rules.rules

    def test_adding_to_a_file_keeps_its_separator_and_rules(self, tmp_path):
        path = tmp_path / "rules.csv"
        path.write_text("match;category\nlidl;Groceries", encoding="utf-8")
        assert write_rules(str(path), self.groups(), "PLN") == 2
        text = path.read_text(encoding="utf-8")
        assert text.startswith("match;category\nlidl;Groceries\n")
        assert "netflix.com;" in text and "lidl sp. z o.o." not in text
        assert [r.match for r in load_rules(path)][-1] == "netflix.com"

    def test_payees_a_rule_covers_are_not_added_twice(self, tmp_path):
        # Filled in or not, and however the match was shortened.
        path = tmp_path / "rules.csv"
        path.write_text("match,category\nlidl,\nnetflix,Subscriptions\n", encoding="utf-8")
        assert write_rules(str(path), self.groups(), "PLN") == 1
        assert write_rules(str(path), self.groups(), "PLN") == 0

    def test_only_csv(self, tmp_path):
        with pytest.raises(RulesError, match="CSV"):
            write_rules(str(tmp_path / "rules.json"), self.groups())

    def test_a_file_that_is_not_utf8(self, tmp_path):
        path = tmp_path / "rules.csv"
        path.write_bytes("match,category\nżabka,Zakupy\n".encode("cp1250"))
        with pytest.raises(RulesError, match="not UTF-8"):
            write_rules(str(path), self.groups())

    def test_rows_without_a_description_are_left_out(self, tmp_path):
        groups = suggest([row("", note="")])
        assert write_rules(str(tmp_path / "rules.csv"), groups) == 0


def test_auto_rows_keep_their_sign_for_the_convention():
    # Rules run before the sign convention: they must not touch amount or kind.
    raw = Expense(category="X", label="LIDL", amount=Decimal("-12"), kind=AUTO)
    out = decide({"lidl": "Groceries"}, raw).rows[0]
    assert (out.amount, out.kind) == (Decimal("-12"), AUTO)
