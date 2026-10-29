"""Expense: a row built by hand is stored the way a loaded one is."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vme import Expense, Visualizer
from vme.models import AUTO, EXPENSE, INCOME
from vme.tools import coerce_row


class TestKind:
    @pytest.mark.parametrize("given,kind", [
        ("income", INCOME), ("Income", INCOME), ("INCOME", INCOME), (" income ", INCOME),
        ("Expense", EXPENSE), ("AUTO", AUTO),
    ])
    def test_any_case_is_read(self, given, kind):
        assert Expense(category="Pay", amount=10, kind=given).kind == kind

    @pytest.mark.parametrize("given", [None, "", "  "])
    def test_left_out_it_is_an_expense(self, given):
        assert Expense(category="Food", amount=10, kind=given).kind == EXPENSE

    @pytest.mark.parametrize("given", ["Incom", "out", "credit", 1])
    def test_an_unknown_word_is_an_error_not_an_expense(self, given):
        with pytest.raises(ValueError, match=r'"income", "expense" or "auto", not '
                                             + repr(given)):
            Expense(category="Pay", amount=10, kind=given)

    def test_replace_reads_it_the_same_way(self):
        assert Expense(category="Pay", amount=10).replace(kind="Income").kind == INCOME

    def test_income_written_in_capitals_is_drawn_as_income(self):
        rows = [Expense(category="Pay", label="Salary", amount=100, kind="Income",
                        currency="PLN"),
                Expense(category="Food", label="Lidl", amount=40, currency="PLN")]
        v = Visualizer(rows, currency="PLN")
        assert v.graph().node("in:Salary").value == Decimal("100")
        assert v.totals()["income"] == Decimal("100")


class TestCurrency:
    @pytest.mark.parametrize("given,code", [
        ("€", "EUR"), ("zł", "PLN"), ("£", "GBP"), ("eur", "EUR"), (" pln ", "PLN"),
        ("XYZ", "XYZ"), (None, "USD"), ("", "USD"),
    ])
    def test_symbols_and_any_case_become_the_iso_code(self, given, code):
        assert Expense(category="Food", amount=10, currency=given).currency == code

    @pytest.mark.parametrize("given", ["€", "zł", "eur"])
    def test_matches_a_row_read_from_a_file(self, given):
        by_hand = Expense(category="Food", amount=10, currency=given)
        loaded = coerce_row({"category": "Food", "amount": "10", "currency": given})
        assert by_hand.currency == loaded.currency

    def test_a_row_in_euro_signs_needs_no_rate_for_a_report_in_eur(self):
        rows = [Expense(category="Food", label="Lidl", amount=10, currency="€")]
        graph = Visualizer(rows, currency="EUR").graph()
        assert graph.total == Decimal("10")
