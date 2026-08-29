"""Shared fixtures. Rendering tests force the headless Agg backend."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import matplotlib
import pytest

matplotlib.use("Agg")

from vme.models import EXPENSE, INCOME, Expense  # noqa: E402


@pytest.fixture
def rows():
    """A small, complete month: two income sources, four spending categories."""
    def expense(day, category, label, amount, currency="PLN"):
        return Expense(category=category, label=label, amount=Decimal(amount),
                       currency=currency, date=_dt.date(2026, 8, day), kind=EXPENSE)

    return [
        Expense(category="Income", label="Salary", amount=Decimal("6000"),
                currency="PLN", date=_dt.date(2026, 8, 1), kind=INCOME),
        Expense(category="Income", label="Freelance", amount=Decimal("1000"),
                currency="PLN", date=_dt.date(2026, 8, 5), kind=INCOME),
        expense(2, "Housing", "Rent", "2000"),
        expense(3, "Housing", "Electricity", "200"),
        expense(4, "Groceries", "Lidl", "500"),
        expense(11, "Groceries", "Market", "300"),
        expense(6, "Transport", "Fuel", "400"),
        expense(20, "Leisure", "Cinema", "100"),
    ]


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "budget.csv"
    path.write_text(
        "date,category,label,amount,currency,kind\n"
        "2026-08-01,Income,Salary,6000,PLN,income\n"
        "2026-08-02,Housing,Rent,2000,PLN,expense\n"
        "2026-08-04,Groceries,Lidl,500,PLN,expense\n"
        "2026-09-04,Groceries,Lidl,450,PLN,expense\n",
        encoding="utf-8",
    )
    return path
