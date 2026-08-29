"""Shared helpers: money, dates, currencies and duck-typed row coercion.

Everything here is deliberately dependency-free so the loaders in :mod:`vme.io`
can stay thin.
"""

from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal, DecimalException, InvalidOperation
from typing import Any, Iterable, Mapping, Optional, Sequence

from .currencies import (
    compact_money,
    format_money,
    normalise_code,
    sniff_currency,
)
from .models import AUTO, EXPENSE, INCOME, UNCATEGORIZED, Expense

__all__ = [
    "coerce_row",
    "coerce_rows",
    "compact_money",
    "format_money",
    "month_bounds",
    "normalise_code",
    "parse_amount",
    "parse_date",
    "parse_kind",
    "parse_period",
    "period_label",
    "pick",
    "shorten",
    "sniff_currency",
]

# --------------------------------------------------------------------------- #
# Field aliases -- the vocabulary we accept from CSV headers and JSON keys.
# --------------------------------------------------------------------------- #

FIELD_ALIASES = {
    "category": ("category", "categories", "cat", "group", "bucket", "class",
                 "classification", "parent", "kategoria", "type_of_expense"),
    "label": ("label", "name", "description", "desc", "details", "detail", "payee",
              "merchant", "vendor", "title", "memo", "item", "subcategory",
              "sub_category", "subcat", "opis", "narrative", "counterparty"),
    "amount": ("amount", "value", "sum", "total", "price", "cost", "kwota",
               "debit_amount", "transaction_amount", "amt"),
    "currency": ("currency", "ccy", "cur", "curr", "currency_code", "waluta"),
    "date": ("date", "day", "posted", "posted_date", "post_date", "booking_date",
             "transaction_date", "trans_date", "timestamp", "datetime", "data"),
    "kind": ("kind", "direction", "flow", "type", "trans_type", "transaction_type",
             "dc", "debit_credit", "cd_indicator"),
    "note": ("note", "notes", "comment", "comments", "remark", "memo2", "tags"),
}

INCOME_WORDS = {
    "income", "in", "inflow", "credit", "cr", "crdt", "deposit", "salary",
    "revenue", "earning", "earnings", "wage", "wages", "przychod", "wplata",
    "+", "dep", "int", "div", "directdep", "xfer_in",
}
EXPENSE_WORDS = {
    "expense", "expenses", "out", "outflow", "debit", "db", "dr", "dbit",
    "spending", "spend", "cost", "payment", "withdrawal", "purchase",
    "wydatek", "wyplata", "-", "pos", "check", "atm", "fee", "srvchg", "xfer_out",
}

_AMOUNT_CLEAN_RE = re.compile(r"[^\d,.\-+()]")
_ISO_DATE_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def pick(mapping: Mapping[str, Any], field: str, default: Any = None) -> Any:
    """Fetch ``field`` from ``mapping`` using the alias table, case-insensitively."""
    normalised = {_norm_key(k): v for k, v in mapping.items()}
    for alias in FIELD_ALIASES.get(field, (field,)):
        if alias in normalised:
            value = normalised[alias]
            if value not in (None, ""):
                return value
    return default


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #


