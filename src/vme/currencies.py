"""Currency metadata and conversion rates.

The library never fetches rates from the network -- a budget picture has to be
reproducible, and a rate that silently changes between two runs makes two
different pictures out of the same data. Rates come from you: on the command
line (``--rate EUR=4.30``), from a small JSON/CSV file (``--rates rates.json``),
or from a mapping passed to :class:`~vme.visualizer.Visualizer`.
"""

from __future__ import annotations

import json
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Mapping, NamedTuple, Optional

__all__ = ["Currency", "CURRENCIES", "GROUP_SPACE", "get_currency", "format_money",
           "compact_money", "normalise_code", "load_rates", "sniff_currency",
           "SYMBOL_TO_CURRENCY"]

#: Narrow no-break space -- the typographic separator for grouped digits, and
#: what sits between a number and a trailing currency symbol.
GROUP_SPACE = "\u202f"


class Currency(NamedTuple):
    """How one currency is written."""

    code: str
    symbol: str
    name: str
    decimals: int = 2
    #: ``True`` when the symbol goes in front of the number ("$12"), else after ("12 zł").
    prefix: bool = False
    #: Thousands separator used in that currency's home locale.
    group: str = " "  # narrow no-break space
    decimal_point: str = "."


def _c(code: str, symbol: str, name: str, **kwargs: Any) -> Currency:
    return Currency(code, symbol, name, **kwargs)


#: Codes we know how to write. Anything else still works -- the code itself is
#: used as the symbol and the default 2-decimal, suffix layout applies.
CURRENCIES: Dict[str, Currency] = {c.code: c for c in (
    # Europe
    _c("EUR", "€", "Euro", prefix=True, group=","),
    _c("PLN", "zł", "Polish złoty", group=" ", decimal_point=","),
    _c("UAH", "₴", "Ukrainian hryvnia", decimal_point=","),
    _c("GBP", "£", "Pound sterling", prefix=True, group=","),
    _c("CHF", "CHF", "Swiss franc", group="'"),
    _c("CZK", "Kč", "Czech koruna", decimal_point=","),
    _c("SEK", "kr", "Swedish krona", decimal_point=","),
    _c("NOK", "kr", "Norwegian krone", decimal_point=","),
    _c("DKK", "kr", "Danish krone", decimal_point=","),
    _c("HUF", "Ft", "Hungarian forint", decimals=0, decimal_point=","),
    _c("RON", "lei", "Romanian leu", decimal_point=","),
    _c("BGN", "лв", "Bulgarian lev", decimal_point=","),
    _c("RSD", "дин", "Serbian dinar", decimal_point=","),
    _c("ISK", "kr", "Icelandic króna", decimals=0, decimal_point=","),
    _c("TRY", "₺", "Turkish lira", prefix=True, decimal_point=","),
    _c("MDL", "L", "Moldovan leu", decimal_point=","),
    _c("GEL", "₾", "Georgian lari"),
    # Americas
    _c("USD", "$", "US dollar", prefix=True, group=","),
    _c("CAD", "CA$", "Canadian dollar", prefix=True, group=","),
    _c("MXN", "MX$", "Mexican peso", prefix=True, group=","),
    _c("BRL", "R$", "Brazilian real", prefix=True, decimal_point=","),
    _c("ARS", "AR$", "Argentine peso", prefix=True, decimal_point=","),
    _c("CLP", "CLP$", "Chilean peso", decimals=0, prefix=True),
    _c("COP", "COL$", "Colombian peso", decimals=0, prefix=True),
    # Asia-Pacific
    _c("JPY", "¥", "Japanese yen", decimals=0, prefix=True, group=","),
    _c("CNY", "¥", "Chinese yuan", prefix=True, group=","),
    _c("KRW", "₩", "South Korean won", decimals=0, prefix=True, group=","),
    _c("INR", "₹", "Indian rupee", prefix=True, group=","),
    _c("IDR", "Rp", "Indonesian rupiah", decimals=0, prefix=True, decimal_point=","),
    _c("SGD", "S$", "Singapore dollar", prefix=True, group=","),
    _c("HKD", "HK$", "Hong Kong dollar", prefix=True, group=","),
    _c("AUD", "A$", "Australian dollar", prefix=True, group=","),
    _c("NZD", "NZ$", "New Zealand dollar", prefix=True, group=","),
    _c("THB", "฿", "Thai baht", prefix=True, group=","),
    _c("PHP", "₱", "Philippine peso", prefix=True, group=","),
    _c("VND", "₫", "Vietnamese đồng", decimals=0, decimal_point=","),
    _c("MYR", "RM", "Malaysian ringgit", prefix=True, group=","),
    # Middle East & Africa
    _c("ILS", "₪", "Israeli new shekel", prefix=True, group=","),
    _c("AED", "د.إ", "UAE dirham", group=","),
    _c("SAR", "﷼", "Saudi riyal", group=","),
    _c("ZAR", "R", "South African rand", prefix=True, decimal_point=","),
    _c("EGP", "E£", "Egyptian pound", prefix=True, group=","),
    _c("NGN", "₦", "Nigerian naira", prefix=True, group=","),
    _c("KES", "KSh", "Kenyan shilling", prefix=True, group=","),
    _c("MAD", "DH", "Moroccan dirham", decimal_point=","),
    # Other
    _c("RUB", "₽", "Russian rouble", decimal_point=","),
    _c("KZT", "₸", "Kazakhstani tenge", decimal_point=","),
    _c("BTC", "₿", "Bitcoin", decimals=8, prefix=True),
)}

