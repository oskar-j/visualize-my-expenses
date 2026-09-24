"""visualize-my-expenses -- turn a budget into a Sankey diagram you can share.

    from vme import Visualizer

    Visualizer.from_file("august.csv", currency="PLN").create_png("august.png")

``Visualizer`` is the whole public surface; everything else is available for the
occasional deeper cut (:mod:`vme.io` to read files, :mod:`vme.plotting` to draw a
graph you built yourself).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .models import EXPENSE, INCOME, Expense, SankeyGraph
from .theme import THEMES, get_theme
from .visualizer import Visualizer

__all__ = ["Visualizer", "Expense", "SankeyGraph", "EXPENSE", "INCOME",
           "THEMES", "get_theme", "load", "__version__"]

# pyproject.toml holds the version; read it back rather than keep a second copy.
try:
    __version__ = version("vme-py")
except PackageNotFoundError:  # imported from a source tree that was never installed
    __version__ = "0+unknown"


def load(path, fmt=None, **options):
    """Read any supported file into a list of :class:`~vme.models.Expense` rows."""
    from .io import load as _load

    return _load(path, fmt, **options)