def parse_amount(value: Any) -> Decimal:
    """Parse money written any of the ways humans and banks write it.

    Handles ``1,234.56``, ``1 234,56``, ``1.234,56``, ``$1,234.56``, ``-12``,
    ``(12.00)`` (accounting negative) and ``12.00 PLN``.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if value is None:
        raise ValueError("missing amount")

    text = str(value).strip()
    if not text:
        raise ValueError("empty amount")

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]

    text = _AMOUNT_CLEAN_RE.sub("", text).strip()
    if text.endswith("-"):  # trailing-minus notation, e.g. "120.00-"
        negative = True
        text = text[:-1]
    text = text.replace("+", "")
    if text.startswith("-"):
        negative = not negative
        text = text[1:]
    text = text.replace("-", "")

    if not text:
        raise ValueError(f"cannot read amount from {value!r}")

    last_comma, last_dot = text.rfind(","), text.rfind(".")
    spaces = " \u202f\xa0"
    if last_comma > last_dot:
        tail = text[last_comma + 1:]
        # A lone comma is ambiguous: "2,500" is two and a half thousand, "1,50"
        # is one and a half. Three trailing digits with no other separator in
        # sight means it grouped thousands.
        grouped = (last_dot < 0 and not any(ch in text for ch in spaces)
                   and len(tail) == 3 and tail.isdigit())
        if grouped or text.count(",") > 1:
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    for space in spaces:
        text = text.replace(space, "")

    try:
        amount = Decimal(text)
    except (InvalidOperation, DecimalException) as exc:
        raise ValueError(f"cannot read amount from {value!r}") from exc
    return -amount if negative else amount


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y",
    "%m-%d-%Y", "%Y%m%d", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y",
    "%d/%m/%y", "%m/%d/%y", "%y-%m-%d", "%d.%m.%y",
)


def parse_date(value: Any, dayfirst: Optional[bool] = None) -> Optional[_dt.date]:
    """Best-effort date parsing. Returns ``None`` for blank input."""
    if value is None or value == "":
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(int(value))
    else:
        text = str(value).strip()
    if not text:
        return None

    # OFX stamps: 20240115120000[-5:EST]
    ofx = re.match(r"^(\d{8})(\d{6})?", text)
    iso = _ISO_DATE_RE.match(text)
    if iso:
        try:
            return _dt.date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            pass
    elif ofx and len(ofx.group(1)) == 8:
        try:
            return _dt.datetime.strptime(ofx.group(1), "%Y%m%d").date()
        except ValueError:
            pass

    # QIF style: 1/15'24 or 1/15/2024
    quicken = re.match(r"^\s*(\d{1,2})/\s*(\d{1,2})'(\d{2,4})\s*$", text)
    if quicken:
        month, day, year = (int(g) for g in quicken.groups())
        year += 2000 if year < 100 else 0
        try:
            return _dt.date(year, month, day)
        except ValueError:
            return None

    candidates = list(_DATE_FORMATS)
    if dayfirst is True:
        candidates.sort(key=lambda f: 0 if f.startswith("%d") else 1)
    elif dayfirst is False:
        candidates.sort(key=lambda f: 0 if f.startswith("%m") else 1)

    head = text.split("T")[0].split(" ")[0] if "T" in text else text
    for fmt in candidates:
        for attempt in (text, head):
            try:
                return _dt.datetime.strptime(attempt, fmt).date()
            except ValueError:
                continue
    return None


def month_bounds(year: int, month: int) -> tuple[_dt.date, _dt.date]:
    start = _dt.date(year, month, 1)
    end = _dt.date(year + (month == 12), (month % 12) + 1, 1) - _dt.timedelta(days=1)
    return start, end


def parse_period(text: str) -> tuple[_dt.date, _dt.date]:
    """``'2026-08'`` -> that month; ``'2026'`` -> that year; ``'a..b'`` -> a range."""
    raw = str(text).strip()
    if ".." in raw:
        left, right = raw.split("..", 1)
        start = parse_date(left.strip())
        end = parse_date(right.strip())
        if start is None or end is None:
            raise ValueError(f"cannot read date range {text!r}")
        return start, end
    if re.fullmatch(r"\d{4}", raw):
        year = int(raw)
        return _dt.date(year, 1, 1), _dt.date(year, 12, 31)
    match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})", raw)
    if match:
        return month_bounds(int(match.group(1)), int(match.group(2)))
    match = re.fullmatch(r"(\d{1,2})[-/.](\d{4})", raw)
    if match:
        return month_bounds(int(match.group(2)), int(match.group(1)))
    single = parse_date(raw)
    if single is not None:
        return single, single
    raise ValueError(
        f"cannot read period {text!r} -- use YYYY-MM, YYYY, or START..END"
    )


def period_label(start: _dt.date, end: _dt.date) -> str:
    if start.day == 1 and (end + _dt.timedelta(days=1)).day == 1:
        if start.year == end.year and start.month == end.month:
            return start.strftime("%B %Y")
        if start.month == 1 and end.month == 12 and start.year == end.year:
            return str(start.year)
    return f"{start.isoformat()} – {end.isoformat()}"


# --------------------------------------------------------------------------- #
# Row coercion
# --------------------------------------------------------------------------- #


def parse_kind(value: Any, default: Optional[str] = None) -> Optional[str]:
    """Map a free-text direction (``'DEBIT'``, ``'in'``, ``'CRDT'``) to a kind."""
    if value is None:
        return default
    token = re.sub(r"[^a-z+-]+", "", str(value).strip().lower())
    if not token:
        return default
    if token in INCOME_WORDS:
        return INCOME
    if token in EXPENSE_WORDS:
        return EXPENSE
    if token.startswith("cred") or token.startswith("inc"):
        return INCOME
    if token.startswith("deb") or token.startswith("exp"):
        return EXPENSE
    return default


def shorten(text: str, width: int = 28) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _mapping_from(row: Any) -> Optional[Mapping[str, Any]]:
    if isinstance(row, Mapping):
        return row
    fields = getattr(row, "_fields", None)  # namedtuple
    if fields:
        return {name: getattr(row, name) for name in fields}
    dataclass_fields = getattr(row, "__dataclass_fields__", None)
    if dataclass_fields:
        return {name: getattr(row, name) for name in dataclass_fields}
    if hasattr(row, "__dict__") and vars(row):
        return dict(vars(row))
    return None


def coerce_row(row: Any, default_currency: str = "USD",
               dayfirst: Optional[bool] = None) -> Expense:
    """Turn a dict / namedtuple / dataclass / sequence into an :class:`Expense`.

    The sign of the amount is preserved here (negative stays negative); direction
    is settled later by :func:`vme.data_store.apply_sign_convention`, which needs
    to see the whole file to choose a convention.
    """
    if isinstance(row, Expense):
        return row

    mapping = _mapping_from(row)
    if mapping is None:
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
            keys = ("category", "label", "amount", "currency", "date", "kind")
            mapping = dict(zip(keys, row))
        else:
            raise TypeError(
                f"cannot read a row from {type(row).__name__}; pass a dict, a namedtuple, "
                "an Expense, or a sequence of (category, label, amount, currency)"
            )

    raw_amount = pick(mapping, "amount")
    if raw_amount is None:
        raise ValueError(f"row is missing an amount: {mapping!r}")
    amount = parse_amount(raw_amount)

    currency = normalise_code(
        pick(mapping, "currency") or sniff_currency(raw_amount, default_currency),
        default_currency,
    )
    kind = parse_kind(pick(mapping, "kind"))
    if kind is None and _looks_like_income(mapping):
        kind = INCOME

    label = pick(mapping, "label", "") or ""
    category = pick(mapping, "category") or (label if label else UNCATEGORIZED)

    return Expense(
        category=str(category),
        label=str(label),
        amount=amount,  # sign kept for now
        currency=currency,
        date=parse_date(pick(mapping, "date"), dayfirst=dayfirst),
        kind=kind or AUTO,
        note=str(pick(mapping, "note", "") or ""),
    )


def _looks_like_income(mapping: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(pick(mapping, key, "") or "") for key in ("category", "label")
    ).lower()
    return any(word in text for word in ("income", "salary", "wage", "payroll", "bonus"))


def coerce_rows(rows: Optional[Iterable[Any]], default_currency: str = "USD",
                dayfirst: Optional[bool] = None) -> list[Expense]:
    if rows is None:
        return []
    return [coerce_row(row, default_currency, dayfirst) for row in rows]