#: Reverse lookup for amounts written with a symbol instead of a code.
#: Ambiguous symbols (``$``, ``¥``, ``kr``) resolve to the most common holder.
SYMBOL_TO_CURRENCY: Dict[str, str] = {
    "€": "EUR", "zł": "PLN", "₴": "UAH", "£": "GBP", "Kč": "CZK", "Ft": "HUF",
    "₺": "TRY", "₾": "GEL", "лв": "BGN", "$": "USD", "R$": "BRL", "CA$": "CAD",
    "MX$": "MXN", "¥": "JPY", "₩": "KRW", "₹": "INR", "Rp": "IDR", "S$": "SGD",
    "HK$": "HKD", "A$": "AUD", "NZ$": "NZD", "฿": "THB", "₱": "PHP", "₫": "VND",
    "RM": "MYR", "₪": "ILS", "₦": "NGN", "₽": "RUB", "₸": "KZT", "₿": "BTC",
    "kr": "SEK", "лей": "MDL",
}

#: Longest symbols first, so "CA$" is tried before "$".
_SYMBOLS_BY_LENGTH = sorted(SYMBOL_TO_CURRENCY, key=len, reverse=True)

DEFAULT = Currency("USD", "$", "US dollar", prefix=True, group=",")


def normalise_code(code: Any, default: str = "USD") -> str:
    text = str(code or "").strip().upper()
    if not text:
        return default.upper()
    return SYMBOL_TO_CURRENCY.get(str(code).strip(), text)


def get_currency(code: Any) -> Currency:
    """Metadata for ``code``; unknown codes get a sane generic layout."""
    key = normalise_code(code)
    known = CURRENCIES.get(key)
    if known is not None:
        return known
    return Currency(key, key, key, decimals=2, prefix=False)


def sniff_currency(value: Any, default: Optional[str] = None) -> Optional[str]:
    """Pull a currency out of free text such as ``"12.00 PLN"``, ``"$12"``, ``"12 zł"``."""
    if value is None:
        return default
    text = str(value)
    for token in text.replace(",", " ").split():
        upper = token.strip(".,;:()").upper()
        if len(upper) == 3 and upper.isalpha() and upper in CURRENCIES:
            return upper
    for symbol in _SYMBOLS_BY_LENGTH:
        if symbol in text:
            return SYMBOL_TO_CURRENCY[symbol]
    return default


def format_money(amount: Any, currency: Any = "USD",
                 decimals: Optional[int] = None) -> str:
    """``1234.5, "PLN"`` -> ``"1 234,50 zł"``; ``1234.5, "USD"`` -> ``"$1,234.50"``."""
    spec = get_currency(currency)
    places = spec.decimals if decimals is None else max(int(decimals), 0)
    # Money rounds half away from zero; float formatting rounds half to even,
    # which would show 1234.5 JPY as 1,234.
    try:
        value = Decimal(str(amount)).quantize(Decimal(1).scaleb(-places),
                                              rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, ArithmeticError):
        value = Decimal(str(float(amount)))
    body = f"{value:,.{places}f}"
    # Re-punctuate from the neutral "1,234.50" into the currency's own style.
    body = body.replace(",", "\x00").replace(".", spec.decimal_point) \
               .replace("\x00", spec.group)
    if spec.prefix:
        return f"{spec.symbol}{body}"
    return f"{body} {spec.symbol}" if spec.symbol else body


