"""QIF -- Quicken Interchange Format, still the lingua franca of older exports."""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..models import EXPENSE, INCOME, Expense
from ..tools import parse_amount, parse_date
from .base import (
    Format,
    LoaderError,
    read_text,
    register,
    resolve_dayfirst,
    warn_unread_dates,
)

__all__ = ["load_qif"]


def load_qif(path: str, encoding: Optional[str] = None, default_currency: str = "USD",
             dayfirst: Optional[bool] = None, **_: object) -> List[Expense]:
    text = read_text(path, encoding)
    records: List[Tuple[int, dict[str, str]]] = []   # (line of its date, fields)
    record: dict[str, str] = {}
    date_line = 0

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r\n")
        if not line:
            continue
        if line.startswith("!"):  # !Type:Bank, !Account, ...
            continue
        if line.startswith("^"):
            records.append((date_line, record))
            record, date_line = {}, 0
            continue
        code, value = line[0], line[1:].strip()
        if code == "D" and code not in record:
            date_line = number
        # Split transactions repeat S/E/$ -- keep the first, note the rest.
        record.setdefault(code, value)
    records.append((date_line, record))

    # Quicken's own 8/15'26 is always month-first; only 08/15/2026 needs this.
    dayfirst = resolve_dayfirst(path, dayfirst, (r.get("D") for _, r in records))
    expenses: List[Expense] = []
    dates = []
    for date_line, record in records:
        entry = _build(record, default_currency, dayfirst)
        if entry is not None:
            expenses.append(entry)
            dates.append((f"{path}:{date_line}", record.get("D"), entry.date))

    if not expenses:
        raise LoaderError(f"{path}: found no QIF transactions (records end with a '^' line)")
    warn_unread_dates(dates)
    return expenses


def _build(record: dict[str, str], default_currency: str,
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
