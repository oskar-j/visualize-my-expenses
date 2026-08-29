"""Delimited text (CSV/TSV) -- the format most banks and budget apps export."""

from __future__ import annotations

import csv
import io as _io
from typing import List, Optional

from ..models import Expense
from ..tools import coerce_row
from .base import Format, LoaderError, read_text, register

__all__ = ["load_csv"]


def _sniff_dialect(sample: str) -> "type[csv.Dialect]":
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def load_csv(path: str, encoding: Optional[str] = None, delimiter: Optional[str] = None,
             default_currency: str = "USD", dayfirst: Optional[bool] = None,
             **_: object) -> List[Expense]:
    text = read_text(path, encoding)
    if not text.strip():
        raise LoaderError(f"{path} is empty")

    sample = "\n".join(text.splitlines()[:20])
    dialect = _sniff_dialect(sample)
    reader = csv.reader(_io.StringIO(text), dialect=dialect,
                        **({"delimiter": delimiter} if delimiter else {}))

    rows = [row for row in reader if any((cell or "").strip() for cell in row)]
    if not rows:
        raise LoaderError(f"{path} has no data rows")

    header = [cell.strip() for cell in rows[0]]
    if not _looks_like_header(header):
        raise LoaderError(
            f"{path} has no header row. The first line must name the columns, e.g.\n"
            "    date,category,label,amount,currency"
        )

    expenses: List[Expense] = []
    for number, row in enumerate(rows[1:], start=2):
        record = {key: value for key, value in zip(header, row) if key}
        if not any((v or "").strip() for v in record.values()):
            continue
        try:
            expenses.append(coerce_row(record, default_currency, dayfirst))
        except (ValueError, TypeError) as exc:
            raise LoaderError(f"{path}:{number}: {exc}") from exc
    if not expenses:
        raise LoaderError(f"{path} has a header but no rows")
    return expenses


def _looks_like_header(header: "List[str]") -> bool:
    """A header row is one where no cell parses as a number."""
    from ..tools import parse_amount

    numeric = 0
    for cell in header:
        try:
            parse_amount(cell)
            numeric += 1
        except ValueError:
            pass
    return numeric == 0


def _sniff(head: bytes) -> bool:
    try:
        text = head.decode("utf-8", "ignore")
    except Exception:  # pragma: no cover - defensive
        return False
    first = text.splitlines()[0] if text.splitlines() else ""
    return any(sep in first for sep in (",", ";", "\t")) and not first.lstrip().startswith(("{", "[", "<"))


register(Format("csv", "Comma/semicolon/tab separated values with a header row",
                ("csv", "tsv", "txt"), load_csv, _sniff))
