"""Colour and typography tokens.

The categorical order below is fixed on purpose: hues are assigned by slot, never
cycled or generated, so a category keeps its colour when the data changes. Both
columns are validated against their own surface (light ``#fcfcfb`` / dark
``#1a1a19``), and every node carries a visible text label, so identity is never
colour-alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

__all__ = ["Theme", "THEMES", "get_theme"]


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    ink: str
    ink_secondary: str
    ink_muted: str
    hairline: str
    categorical: Sequence[str]
    income: str
    savings: str
    hub: str
    other: str
    ribbon_alpha: float = 0.45
    ribbon_alpha_hover: float = 0.72

    def color_for(self, index: int) -> str:
        """Slot colour by position; past the last slot everything is 'Other' grey."""
        if index < 0 or index >= len(self.categorical):
            return self.other
        return self.categorical[index]


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    ink_muted="#898781",
    hairline="#e1e0d9",
    categorical=("#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                 "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
    income="#0ca30c",
    savings="#1baf7a",
    hub="#52514e",
    other="#898781",
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    ink="#ffffff",
    ink_secondary="#c3c2b7",
    ink_muted="#898781",
    hairline="#2c2c2a",
    categorical=("#3987e5", "#d95926", "#199e70", "#c98500",
                 "#d55181", "#008300", "#9085e9", "#e66767"),
    income="#0ca30c",
    savings="#199e70",
    hub="#c3c2b7",
    other="#898781",
    ribbon_alpha=0.50,
    ribbon_alpha_hover=0.78,
)

THEMES: Dict[str, Theme] = {"light": LIGHT, "dark": DARK}


def get_theme(name: str = "light") -> Theme:
    key = (name or "light").strip().lower()
    if key not in THEMES:
        raise ValueError(f"unknown theme {name!r}; choose from: {', '.join(THEMES)}")
    return THEMES[key]


#: Font stack handed to matplotlib -- system sans everywhere, no display faces.
FONT_STACK: List[str] = [
    "SF Pro Text", "Helvetica Neue", "Segoe UI", "Inter", "Roboto",
    "Liberation Sans", "Arial", "DejaVu Sans",
]
