"""Core data model.

A single flat row (an :class:`Expense`) is everything the library needs as input.
Direction of the money is carried by :attr:`Expense.kind` rather than by the sign
of the amount, so ``amount`` is always a non-negative :class:`~decimal.Decimal`.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Optional

from .currencies import normalise_code

__all__ = ["AUTO", "EXPENSE", "INCOME", "KINDS", "Expense", "Node", "Link", "SankeyGraph"]

EXPENSE = "expense"
INCOME = "income"
#: Direction not stated by the source -- resolved from the amount sign by
#: :func:`vme.data_store.apply_sign_convention` before anything is plotted.
AUTO = "auto"
#: Every value :attr:`Expense.kind` can take.
KINDS = (INCOME, EXPENSE, AUTO)

UNCATEGORIZED = "Uncategorized"


@dataclass(frozen=True)
class Expense:
    """One line of a budget: ``amount`` of ``currency`` moving in or out.

    ``category`` is the coarse bucket (``"Housing"``), ``label`` the detail
    (``"Rent"``). Both are free text -- the Sankey is built from whatever
    strings you use.

    ``kind`` is ``"income"``, ``"expense"`` (the default) or ``"auto"``, in any
    case; any other word raises :class:`ValueError` rather than quietly
    becoming an expense. ``currency`` takes an ISO code in any case or a
    symbol: ``"€"`` and ``"eur"`` are both stored as ``"EUR"``.
    """

    category: str = UNCATEGORIZED
    label: str = ""
    amount: Decimal = Decimal("0")
    currency: str = "USD"
    date: Optional[_dt.date] = None
    kind: str = EXPENSE
    note: str = ""

    def __post_init__(self) -> None:
        # Normalise in place; the dataclass is frozen, so go through object.
        category = (self.category or UNCATEGORIZED).strip() or UNCATEGORIZED
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "label", (self.label or "").strip())
        # The loaders store codes the same way, so a row built by hand in "€"
        # meets a report in EUR without needing a rate.
        object.__setattr__(self, "currency", normalise_code(self.currency, "USD"))
        object.__setattr__(self, "kind", _kind(self.kind))
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(str(self.amount)))

    @property
    def is_income(self) -> bool:
        return self.kind == INCOME

    @property
    def is_expense(self) -> bool:
        return self.kind != INCOME

    @property
    def is_auto(self) -> bool:
        """Direction still undecided (loaded from a file that did not say)."""
        return self.kind == AUTO

    @property
    def signed_amount(self) -> Decimal:
        """Positive for income, negative for spending."""
        return self.amount if self.is_income else -self.amount

    @property
    def leaf(self) -> str:
        """The detail name to show, falling back to the category."""
        return self.label or self.category

    def replace(self, **changes: object) -> Expense:
        return replace(self, **changes)  # type: ignore[arg-type]

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat() if self.date else None,
            "category": self.category,
            "label": self.label,
            "amount": str(self.amount),
            "currency": self.currency,
            "kind": self.kind,
            "note": self.note,
        }


def _kind(value: Any) -> str:
    """``"Income"`` -> ``"income"``; left out, an expense; anything else, an error."""
    text = str(value).strip().lower() if value is not None else ""
    if not text:
        return EXPENSE
    if text in KINDS:
        return text
    raise ValueError(
        f'kind must be "income", "expense" or "auto", not {value!r}'
    )


# --------------------------------------------------------------------------- #
# Sankey graph -- the intermediate structure every renderer draws from.
# --------------------------------------------------------------------------- #


@dataclass
class Node:
    key: str
    label: str
    depth: int
    value: Decimal = Decimal("0")
    kind: str = "category"  # income | hub | category | leaf | savings
    color: Optional[str] = None

    @property
    def float_value(self) -> float:
        return float(self.value)


@dataclass
class Link:
    source: str
    target: str
    value: Decimal
    color: Optional[str] = None

    @property
    def float_value(self) -> float:
        return float(self.value)


@dataclass
class SankeyGraph:
    """Nodes bucketed into columns (``depth``) plus the flows between them."""

    nodes: list[Node] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    currency: str = "USD"
    title: str = ""
    subtitle: str = ""

    def add_node(self, node: Node) -> Node:
        existing = self.node(node.key)
        if existing is not None:
            existing.value += node.value
            return existing
        self.nodes.append(node)
        return node

    def node(self, key: str) -> Optional[Node]:
        for n in self.nodes:
            if n.key == key:
                return n
        return None

    def add_link(self, source: str, target: str, value: Decimal,
                 color: Optional[str] = None) -> None:
        for link in self.links:
            if link.source == source and link.target == target:
                link.value += value
                return
        self.links.append(Link(source, target, value, color))

    @property
    def depths(self) -> list[int]:
        return sorted({n.depth for n in self.nodes})

    def nodes_at(self, depth: int) -> list[Node]:
        return [n for n in self.nodes if n.depth == depth]

    @property
    def total(self) -> Decimal:
        """Total value flowing out of the first column."""
        first = self.depths[0] if self.nodes else 0
        return sum((n.value for n in self.nodes_at(first)), Decimal("0"))

    def loose_nodes(self) -> list[Node]:
        """Nodes that take part in no link at all -- the 'loose elements'."""
        wired = {lk.source for lk in self.links} | {lk.target for lk in self.links}
        return [n for n in self.nodes if n.key not in wired]

    def __bool__(self) -> bool:
        return bool(self.links)
