"""Format registry and detection for :mod:`vme.io`."""

from __future__ import annotations

import datetime as _dt
import os
import warnings
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ..models import Expense
from ..tools import infer_dayfirst

__all__ = ["LoaderError", "LoaderWarning", "Format", "register", "FORMATS", "detect_format",
           "extensions_for", "resolve_dayfirst", "warn_unread_dates"]


class LoaderError(ValueError):
    """Raised when an input file cannot be read as expenses."""


class LoaderWarning(UserWarning):
    """The file was read, but part of it was not understood (the CLI prints a note)."""


LoaderFn = Callable[..., List[Expense]]


class Format:
    def __init__(self, name: str, description: str, extensions: Tuple[str, ...],
                 loader: LoaderFn, sniff: Optional[Callable[[bytes], bool]] = None,
                 requires: Optional[str] = None):
        self.name = name
        self.description = description
        self.extensions = extensions
        self.loader = loader
        self.sniff = sniff
        self.requires = requires  # optional dependency, for the error message

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Format {self.name}>"


FORMATS: Dict[str, Format] = {}


def register(fmt: Format) -> Format:
    FORMATS[fmt.name] = fmt
    return fmt


def extensions_for(name: str) -> Tuple[str, ...]:
    fmt = FORMATS.get(name)
    return fmt.extensions if fmt else ()


def detect_format(path: str, head: Optional[bytes] = None) -> str:
    """Guess the format from the file extension, falling back to content sniffing."""
    suffix = os.path.splitext(str(path))[1].lower().lstrip(".")
    for fmt in FORMATS.values():
        if suffix and suffix in fmt.extensions:
            return fmt.name

    if head is None:
        try:
            with open(path, "rb") as handle:
                head = handle.read(8192)
        except OSError as exc:
            raise LoaderError(f"cannot open {path}: {exc}") from exc

    for fmt in FORMATS.values():
        if fmt.sniff and fmt.sniff(head):
            return fmt.name

    known = ", ".join(sorted({ext for f in FORMATS.values() for ext in f.extensions}))
    raise LoaderError(
        f"cannot tell what format {os.path.basename(str(path))!r} is. "
        f"Pass --format explicitly. Known extensions: {known}"
    )


def read_text(path: str, encoding: Optional[str] = None) -> str:
    """Read a text file, tolerating BOMs and the usual bank-export encodings."""
    encodings = [encoding] if encoding else ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last: Optional[Exception] = None
    for enc in encodings:
        try:
            with open(path, encoding=enc, newline="") as handle:
                return handle.read()
        except UnicodeDecodeError as exc:  # try the next one
            last = exc
        except OSError as exc:
            raise LoaderError(f"cannot open {path}: {exc}") from exc
    raise LoaderError(f"cannot decode {path}: {last}")


def resolve_dayfirst(path: str, dayfirst: Optional[bool],
                     dates: Iterable[Any]) -> Optional[bool]:
    """``dayfirst`` as given, or worked out once from every date in the file.

    Loaders call this before building any row, so one file never mixes the two
    orders (see :func:`vme.tools.infer_dayfirst`).
    """
    if dayfirst is not None:
        return dayfirst
    try:
        return infer_dayfirst(dates)
    except ValueError as exc:
        raise LoaderError(
            f"{path}: {exc}. Say which this file uses with --dayfirst or --monthfirst "
            "(dayfirst=True or dayfirst=False from Python)."
        ) from exc


def warn_unread_dates(dates: Iterable[Tuple[str, Any, Optional[_dt.date]]]) -> None:
    """Note the date cells that held something but could not be read as a date.

    ``dates`` holds ``(where, as_written, parsed)`` for each row, ``where`` naming
    the file and line. Such a row still loads, undated, and a period filter then
    leaves it out: worth a note, not an error, since the chart can still be drawn.
    """
    unread = [(where, raw) for where, raw, parsed in dates
              if parsed is None and raw is not None and str(raw).strip()]
    if not unread:
        return
    where, raw = unread[0]
    one = len(unread) == 1
    warnings.warn(LoaderWarning(
        f"{where}: cannot read the date {raw!r}"
        + ("" if one else f" (and {len(unread) - 1} more)")
        + (". That row loads" if one else ". Those rows load")
        + " without a date, so --month, --year and --period leave "
        + ("it" if one else "them") + " out. Dates written YYYY-MM-DD always work."
    ), stacklevel=2)


def require(module: str, extra: str, fmt: str) -> Any:
    """Import an optional dependency or explain how to install it."""
    try:
        return __import__(module)
    except ImportError as exc:
        raise LoaderError(
            f"reading {fmt} files needs the '{module}' package. "
            f"Install it with:  pip install \"vme-py[{extra}]\""
        ) from exc
