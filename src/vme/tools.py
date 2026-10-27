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
    "infer_dayfirst",
    "looks_like_income",
    "month_bounds",
    "normalise_code",
    "parse_amount",
    "parse_date",
    "parse_kind",
    "parse_period",
    "period_label",
    "pick",
    "raw_date",
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


#: Words that give the direction even inside a longer phrase ("Incoming transfer").
#: "credit" and "debit" are not among them: in "Credit Card" they say how it was paid.
_DIRECTION_WORDS = {
    "incoming": INCOME, "inflow": INCOME, "inbound": INCOME,
    "outgoing": EXPENSE, "outflow": EXPENSE, "outbound": EXPENSE,
}


def parse_kind(value: Any, default: Optional[str] = None) -> Optional[str]:
    """Map a free-text direction (``'DEBIT'``, ``'in'``, ``'CRDT'``) to a kind.

    One word is read generously (``'Credited'`` is income). A longer phrase
    usually names the transaction rather than its direction, so it counts only
    as a known phrase (``'Direct Dep'``) or through a word that cannot mean
    anything else (``'Incoming transfer'``). ``'Credit Card'`` gives ``default``
    and the amount's sign decides.
    """
    if value is None:
        return default
    text = str(value).strip().lower()
    token = re.sub(r"[^a-z+-]+", "", text)
    if not token:
        return default
    if token in INCOME_WORDS:
        return INCOME
    if token in EXPENSE_WORDS:
        return EXPENSE
    words = re.findall(r"[a-z]+", text)
    if len(words) > 1:
        found = {_DIRECTION_WORDS[word] for word in words if word in _DIRECTION_WORDS}
        return found.pop() if len(found) == 1 else default
    if token.startswith(("cred", "inc")):
        return INCOME
    if token.startswith(("deb", "exp")):
        return EXPENSE
    return default


#: Words that name income in a category or label ("Salary", "Payroll")...
_INCOME_HINT = re.compile(
    r"\b(?:income|incomes|salary|salaries|wage|wages|payroll|bonus|bonuses)\b")
#: ...unless the same text names a cost ("Income tax", "Income protection insurance").
_COST_HINT = re.compile(r"\b(?:tax|taxes|insurance|fee|fees)\b")


def looks_like_income(category: Any = "", label: Any = "") -> bool:
    """Whether a row's own words say it is income: ``Income``, ``Salary``, ``Payroll``.

    This is a last resort, for a plain list of positive amounts where nothing
    else marks the income; :func:`vme.data_store.apply_sign_convention` never
    lets it overrule a sign. Whole words only, so "Water & sewage" is not a wage.
    The category speaks first and the label only when the category says nothing
    either way: category "Income" with label "Tax refund" is income, category
    "Taxes" with label "Income tax" is not.
    """
    for text in (category, label):
        words = str(text or "").lower()
        if _COST_HINT.search(words):
            return False
        if _INCOME_HINT.search(words):
            return True
    return False


#: A numeric date whose first two fields could be either day or month:
#: 03/04/2026, 03-04-2026, 03/04/26. A two-digit year after dashes is not
#: one of them -- "26-04-03" is read year-first.
_DAY_MONTH_RE = re.compile(r"^\s*(\d{1,2})([/-])(\d{1,2})\2(\d{4}|\d{2})(?!\d)")


def infer_dayfirst(values: Iterable[Any]) -> Optional[bool]:
    """Work out the day/month order from a whole column of dates at once.

    One date alone cannot tell 03/04 from 04/03, and deciding row by row mixes
    both orders in one file: 01/02 read day-first next to 01/13 read
    month-first. One 13/01 makes the column day-first (``True``), one 01/13
    month-first (``False``). ``None`` when every date could be either.

    :raises ValueError: when the column holds both, naming one of each.
    """
    day_first: Optional[str] = None
    month_first: Optional[str] = None
    for value in values:
        if not isinstance(value, str):
            continue
        match = _DAY_MONTH_RE.match(value)
        if match is None or (match.group(2) == "-" and len(match.group(4)) == 2):
            continue
        first, second = int(match.group(1)), int(match.group(3))
        if first > 12 >= second:
            day_first = day_first or value.strip()
        elif second > 12 >= first:
            month_first = month_first or value.strip()
        if day_first and month_first:
            raise ValueError(
                f"dates are written both day-first ({day_first!r}) and "
                f"month-first ({month_first!r})"
            )
    if day_first:
        return True
    if month_first:
        return False
    return None


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


def _as_mapping(row: Any) -> Mapping[str, Any]:
    mapping = _mapping_from(row)
    if mapping is not None:
        return mapping
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
        keys = ("category", "label", "amount", "currency", "date", "kind")
        return dict(zip(keys, row))
    raise TypeError(
        f"cannot read a row from {type(row).__name__}; pass a dict, a namedtuple, "
        "an Expense, or a sequence of (category, label, amount, currency)"
    )


def raw_date(row: Any) -> Any:
    """The date field of a row not yet coerced, as written; ``None`` if there is none."""
    if isinstance(row, Expense):
        return None
    try:
        return pick(_as_mapping(row), "date")
    except TypeError:
        return None


def coerce_row(row: Any, default_currency: str = "USD",
               dayfirst: Optional[bool] = None) -> Expense:
    """Turn a dict / namedtuple / dataclass / sequence into an :class:`Expense`.

    The sign of the amount is preserved here (negative stays negative), and a
    row whose source did not state a direction stays ``AUTO``. Direction is
    settled later by :func:`vme.data_store.apply_sign_convention`, which needs to
    see the whole file to choose a convention.

    ``dayfirst`` should be decided for the whole file (:func:`infer_dayfirst`);
    left as ``None`` here, an ambiguous date is read day-first.
    """
    if isinstance(row, Expense):
        return row

    mapping = _as_mapping(row)

    raw_amount = pick(mapping, "amount")
    if raw_amount is None:
        raise ValueError(f"row is missing an amount: {mapping!r}")
    amount = parse_amount(raw_amount)

    currency = normalise_code(
        pick(mapping, "currency") or sniff_currency(raw_amount, default_currency),
        default_currency,
    )
    kind = parse_kind(pick(mapping, "kind"))

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


def coerce_rows(rows: Optional[Iterable[Any]], default_currency: str = "USD",
                dayfirst: Optional[bool] = None) -> list[Expense]:
    """Coerce every row, reading ambiguous dates the same way throughout.

    Without ``dayfirst`` the order is worked out once from all the rows
    (:func:`infer_dayfirst`).
    """
    if rows is None:
        return []
    rows = list(rows)
    if dayfirst is None:
        try:
            dayfirst = infer_dayfirst(raw_date(row) for row in rows)
        except ValueError as exc:
            raise ValueError(
                f"{exc}. Write the dates as YYYY-MM-DD or datetime.date, "
                "or pass dayfirst=True or dayfirst=False."
            ) from exc
    return [coerce_row(row, default_currency, dayfirst) for row in rows]
