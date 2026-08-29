"""OFX / QFX -- Open Financial Exchange, what most US banks and Quicken export.

Both the SGML flavour (OFX 1.x, unclosed tags) and the XML flavour (OFX 2.x) are
handled by the same tolerant tag scanner, which is far less fragile here than a
real XML parser.
"""

from __future__ import annotations

import re
from typing import List, Optional

from ..models import EXPENSE, INCOME, Expense
from ..tools import parse_amount, parse_date, parse_kind
from .base import Format, LoaderError, read_text, register

__all__ = ["load_ofx"]

_TRANSACTION_RE = re.compile(r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>)",
                             re.IGNORECASE | re.DOTALL)
_FIELD_RE = re.compile(r"<([A-Z0-9.]+)>([^<\r\n]*)", re.IGNORECASE)

#: OFX transaction types that are money coming in.
_CREDIT_TYPES = {"CREDIT", "DEP", "DIRECTDEP", "INT", "DIV", "XFER"}


def _fields(block: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for name, value in _FIELD_RE.findall(block):
        value = value.strip()
        if value and name.upper() not in found:
            found[name.upper()] = value
    return found


def load_ofx(path: str, encoding: Optional[str] = None, default_currency: str = "USD",
             **_: object) -> List[Expense]:
    text = read_text(path, encoding)
    if "<STMTTRN>" not in text.upper():
        raise LoaderError(f"{path}: no <STMTTRN> transactions found -- is this really OFX/QFX?")

    header = _fields(text.split("<STMTTRN>", 1)[0])
    file_currency = header.get("CURDEF") or default_currency

    expenses: List[Expense] = []
    for block in _TRANSACTION_RE.findall(text):
        field = _fields(block)
        raw_amount = field.get("TRNAMT")
        if raw_amount is None:
            continue
        try:
            amount = parse_amount(raw_amount)
        except ValueError as exc:
            raise LoaderError(f"{path}: bad TRNAMT {raw_amount!r}: {exc}") from exc

        trn_type = (field.get("TRNTYPE") or "").upper()
        if trn_type in _CREDIT_TYPES and amount > 0:
            kind = INCOME
        elif trn_type and trn_type not in _CREDIT_TYPES:
            kind = EXPENSE if amount <= 0 or trn_type in ("DEBIT", "POS", "ATM", "CHECK", "FEE") \
                else (parse_kind(trn_type) or INCOME)
        else:
            kind = INCOME if amount > 0 else EXPENSE

        name = field.get("NAME") or field.get("PAYEE") or field.get("MEMO") or "Transaction"
        memo = field.get("MEMO", "")
        category = field.get("CATEGORY") or _category_from_type(trn_type, kind)

        expenses.append(Expense(
            category=category,
            label=name,
            amount=abs(amount),
            currency=(field.get("CURSYM") or file_currency),
            date=parse_date(field.get("DTPOSTED") or field.get("DTUSER")),
            kind=kind,
            note=memo if memo != name else "",
        ))

    if not expenses:
        raise LoaderError(f"{path}: found no usable transactions")
    return expenses


def _category_from_type(trn_type: str, kind: str) -> str:
    if kind == INCOME:
        return {"DIRECTDEP": "Salary", "DEP": "Deposit", "INT": "Interest",
                "DIV": "Dividends"}.get(trn_type, "Income")
    return {"ATM": "Cash", "CHECK": "Cheques", "FEE": "Fees", "SRVCHG": "Bank fees",
            "PAYMENT": "Payments", "POS": "Card payments"}.get(trn_type, "Uncategorized")


register(Format("ofx", "OFX / QFX bank & card statements (Quicken, Money, most US banks)",
                ("ofx", "qfx"), load_ofx,
                lambda head: b"OFXHEADER" in head[:400].upper() or b"<OFX>" in head.upper()))
