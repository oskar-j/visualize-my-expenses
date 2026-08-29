"""JSON and JSON Lines."""

from __future__ import annotations

import json
from typing import Any, List, Optional

from ..models import Expense
from ..tools import coerce_row
from .base import Format, LoaderError, read_text, register

__all__ = ["load_json", "load_jsonl"]

#: Keys we look under when the document is an object rather than a list.
CONTAINER_KEYS = ("expenses", "rows", "transactions", "data", "items", "entries", "records")


def _extract(document: Any, path: str) -> List[Any]:
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        for key in CONTAINER_KEYS:
            if isinstance(document.get(key), list):
                return document[key]
        # A single row object is fine too.
        if any(k.lower() in ("amount", "value", "sum") for k in document):
            return [document]
    raise LoaderError(
        f"{path}: expected a JSON array of rows, or an object with one of "
        f"{', '.join(CONTAINER_KEYS)}"
    )


def load_json(path: str, encoding: Optional[str] = None, default_currency: str = "USD",
              dayfirst: Optional[bool] = None, **_: object) -> List[Expense]:
    text = read_text(path, encoding)
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LoaderError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc

    rows = _extract(document, path)
    expenses: List[Expense] = []
    for index, row in enumerate(rows):
        try:
            expenses.append(coerce_row(row, default_currency, dayfirst))
        except (ValueError, TypeError) as exc:
            raise LoaderError(f"{path}: row {index}: {exc}") from exc
    if not expenses:
        raise LoaderError(f"{path} contains no rows")
    return expenses


def load_jsonl(path: str, encoding: Optional[str] = None, default_currency: str = "USD",
               dayfirst: Optional[bool] = None, **_: object) -> List[Expense]:
    text = read_text(path, encoding)
    expenses: List[Expense] = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            expenses.append(coerce_row(json.loads(line), default_currency, dayfirst))
        except json.JSONDecodeError as exc:
            raise LoaderError(f"{path}:{number}: invalid JSON: {exc.msg}") from exc
        except (ValueError, TypeError) as exc:
            raise LoaderError(f"{path}:{number}: {exc}") from exc
    if not expenses:
        raise LoaderError(f"{path} contains no rows")
    return expenses


register(Format("json", "JSON array of rows, or {\"expenses\": [...]}",
                ("json",), load_json,
                lambda head: head.lstrip()[:1] in (b"[", b"{")))
register(Format("jsonl", "JSON Lines / newline-delimited JSON",
                ("jsonl", "ndjson"), load_jsonl))
