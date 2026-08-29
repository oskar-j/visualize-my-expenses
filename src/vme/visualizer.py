"""The public API: load rows, then draw them.

    >>> from vme import Visualizer
    >>> Visualizer.from_file("august.csv", currency="PLN").create_png("august.png")
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Mapping, Optional

from .data_store import Calculator
from .models import SankeyGraph
from .sankey import GraphOptions
from .theme import Theme, get_theme
from .currencies import format_money, load_rates
from .tools import period_label

__all__ = ["Visualizer"]


def _as_rates(rates: Any, target: str) -> "dict":
    """Accept a mapping, a path to a rates file, or nothing."""
    if rates is None:
        return {}
    if isinstance(rates, Mapping):
        return dict(rates)
    if isinstance(rates, (str, os.PathLike)):
        return dict(load_rates(str(rates), target))
    raise TypeError(
        "rates must be a mapping like {'EUR': 4.30} or a path to a rates file, "
        f"not {type(rates).__name__}"
    )

IMAGE_SUFFIXES = (".png", ".svg", ".pdf", ".jpg", ".jpeg", ".webp", ".eps")
HTML_SUFFIXES = (".html", ".htm")


class Visualizer(Calculator):
    """Rows in, Sankey out.

    :param rows: anything iterable of dicts / namedtuples / :class:`~vme.models.Expense`.
    :param currency: the currency the *report* is in; rows in others need ``rates``.
    :param rates: ``{"EUR": 4.30}`` -- one euro is worth 4.30 of ``currency`` --
        or the path to a JSON/CSV rates file.
    :param title: heading drawn on the plot (defaults to a generated one).
    :param theme: ``"light"`` or ``"dark"``.
    """

    def __init__(self, rows: Optional[Iterable[Any]] = None, currency: str = "USD",
                 title: str = "", subtitle: str = "", theme: str = "light",
                 sign: str = "auto", rates: Optional[Any] = None,
                 period: Optional[str] = None, **kwargs: Any):
        super().__init__(rows=rows, currency=currency,
                         verbose=bool(kwargs.pop("verbose", False)))
        self.title = title
        self.subtitle = subtitle
        self.theme_name = theme
        self.sign = sign
        self.rates = _as_rates(rates, self.currency)
        self.period = period
        self.options = GraphOptions(
            detail=kwargs.pop("detail", True),
            top_categories=kwargs.pop("top_categories", None),
            max_labels=kwargs.pop("max_labels", 6),
            min_share=kwargs.pop("min_share", 0.0),
            show_savings=kwargs.pop("show_savings", True),
            group_income=kwargs.pop("group_income", False),
            hub_label=kwargs.pop("hub_label", None),
        )
        self.render_options = kwargs
        self._prepared = False

    # ------------------------------------------------------------ construction
    @classmethod
    def from_file(cls, path: str, fmt: Optional[str] = None, currency: str = "USD",
                  loader_options: Optional[Mapping[str, Any]] = None,
                  **kwargs: Any) -> "Visualizer":
        """Read ``path`` (any supported format) and return a ready visualizer."""
        from .io import load

        options = dict(loader_options or {})
        options.setdefault("default_currency", currency)
        rows = load(str(path), fmt, **options)
        visualizer = cls(rows=rows, currency=currency, **kwargs)
        if not visualizer.title:
            visualizer.title = os.path.splitext(os.path.basename(str(path)))[0] \
                .replace("_", " ").replace("-", " ").strip().title()
        return visualizer

    # -------------------------------------------------------------- pipeline
    def prepare(self, force: bool = False) -> "Visualizer":
        """Resolve directions, convert currencies, apply the period filter (idempotent)."""
        if self._prepared and not force:
            return self
        self._prepare(sign=self.sign, rates=self.rates, period=self.period)
        self._prepared = True
        if not self.title:
            self.title = "Where the money went"
        if not self.subtitle:
            span = self.date_range()
            if span:
                self.subtitle = period_label(*span)
        return self

    def theme(self) -> Theme:
        return get_theme(self.theme_name)

    def graph(self) -> SankeyGraph:
        """The aggregated Sankey graph for the current rows."""
        self.prepare()
        if not self._verify(verbose=self.verbose):
            raise ValueError(self._problem_message())
        return self.build_graph(options=self.options, theme=self.theme())

    def _problem_message(self) -> str:
        found = self.problems()
        listed = "\n".join(f"  - {problem}" for problem in found)
        return ("Data has bad structure - are some of your elements loose?\n" + listed)

    def footer(self) -> str:
        """The one-line summary printed under the plot."""
        self.prepare()
        totals = self.totals()
        parts = []
        if totals["income"]:
            parts.append(f"Income {format_money(totals['income'], self.currency, 0)}")
        parts.append(f"Spent {format_money(totals['spent'], self.currency, 0)}")
        if totals["income"]:
            leftover = totals["net"]
            name = "Left over" if leftover >= 0 else "Overspent"
            parts.append(f"{name} {format_money(abs(leftover), self.currency, 0)}")
        parts.append(f"{len(self.rows)} transactions")
        return "   ·   ".join(parts)

    # -------------------------------------------------------------- rendering
    def create_png(self, filename: str = "expenses.png", **options: Any) -> str:
        """Write a shareable image. ``.svg`` and ``.pdf`` work here too."""
        from . import plotting

        graph = self.graph()            # prepares and validates before we sum totals
        merged = dict(self.render_options)
        merged.update(options)
        merged.setdefault("footer", self.footer())
        return plotting.save(graph, str(filename), theme=self.theme(), **merged)

    #: ``create_image`` reads better when the target is an SVG or a PDF.
    create_image = create_png

    def create_html(self, filename: str = "plot.html", **options: Any) -> str:
        """Write an interactive plotly version (needs the ``html`` extra)."""
        from . import plotting

        return plotting.write_html(self.graph(), str(filename), theme=self.theme(),
                                   **options)

    def save(self, filename: str, **options: Any) -> str:
        """Write whichever format ``filename``'s extension asks for."""
        suffix = os.path.splitext(str(filename))[1].lower()
        if suffix in HTML_SUFFIXES:
            return self.create_html(filename, **options)
        if suffix in IMAGE_SUFFIXES:
            return self.create_png(filename, **options)
        raise ValueError(
            f"don't know how to write {suffix or filename!r}; use one of: "
            + ", ".join(IMAGE_SUFFIXES + HTML_SUFFIXES)
        )

    def show_plot(self, **options: Any) -> None:
        """Open the Sankey in an interactive matplotlib window."""
        from . import plotting

        graph = self.graph()
        merged = dict(self.render_options)
        merged.update(options)
        merged.setdefault("footer", self.footer())
        plotting.show(graph, theme=self.theme(), **merged)

    def print_to_console(self, file=None, width: int = 46) -> None:
        self.prepare()
        super().print_to_console(file=file, width=width)

    def run(self, output: Optional[str] = None) -> str:
        """Prepare, report to the console and write ``output`` (default ``expenses.png``)."""
        self.prepare()
        if self.verbose:
            self.print_to_console()
        return self.save(output or "expenses.png")