def compact_money(amount: Any, currency: Any = "USD") -> str:
    """Short form for tight in-plot labels: ``12.3k zł``, ``$1.2M``."""
    spec = get_currency(currency)
    value = float(amount)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if abs(value) >= limit:
            scaled = f"{value / limit:.1f}".rstrip("0").rstrip(".") + suffix
            return f"{spec.symbol}{scaled}" if spec.prefix else f"{scaled} {spec.symbol}"
    return format_money(value, spec.code, 0 if abs(value) >= 100 else spec.decimals)


# --------------------------------------------------------------------------- #
# Rates
# --------------------------------------------------------------------------- #


class RateError(ValueError):
    """A rates file could not be read."""


def load_rates(path: str, target: Optional[str] = None) -> Dict[str, Decimal]:
    """Read conversion rates from a JSON or CSV file.

    JSON, either flat or with a target declared::

        {"EUR": 4.30, "USD": 3.95}
        {"base": "PLN", "rates": {"EUR": 4.30, "USD": 3.95}}

    CSV, with a header::

        currency,rate
        EUR,4.30

    Each value answers: *one unit of this currency is worth how much of the
    report currency?*
    """
    suffix = os.path.splitext(str(path))[1].lower()
    try:
        with open(path, encoding="utf-8-sig") as handle:
            text = handle.read()
    except OSError as exc:
        raise RateError(f"cannot open rates file {path}: {exc}") from exc

    if suffix in (".csv", ".tsv", ".txt"):
        pairs = _rates_from_csv(text, path)
        base = None
    else:
        pairs, base = _rates_from_json(text, path)

    if target and base and base.upper() != target.upper():
        raise RateError(
            f"{path} holds rates against {base.upper()}, but the report is in "
            f"{target.upper()}. Re-state the rates, or run with -c {base.upper()}."
        )

    rates: Dict[str, Decimal] = {}
    for code, value in pairs.items():
        try:
            rate = Decimal(str(value))
        except Exception as exc:
            raise RateError(f"{path}: rate for {code} is not a number: {value!r}") from exc
        if rate <= 0:
            raise RateError(f"{path}: rate for {code} must be positive, got {rate}")
        rates[normalise_code(code)] = rate
    if not rates:
        raise RateError(f"{path} contains no rates")
    return rates


def _rates_from_json(text: str, path: str) -> tuple:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RateError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc
    if not isinstance(document, Mapping):
        raise RateError(f"{path}: expected a JSON object of CODE -> rate")
    base = document.get("base") or document.get("target") or document.get("currency")
    inner = document.get("rates")
    if isinstance(inner, Mapping):
        return dict(inner), base
    return {k: v for k, v in document.items()
            if k not in ("base", "target", "currency", "date", "source")}, base


def _rates_from_csv(text: str, path: str) -> Dict[str, Any]:
    import csv
    import io

    reader = csv.reader(io.StringIO(text), delimiter=";" if ";" in text.split("\n")[0]
                        else ",")
    rows = [row for row in reader if any((cell or "").strip() for cell in row)]
    if len(rows) < 2:
        raise RateError(f"{path}: expected a header plus at least one rate row")
    header = [cell.strip().lower() for cell in rows[0]]
    try:
        code_at = next(i for i, name in enumerate(header)
                       if name in ("currency", "code", "ccy", "from"))
        rate_at = next(i for i, name in enumerate(header)
                       if name in ("rate", "factor", "value", "multiplier"))
    except StopIteration:
        raise RateError(
            f"{path}: need a 'currency' column and a 'rate' column; got {', '.join(header)}"
        ) from None
    return {row[code_at]: row[rate_at] for row in rows[1:]
            if len(row) > max(code_at, rate_at) and row[code_at].strip()}


def describe(codes: Optional[Iterable[str]] = None) -> list:
    """``[(code, symbol, name), ...]`` for the ``vme currencies`` command."""
    keys = [normalise_code(c) for c in codes] if codes else sorted(CURRENCIES)
    return [(c.code, c.symbol, c.name) for c in (get_currency(k) for k in keys)]
