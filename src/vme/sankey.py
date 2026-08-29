"""Turn a flat list of rows into the hierarchical graph a Sankey needs.

The shape is always the same::

    income sources  ->  budget hub  ->  categories  ->  labels
                                    \\-> savings (when you spent less than you earned)

When a file has no income rows the hub becomes "Total spent" and the left column
is simply omitted.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import Expense, Link, Node, SankeyGraph
from .theme import Theme, get_theme

__all__ = ["build_graph", "GraphOptions"]

ZERO = Decimal("0")


class GraphOptions:
    """Knobs for :func:`build_graph` (kept as a plain object so the CLI can pass it around)."""

    def __init__(self, detail: bool = True, top_categories: Optional[int] = None,
                 max_labels: int = 6, min_share: float = 0.0, show_savings: bool = True,
                 group_income: bool = False, hub_label: Optional[str] = None,
                 other_label: str = "Other"):
        self.detail = detail
        self.top_categories = top_categories
        self.max_labels = max_labels
        self.min_share = min_share
        self.show_savings = show_savings
        self.group_income = group_income
        self.hub_label = hub_label
        self.other_label = other_label


def _fold(items: "List[Tuple[str, Decimal]]", keep: Optional[int], min_share: float,
          total: Decimal, other_label: str) -> "List[Tuple[str, Decimal]]":
    """Keep the biggest ``keep`` items, sweep the rest into one 'Other' bucket."""
    ordered = sorted(items, key=lambda pair: (-pair[1], pair[0]))
    threshold = (Decimal(str(min_share)) / 100) * total if min_share and total else ZERO

    kept: "List[Tuple[str, Decimal]]" = []
    folded = ZERO
    for index, (name, value) in enumerate(ordered):
        too_many = keep is not None and index >= keep
        too_small = threshold and value < threshold
        if too_many or too_small:
            folded += value
        else:
            kept.append((name, value))
    if folded > 0:
        if not kept:  # everything got folded -- keep the single biggest anyway
            kept = [ordered[0]]
            folded -= ordered[0][1]
        if folded > 0:
            kept.append((other_label, folded))
    return kept


def build_graph(rows: Sequence[Expense], currency: str = "USD", title: str = "",
                subtitle: str = "", options: Optional[GraphOptions] = None,
                theme: Optional[Theme] = None) -> SankeyGraph:
    """Aggregate ``rows`` (already converted to ``currency``) into a :class:`SankeyGraph`."""
    options = options or GraphOptions()
    theme = theme or get_theme("light")

    graph = SankeyGraph(currency=currency, title=title, subtitle=subtitle)

    income_rows = [row for row in rows if row.is_income]
    expense_rows = [row for row in rows if not row.is_income]

    income_total = sum((row.amount for row in income_rows), ZERO)
    expense_total = sum((row.amount for row in expense_rows), ZERO)

    has_income = income_total > 0
    hub_depth = 1 if has_income else 0
    hub_key = "hub"
    hub_label = options.hub_label or ("Budget" if has_income else "Total spent")

    # ---------------------------------------------------------------- income
    if has_income:
        source_totals: "Dict[str, Decimal]" = defaultdict(lambda: ZERO)
        for row in income_rows:
            name = row.category if options.group_income else (row.label or row.category)
            source_totals[name] += row.amount
        sources = _fold(list(source_totals.items()), None, options.min_share,
                        income_total, options.other_label)
        for name, value in sources:
            key = f"in:{name}"
            graph.add_node(Node(key, name, 0, value, "income", theme.income))
            graph.add_link(key, hub_key, value, theme.income)

    hub_value = income_total if has_income else expense_total
    graph.add_node(Node(hub_key, hub_label, hub_depth, hub_value, "hub", theme.hub))

    # ------------------------------------------------------------ categories
    category_totals: "Dict[str, Decimal]" = defaultdict(lambda: ZERO)
    label_totals: "Dict[str, Dict[str, Decimal]]" = defaultdict(
        lambda: defaultdict(lambda: ZERO))
    for row in expense_rows:
        category_totals[row.category] += row.amount
        label_totals[row.category][row.leaf] += row.amount

    categories = _fold(list(category_totals.items()), options.top_categories,
                       options.min_share, expense_total, options.other_label)

    category_depth = hub_depth + 1
    palette_slot = 0
    colors: "Dict[str, str]" = OrderedDict()
    for name, value in categories:
        key = f"cat:{name}"
        if name == options.other_label and name not in category_totals:
            color = theme.other
        else:
            color = theme.color_for(palette_slot)
            palette_slot += 1
        colors[name] = color
        graph.add_node(Node(key, name, category_depth, value, "category", color))
        graph.add_link(hub_key, key, value, color)

    # ---------------------------------------------------------------- labels
    if options.detail:
        kept_names = {name for name, _ in categories}
        folded_names = [n for n in category_totals if n not in kept_names]
        detail_source: "Dict[str, Dict[str, Decimal]]" = {}
        for name in kept_names:
            if name in label_totals:
                detail_source[name] = dict(label_totals[name])
        if folded_names and options.other_label in kept_names:
            merged: "Dict[str, Decimal]" = defaultdict(lambda: ZERO)
            for name in folded_names:
                for leaf, value in label_totals[name].items():
                    merged[name if len(label_totals[name]) == 1 else leaf] += value
            detail_source[options.other_label] = dict(merged)

        for name, leaves in detail_source.items():
            single = len(leaves) == 1 and next(iter(leaves)) == name
            if single:  # a label identical to its category adds no information
                continue
            folded_leaves = _fold(list(leaves.items()), options.max_labels, 0.0,
                                  category_totals.get(name, ZERO), options.other_label)
            for leaf, value in folded_leaves:
                key = f"leaf:{name}/{leaf}"
                graph.add_node(Node(key, leaf, category_depth + 1, value, "leaf",
                                    colors.get(name, theme.other)))
                graph.add_link(f"cat:{name}", key, value, colors.get(name, theme.other))

    # --------------------------------------------------------------- savings
    leftover = income_total - expense_total
    if has_income and options.show_savings and leftover > 0:
        key = "savings"
        graph.add_node(Node(key, "Savings / left over", category_depth, leftover,
                            "savings", theme.savings))
        graph.add_link(hub_key, key, leftover, theme.savings)
    elif has_income and leftover < 0:
        # Spent more than came in -- show where the shortfall was funded from.
        key = "in:deficit"
        graph.add_node(Node(key, "From savings", 0, -leftover, "income", theme.savings))
        graph.add_link(key, hub_key, -leftover, theme.savings)
        hub = graph.node(hub_key)
        if hub is not None:
            hub.value = expense_total

    return graph


def summarise(rows: Iterable[Expense]) -> "Dict[str, Decimal]":
    """Headline totals used by the console output and the plot footer."""
    rows = list(rows)
    income = sum((r.amount for r in rows if r.is_income), ZERO)
    spent = sum((r.amount for r in rows if not r.is_income), ZERO)
    return {"income": income, "spent": spent, "net": income - spent}
