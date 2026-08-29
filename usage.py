"""Smoke check and worked example: run `python usage.py` from the repo root.

Writes three PNGs into examples/output/ -- a plain month, the same month in the
dark theme, and a month whose rows are in four different currencies.
"""

from __future__ import annotations

import os
from collections import namedtuple

from vme import Visualizer

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, "examples")
OUTPUT = os.path.join(EXAMPLES, "output")

# Rows are duck-typed: dicts, dataclasses, namedtuples and vme.Expense all work.
Expense = namedtuple("Expense", ["category", "label", "amount", "currency", "kind"])


def spend(category, label, amount, currency="PLN"):
    return Expense(category, label, amount, currency, "expense")


def earn(label, amount, currency="PLN"):
    return Expense("Income", label, amount, currency, "income")


my_expenses = [
    earn("Salary", 9800),
    earn("Freelance", 1450),
    spend("Housing", "Rent", 3200),
    spend("Housing", "Electricity", 210.40),
    spend("Housing", "Internet", 79),
    spend("Groceries", "Biedronka", 801.05),
    spend("Groceries", "Lidl", 297.55),
    spend("Groceries", "Local market", 164),
    spend("Transport", "Fuel", 320),
    spend("Transport", "Monthly pass", 110),
    spend("Eating out", "Lunches", 486.30),
    spend("Eating out", "Coffee", 142.60),
    spend("Health", "Dentist", 450),
    spend("Health", "Pharmacy", 178.90),
    spend("Leisure", "Concert tickets", 240),
    spend("Leisure", "Books", 127.40),
    spend("Family", "Kids' school trip", 300),
]


def main() -> None:
    os.makedirs(OUTPUT, exist_ok=True)

    # 1. Rows you built yourself.
    plot = Visualizer(rows=my_expenses, currency="PLN", title="August 2026")
    plot.print_to_console()
    print("\nwrote", plot.create_png(os.path.join(OUTPUT, "usage-august.png")))

    # 2. The same data, dark theme, categories only.
    dark = Visualizer(rows=my_expenses, currency="PLN", title="August 2026",
                      theme="dark", detail=False)
    print("wrote", dark.create_png(os.path.join(OUTPUT, "usage-august-dark.png")))

    # 3. A file whose rows are in PLN, EUR, UAH and USD. Each foreign currency
    #    needs a rate: one unit of it, expressed in the report currency.
    trip = Visualizer.from_file(
        os.path.join(EXAMPLES, "trip-multicurrency.csv"),
        currency="PLN",
        rates=os.path.join(EXAMPLES, "rates-pln.json"),
        title="August 2026 — four currencies",
        period="2026-08",
    )
    print("wrote", trip.create_png(os.path.join(OUTPUT, "usage-trip.png")))
    print(trip.footer())


if __name__ == "__main__":
    main()
