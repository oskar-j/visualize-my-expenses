"""ISO 20022 camt.052/053/054 -- the European bank-statement XML standard."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from ..models import EXPENSE, INCOME, Expense
from ..tools import parse_amount, parse_date
from .base import Format, LoaderError, register

__all__ = ["load_camt"]


def _tag(element: ET.Element) -> str:
    """Local tag name, namespace stripped."""
    return element.tag.rsplit("}", 1)[-1]


def _find(element: ET.Element, *path: str) -> Optional[ET.Element]:
    current: Optional[ET.Element] = element
    for step in path:
        if current is None:
            return None
        current = next((child for child in current if _tag(child) == step), None)
    return current


def _text(element: Optional[ET.Element]) -> str:
    return (element.text or "").strip() if element is not None else ""


def _first_text(element: ET.Element, *names: str) -> str:
    """Depth-first search for the first non-empty text under any of ``names``."""
    for child in element.iter():
        if _tag(child) in names and (child.text or "").strip():
            return child.text.strip()
    return ""


def load_camt(path: str, default_currency: str = "USD", **_: object) -> List[Expense]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise LoaderError(f"{path}: invalid XML: {exc}") from exc
    except OSError as exc:
        raise LoaderError(f"cannot open {path}: {exc}") from exc

    root = tree.getroot()
    entries = [node for node in root.iter() if _tag(node) == "Ntry"]
    if not entries:
        raise LoaderError(
            f"{path}: no <Ntry> elements -- expected an ISO 20022 camt.052/053/054 statement"
        )

    expenses: List[Expense] = []
    for entry in entries:
        amount_node = next((child for child in entry if _tag(child) == "Amt"), None)
        if amount_node is None:
            continue
        try:
            amount = parse_amount(_text(amount_node))
        except ValueError:
            continue
        currency = amount_node.get("Ccy") or default_currency

        indicator = _text(_find(entry, "CdtDbtInd")).upper()
        kind = INCOME if indicator.startswith("CRDT") else EXPENSE

        booked = _text(_find(entry, "BookgDt", "Dt")) or _text(_find(entry, "BookgDt", "DtTm")) \
            or _text(_find(entry, "ValDt", "Dt"))

        party = "Cdtr" if kind == EXPENSE else "Dbtr"
        details = _find(entry, "NtryDtls", "TxDtls")
        label = ""
        if details is not None:
            related = _find(details, "RltdPties", party)
            label = _first_text(related, "Nm") if related is not None else ""
            if not label:
                label = _first_text(details, "Ustrd", "AddtlTxInf")
        label = label or _text(_find(entry, "AddtlNtryInf")) or "Transaction"

        code = _find(entry, "BkTxCd")
        category = ""
        if code is not None:
            category = _text(_find(code, "Prtry", "Cd")) or _text(_find(code, "Domn", "Cd"))
        category = category or ("Income" if kind == INCOME else "Uncategorized")

        expenses.append(Expense(
            category=category.title() if category.isupper() else category,
            label=label,
            amount=abs(amount),
            currency=currency,
            date=parse_date(booked),
            kind=kind,
        ))

    if not expenses:
        raise LoaderError(f"{path}: found no usable entries")
    return expenses


register(Format("camt", "ISO 20022 camt.052/053/054 bank statements (SEPA XML)",
                ("camt", "xml"), load_camt,
                lambda head: b"camt.05" in head or b"BkToCstmrStmt" in head))
