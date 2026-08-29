"""Reading expenses from files.

Supported formats are registered on import; :func:`load` picks one from the file
extension (or content) unless you name it explicitly.

    >>> from vme.io import load
    >>> rows = load("august.csv")
"""

from __future__ import annotations

from typing import List, Optional

from ..models import Expense
from . import camt, csv_loader, excel, json_loader, ofx, qif  # noqa: F401  (registration)
from .base import FORMATS, Format, LoaderError, detect_format

__all__ = ["FORMATS", "Format", "LoaderError", "detect_format", "load", "describe_formats"]


def load(path: str, fmt: Optional[str] = None, **options: object) -> List[Expense]:
    """Read ``path`` into a list of :class:`~vme.models.Expense`.

    :param fmt: force a format name (see :data:`FORMATS`); autodetected when omitted.
    :param options: passed through to the loader -- ``encoding``, ``delimiter``,
        ``sheet``, ``default_currency``, ``dayfirst``.
    """
    name = (fmt or "").strip().lower() or detect_format(str(path))
    if name not in FORMATS:
        raise LoaderError(
            f"unknown format {name!r}; choose one of: {', '.join(sorted(FORMATS))}"
        )
    return FORMATS[name].loader(str(path), **options)


def describe_formats() -> "List[tuple]":
    """``[(name, extensions, description, optional_dependency), ...]``"""
    return [
        (f.name, ", ".join("." + e for e in f.extensions), f.description, f.requires)
        for f in FORMATS.values()
    ]
