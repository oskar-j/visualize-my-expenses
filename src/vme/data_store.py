"""Row storage, cleaning and validation.

``CalculatorBase`` owns the validation + console-output contract, ``Calculator``
owns the rows. :class:`~vme.visualizer.Visualizer` sits on top and does the
plotting; nothing here knows about matplotlib.
"""

from __future__ import annotations

import datetime as _dt
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .currencies import RateError, get_currency, load_rates, normalise_code
from .models import AUTO, EXPENSE, INCOME, Expense
from .sankey import GraphOptions, build_graph, summarise
from .tools import coerce_rows, format_money, parse_period, period_label, shorten

__all__ = ["CalculatorBase", "Calculator", "apply_sign_convention", "convert",
           "CurrencyError", "RateError", "SIGN_CONVENTIONS", "currencies_used",
           "load_rates"]

ZERO = Decimal("0")

#: How to read the sign of an amount when the source did not say.
SIGN_CONVENTIONS = ("auto", "statement", "expenses", "income")


class CurrencyError(ValueError):
    """Rows are in more than one currency and no rate was supplied."""


def apply_sign_convention(rows: Sequence[Expense], convention: str = "auto") -> List[Expense]:
    """Decide, once per data set, what a negative amount means.

    * ``statement`` -- bank convention: negative is money out, positive money in.
    * ``expenses``  -- everything is spending (the shape of a plain expense list).
    * ``income``    -- everything is income.
    * ``auto``      -- ``expenses`` when no amount is negative, ``statement`` otherwise.

    Rows whose source stated a direction explicitly are never overridden.
    """
    if convention not in SIGN_CONVENTIONS:
        raise ValueError(
            f"unknown sign convention {convention!r}; choose from: {', '.join(SIGN_CONVENTIONS)}"
        )

    undecided = [row for row in rows if row.kind == AUTO]
    if convention == "auto":
        has_negative = any(row.amount < 0 for row in undecided)
        convention = "statement" if has_negative else "expenses"

    resolved: List[Expense] = []
    for row in rows:
        kind = row.kind
        if kind == AUTO:
            if convention == "statement":
                kind = INCOME if row.amount > 0 else EXPENSE
            elif convention == "income":
                kind = INCOME
            else:
                kind = EXPENSE
        resolved.append(row.replace(amount=abs(row.amount), kind=kind))
    return resolved


