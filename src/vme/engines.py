"""Engines: who decides how the chart looks.

vme always draws the Sankey with matplotlib -- seaborn has no Sankey of its own.
The engine decides the look:

* ``matplotlib`` -- vme's own palette, checked for colour-blind separation and
  for contrast against its background, and vme's font stack.
* ``seaborn`` -- seaborn's look: a seaborn palette (``deep`` unless another is
  named), seaborn's font stack, and the type sizes of a seaborn context
  (``notebook`` unless ``paper``, ``talk`` or ``poster`` is named). Needs the
  ``seaborn`` extra: ``pip install "vme-py[seaborn]"``.

The background, light or dark, stays vme's under both engines, and so do the
colours of income, savings, the hub and "Other": seaborn has no dark mode, and
its styles (``darkgrid`` and the rest) set up axes and grids, which a Sankey
does not draw.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, replace
from typing import Any, Optional, Tuple

from .theme import FONT_STACK, Theme, get_theme

__all__ = ["CONTEXTS", "ENGINES", "Style", "get_style"]

ENGINES = ("matplotlib", "seaborn")
#: seaborn's plotting contexts, smallest type first.
CONTEXTS = ("paper", "notebook", "talk", "poster")

#: Category colours a palette may give: past these, categories are drawn grey,
#: the colour of "Other" (see :meth:`vme.theme.Theme.color_for`).
SLOTS = 8

#: Suggested in the error for a palette name seaborn does not know.
_PALETTE_EXAMPLES = "deep, muted, pastel, bright, dark, colorblind, tab10, Set2"


@dataclass(frozen=True)
class Style:
    """Everything an engine decides: colours, font stack and type scale."""

    engine: str
    theme: Theme
    fonts: Tuple[str, ...]
    font_scale: float = 1.0


def get_style(engine: str = "matplotlib", theme: str = "light",
              palette: Optional[str] = None, context: Optional[str] = None) -> Style:
    """The look of a chart drawn by ``engine`` on the ``theme`` background.

    ``palette`` and ``context`` are seaborn's, so they need ``engine="seaborn"``.

    :raises ValueError: for an unknown engine, theme, palette or context.
    :raises ImportError: for ``engine="seaborn"`` when seaborn is not installed.
    """
    name = (engine or "matplotlib").strip().lower()
    if name not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}; choose from: {', '.join(ENGINES)}")
    base = get_theme(theme)

    if name == "matplotlib":
        given = [option for option, value in (("palette", palette), ("context", context))
                 if value]
        if given:
            raise ValueError(
                f"{' and '.join(given)} {'comes' if len(given) == 1 else 'come'} from "
                "seaborn, so use the seaborn engine: --engine seaborn "
                "(engine=\"seaborn\" from Python)"
            )
        return Style("matplotlib", base, tuple(FONT_STACK))

    seaborn = _import_seaborn()
    context = (context or "notebook").strip().lower()
    if context not in CONTEXTS:
        raise ValueError(f"unknown context {context!r}; choose from: {', '.join(CONTEXTS)}")
    notebook = seaborn.plotting_context("notebook")["font.size"]
    return Style(
        engine="seaborn",
        theme=replace(base, categorical=_palette(seaborn, palette or "deep")),
        # The font stack of seaborn's own styles: every one of them sets the same.
        fonts=tuple(seaborn.axes_style("darkgrid")["font.sans-serif"]),
        font_scale=float(seaborn.plotting_context(context)["font.size"]) / notebook,
    )


def _import_seaborn() -> Any:
    try:
        import seaborn
    except ImportError as exc:
        raise ImportError(
            "the seaborn engine needs seaborn. Install it with:  "
            'pip install "vme-py[seaborn]"'
        ) from exc
    return seaborn


def _palette(seaborn: Any, name: str) -> Tuple[str, ...]:
    """Up to :data:`SLOTS` colours of a seaborn palette, its greys left out.

    Most seaborn palettes carry a grey (slot 8 of ``deep``, ``colorblind`` and
    ``tab10``). Grey is how vme draws "Other", so a category in it would read
    as folded.
    """
    try:
        colours = seaborn.color_palette(name).as_hex()
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"{name!r} is not a seaborn palette; try one of: {_PALETTE_EXAMPLES}"
        ) from exc
    vivid = [colour for colour in dict.fromkeys(colours) if not _is_grey(colour)]
    return tuple(vivid[:SLOTS])


def _is_grey(colour: str) -> bool:
    red, green, blue = (int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    _, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    return saturation < 0.08 or lightness < 0.04 or lightness > 0.96
