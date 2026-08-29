"""QIF -- Quicken Interchange Format, still the lingua franca of older exports."""

from __future__ import annotations

from typing import List, Optional

from ..models import EXPENSE, INCOME, Expense
from ..tools import parse_amount, parse_date
from .base import Format, LoaderError, read_text, register

__all__ = ["load_qif"]


def load_qif(path: str, encoding: Optional[str] = None, default_currency: str = "USD",
             dayfirst: Optional[bool] = None, **_: object) -> List[Expense]:
    text = read_text(path, encoding)
    expenses: List[Expense] = []
    record: "dict[str, str]" = {}

    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line:
            continue
        if line.startswith("!"):  # !Type:Bank, !Account, ...
            continue
        if line.startswith("^"):
            entry = _build(record, default_currency, dayfirst)
            if entry is not None:
                expenses.append(entry)
            record = {}
            continue
        code, value = line[0], line[1:].strip()
        # Split transactions repeat S/E/$ -- keep the first, note the rest.
        record.setdefault(code, value)

    entry = _build(record, default_currency, dayfirst)
    if entry is not None:
        expenses.append(entry)

    if not expenses:
        raise LoaderError(f"{path}: found no QIF transactions (records end with a '^' line)")
    return expenses


def _build(record: "dict[str, str]", default_currency: str,
           dayfirst: Optional[bool]) -> Optional[Expense]:
    raw_amount = record.get("T") or record.get("U") or record.get("$")
    if raw_amount is None:
        return None
    try:
        amount = parse_amount(raw_amount)
    except ValueError:
        return None

    category = (record.get("L") or record.get("S") or "").strip()
    if category.startswith("[") and category.endswith("]"):
        category = f"Transfer: {category[1:-1]}"
    if ":" in category:  # Quicken's Category:Subcategory
        category, _, subcategory = category.partition(":")
    else:
        subcategory = ""

    payee = (record.get("P") or "").strip()
    memo = (record.get("M") or record.get("E") or "").strip()
    label = subcategory.strip() or payee or memo or category or "Transaction"

    return Expense(
        category=(category.strip() or ("Income" if amount > 0 else "Uncategorized")),
        label=label,
        amount=abs(amount),
        currency=default_currency,
        date=parse_date(record.get("D"), dayfirst=dayfirst),
        kind=INCOME if amount > 0 else EXPENSE,
        note=memo if memo != label else "",
    )


register(Format("qif", "QIF (Quicken Interchange Format) exports",
                ("qif",), load_qif,
                lambda head: head[:200].upper().startswith(b"!TYPE:") or b"\n!Type:" in head))