def currencies_used(rows: Iterable[Expense]) -> List[str]:
    """Every currency appearing in ``rows``, most common first."""
    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.currency] += 1
    return [code for code, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def convert(rows: Sequence[Expense], target: str,
            rates: Optional[Mapping[str, Any]] = None) -> List[Expense]:
    """Restate every row in ``target``.

    ``rates`` maps a source currency to how much of ``target`` one of its units is
    worth -- ``{"EUR": 4.30}`` in a PLN report means one euro buys 4.30 złoty.
    Rows already in ``target`` pass through untouched, so a single-currency file
    never needs a rate at all.
    """
    target = normalise_code(target, "USD")
    table = {normalise_code(code): Decimal(str(value))
             for code, value in (rates or {}).items()}
    bad = sorted(code for code, rate in table.items() if rate <= 0)
    if bad:
        raise CurrencyError(
            "conversion rate for {} must be positive".format(", ".join(bad))
        )
    table[target] = Decimal("1")

    present = currencies_used(rows)
    missing = [code for code in present if code not in table]
    if missing:
        names = ", ".join(f"{code} ({get_currency(code).name})" for code in missing)
        example = missing[0]
        raise CurrencyError(
            f"rows are in {names} but the report is in {target}. Give a rate for each one, "
            f"for example:  --rate {example}=4.30   (one {example} is worth 4.30 {target})"
        )

    converted: List[Expense] = []
    for row in rows:
        if row.currency == target:
            converted.append(row)
            continue
        converted.append(row.replace(amount=row.amount * table[row.currency],
                                     currency=target))
    return converted


class CalculatorBase:
    """Validation and console-output contract shared by everything above it."""

    rows: List[Expense]
    currency: str
    verbose: bool

    def problems(self) -> List[str]:
        """Everything wrong with the current rows, worst first. Empty means clean."""
        found: List[str] = []
        rows = getattr(self, "rows", None) or []
        if not rows:
            return ["no rows to plot"]

        for index, row in enumerate(rows):
            where = f"row {index}"
            if not isinstance(row, Expense):
                found.append(f"{where}: not an Expense (got {type(row).__name__})")
                continue
            try:
                amount = Decimal(row.amount)
            except (InvalidOperation, TypeError, ValueError):
                found.append(f"{where}: amount {row.amount!r} is not a number")
                continue
            if not amount.is_finite():
                found.append(f"{where}: amount is not finite")
            elif amount < 0:
                found.append(f"{where}: negative amount {amount} -- "
                             "call apply_sign_convention() first")
            if not row.category and not row.label:
                found.append(f"{where}: has neither a category nor a label")
            if row.kind == AUTO:
                found.append(f"{where}: direction is still undecided")

        currencies = {row.currency for row in rows if isinstance(row, Expense)}
        if len(currencies) > 1:
            found.append("mixed currencies ({}) -- convert them first"
                         .format(", ".join(sorted(currencies))))

        if all(getattr(row, "amount", ZERO) == 0 for row in rows):
            found.append("every amount is zero -- nothing to draw")

        graph = getattr(self, "_last_graph", None)
        if graph is not None:
            loose = graph.loose_nodes()
            if loose:
                found.append("loose elements: {} connect to nothing"
                             .format(", ".join(n.label for n in loose[:5])))
        return found

    def _verify(self, verbose: bool = False) -> bool:
        """True when the data is clean enough to plot."""
        found = self.problems()
        if found and verbose:
            print(f"vme: {len(found)} problem(s) found:", file=sys.stderr)
            for problem in found:
                print(f"  - {problem}", file=sys.stderr)
        return not found

    def print_to_console(self, file=None, width: int = 46) -> None:
        """A plain-text breakdown -- the quick sanity check before plotting."""
        stream = file or sys.stdout
        rows = getattr(self, "rows", None) or []
        currency = getattr(self, "currency", "USD")
        if not rows:
            print("No expenses loaded.", file=stream)
            return

        totals = summarise(rows)
        title = getattr(self, "title", "") or "Expenses"
        print(title, file=stream)
        print("=" * max(len(title), 24), file=stream)

        by_category: Dict[str, Decimal] = defaultdict(lambda: ZERO)
        by_label: Dict[str, Dict[str, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: ZERO))
        for row in rows:
            if row.is_income:
                continue
            by_category[row.category] += row.amount
            by_label[row.category][row.leaf] += row.amount

        spent = totals["spent"] or Decimal("1")
        for category, value in sorted(by_category.items(), key=lambda kv: -kv[1]):
            share = value / spent * 100
            print("\n{:<{w}} {:>12}  {:>5.1f}%".format(
                shorten(category, width - 20), format_money(value, currency), share, w=width - 20),
                file=stream)
            leaves = sorted(by_label[category].items(), key=lambda kv: -kv[1])
            if len(leaves) == 1 and leaves[0][0] == category:
                continue
            for leaf, leaf_value in leaves:
                print("  {:<{w}} {:>12}".format(
                    shorten(leaf, width - 24), format_money(leaf_value, currency), w=width - 24),
                    file=stream)

        print("\n" + "-" * width, file=stream)
        if totals["income"]:
            print("{:<{w}} {:>12}".format("Income", format_money(totals["income"], currency),
                                          w=width - 13), file=stream)
        print("{:<{w}} {:>12}".format("Spent", format_money(totals["spent"], currency),
                                      w=width - 13), file=stream)
        if totals["income"]:
            leftover = totals["net"]
            name = "Left over" if leftover >= 0 else "Overspent by"
            print("{:<{w}} {:>12}".format(name, format_money(abs(leftover), currency),
                                          w=width - 13), file=stream)


class Calculator(CalculatorBase):
    """Owns the rows: loading, filtering, cleaning and aggregation."""

    def __init__(self, rows: Optional[Iterable[Any]] = None, currency: str = "USD",
                 verbose: bool = False):
        self.verbose = bool(verbose)
        self.currency = normalise_code(currency, "USD")
        self.title = ""
        self.subtitle = ""
        self._last_graph = None
        self.set_rows(rows)

    # ------------------------------------------------------------- row store
    def set_rows(self, rows: Optional[Iterable[Any]]) -> Calculator:
        """Replace the current rows. Anything dict-like or tuple-like is accepted."""
        self.rows = coerce_rows(rows, self.currency)
        self._last_graph = None
        return self

    def append_rows(self, rows: Optional[Iterable[Any]]) -> Calculator:
        """Add more rows to the ones already loaded."""
        if getattr(self, "rows", None) is None:
            return self.set_rows(rows)
        self.rows = self.rows + coerce_rows(rows, self.currency)
        self._last_graph = None
        return self

    def insert_row(self, row: Any) -> Calculator:
        """Add a single row."""
        return self.append_rows([row])

    # ------------------------------------------------------------- pipeline
    def currencies(self) -> List[str]:
        """Every currency present in the loaded rows, most common first."""
        return currencies_used(self.rows)

    def _prepare(self, sign: str = "auto", rates: Optional[Mapping[str, Any]] = None,
                 period: Optional[str] = None, verbose: Optional[bool] = None) -> Calculator:
        """Resolve directions, convert currencies and apply the period filter.

        Mutates the calculator in place and returns it, so it can be chained.
        """
        verbose = self.verbose if verbose is None else verbose
        rows = apply_sign_convention(self.rows, sign)
        if verbose:
            foreign = [c for c in currencies_used(rows) if c != self.currency]
            if foreign:
                print("vme: converting {} into {}".format(", ".join(foreign),
                                                          self.currency),
                      file=sys.stderr)
        rows = convert(rows, self.currency, rates)

        if period:
            start, end = parse_period(period)
            kept, undated, outside = [], 0, 0
            for row in rows:
                if row.date is None:
                    undated += 1
                elif start <= row.date <= end:
                    kept.append(row)
                else:
                    outside += 1
            if verbose:
                print(f"vme: {period_label(start, end)}: kept {len(kept)} rows, "
                      f"skipped {outside} outside the period, {undated} without a date",
                      file=sys.stderr)
            if not kept:
                raise ValueError(
                    f"no rows fall inside {period_label(start, end)}"
                    + (f" ({undated} rows have no date at all)" if undated else "")
                )
            rows = kept
            if not self.subtitle:
                self.subtitle = period_label(start, end)

        self.rows = rows
        self._last_graph = None
        return self

    def date_range(self) -> Optional[Tuple[_dt.date, _dt.date]]:
        dates = [row.date for row in self.rows if row.date is not None]
        return (min(dates), max(dates)) if dates else None

    def totals(self) -> Dict[str, Decimal]:
        return summarise(self.rows)

    def build_graph(self, options: Optional[GraphOptions] = None, theme=None):
        """Aggregate the current rows into a :class:`~vme.models.SankeyGraph`."""
        graph = build_graph(self.rows, currency=self.currency, title=self.title,
                            subtitle=self.subtitle, options=options, theme=theme)
        self._last_graph = graph
        return graph
