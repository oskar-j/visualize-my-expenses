"""Format registry and detection for :mod:`vme.io`."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..models import Expense

__all__ = ["LoaderError", "Format", "register", "FORMATS", "detect_format", "extensions_for"]


class LoaderError(ValueError):
    """Raised when an input file cannot be read as expenses."""


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


FORMATS: "Dict[str, Format]" = {}


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
            with open(path, "r", encoding=enc, newline="") as handle:
                return handle.read()
        except UnicodeDecodeError as exc:  # try the next one
            last = exc
        except OSError as exc:
            raise LoaderError(f"cannot open {path}: {exc}") from exc
    raise LoaderError(f"cannot decode {path}: {last}")


def require(module: str, extra: str, fmt: str) -> Any:
    """Import an optional dependency or explain how to install it."""
    try:
        return __import__(module)
    except ImportError as exc:
        raise LoaderError(
            f"reading {fmt} files needs the '{module}' package. "
            f"Install it with:  pip install \"visualize-my-expenses[{extra}]\""
        ) from exc
