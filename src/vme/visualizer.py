"""The public API: load rows, then draw them.

    >>> from vme import Visualizer
    >>> Visualizer.from_file("august.csv", currency="PLN").create_png("august.png")
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Union

from .currencies import format_money, load_rates
from .data_store import Calculator
from .engines import Style, get_style
from .models import SankeyGraph
from .rules import RuleReport, load_rules
from .sankey import GraphOptions
from .theme import Theme
from .tools import period_label

__all__ = ["Visualizer"]


def _as_rates(rates: Any, target: str) -> dict:
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


def title_for(paths: Sequence[Union[str, os.PathLike[str]]]) -> str:
    """A heading from file names: ``["checking.ofx", "credit-card.csv"]`` ->
    ``"Checking + Credit Card"``."""
    return " + ".join(
        os.path.splitext(os.path.basename(os.fspath(path)))[0]
        .replace("_", " ").replace("-", " ").strip().title()
        for path in paths
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
    :param engine: ``"matplotlib"`` (vme's own look) or ``"seaborn"`` (seaborn's
        palette, fonts and type sizes; needs the ``seaborn`` extra).
    :param palette: a seaborn palette name, such as ``"colorblind"``; seaborn engine only.
    :param context: ``"paper"``, ``"notebook"``, ``"talk"`` or ``"poster"``; seaborn
        engine only.
    :param rules: categorisation rules: the path to a CSV or JSON rules file, a
        mapping such as ``{"lidl": "Groceries"}``, or a list of rules (see
        :mod:`vme.rules`). They run before anything else, on every row.
    """

    def __init__(self, rows: Optional[Iterable[Any]] = None, currency: str = "USD",
                 title: str = "", subtitle: str = "", theme: str = "light",
                 sign: str = "auto", rates: Optional[Any] = None,
                 period: Optional[str] = None, engine: str = "matplotlib",
                 palette: Optional[str] = None, context: Optional[str] = None,
                 rules: Optional[Any] = None, **kwargs: Any):
        super().__init__(rows=rows, currency=currency,
                         verbose=bool(kwargs.pop("verbose", False)))
        self.title = title
        self.subtitle = subtitle
        self.theme_name = theme
        self.engine = engine
        self.palette = palette
        self.context = context
        self.style()  # an unknown engine or palette, or a missing seaborn, fails here
        self.sign = sign
        self.rates = _as_rates(rates, self.currency)
        self.rules = load_rules(rules)  # a bad rules file fails here, before any drawing
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

    # ------------------------------------------------------------ construction
    @classmethod
    def from_file(cls, path: str, fmt: Optional[str] = None, currency: str = "USD",
                  loader_options: Optional[Mapping[str, Any]] = None,
                  **kwargs: Any) -> Visualizer:
        """Read ``path`` (any supported format) and return a ready visualizer."""
        return cls.from_files([path], fmt=fmt, currency=currency,
                              loader_options=loader_options, **kwargs)

    @classmethod
    def from_files(cls, paths: Iterable[Union[str, os.PathLike[str]]],
                   fmt: Optional[str] = None, currency: str = "USD",
                   loader_options: Optional[Mapping[str, Any]] = None,
                   **kwargs: Any) -> Visualizer:
        """Read several files into one chart: a current account and a card, say.

        Every file is read with the same ``fmt`` and ``loader_options``, and
        decides its own sign convention. Use a ``skip`` rule for the transfers
        between the accounts, or they count twice.
        """
        if isinstance(paths, (str, os.PathLike)):
            paths = [paths]
        paths = list(paths)
        if not paths:
            raise ValueError("no files to read")
        visualizer = cls(currency=currency, **kwargs)
        for path in paths:
            visualizer.add_file(path, fmt=fmt, **dict(loader_options or {}))
        if not visualizer.title:
            visualizer.title = title_for(paths)
        return visualizer

    def add_file(self, path: Union[str, os.PathLike[str]], fmt: Optional[str] = None,
                 **loader_options: Any) -> Visualizer:
        """Add the rows of one more file.

        Its sign convention is decided on its own rows, so a bank statement
        (negative = money out) and a plain list of expenses can be drawn
        together.
        """
        from .io import load

        options = dict(loader_options)
        options.setdefault("default_currency", self.currency)
        self._append_file(load(os.fspath(path), fmt, **options))
        return self

    # -------------------------------------------------------------- pipeline
    def prepare(self, force: bool = False) -> Visualizer:
        """Resolve directions, convert currencies, apply the period filter.

        Runs once, and again after rows are set, added or inserted -- always
        over every row as loaded.
        """
        if self._prepared and not force:
            return self
        self._prepare(sign=self.sign, rates=self.rates, period=self.period, rules=self.rules)
        self._prepared = True
        if not self.title:
            self.title = "Where the money went"
        if not self.subtitle:
            span = self.date_range()
            if span:
                self.subtitle = self._made_subtitle = period_label(*span)
        return self

    def style(self) -> Style:
        """Colours, fonts and type scale, as the engine decides them."""
        return get_style(self.engine, self.theme_name, self.palette, self.context)

    def theme(self) -> Theme:
        return self.style().theme

    def _render_options(self, options: Mapping[str, Any]) -> dict:
        """Constructor options, then call options, then what the engine decides."""
        style = self.style()
        merged = dict(self.render_options)
        merged.update(options)
        merged.setdefault("fonts", style.fonts)
        merged.setdefault("font_scale", style.font_scale)
        return merged

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

    def rule_report(self) -> RuleReport:
        """What the rules did: rows categorised and skipped, and the rest."""
        self.prepare()
        assert self._rule_report is not None
        return self._rule_report

    def totals(self) -> Dict[str, Decimal]:
        """Income, spending and what is left, from the prepared rows."""
        self.prepare()
        return super().totals()

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
        merged = self._render_options(options)
        merged.setdefault("footer", self.footer())
        return plotting.save(graph, str(filename), theme=self.theme(), **merged)

    #: ``create_image`` reads better when the target is an SVG or a PDF.
    create_image = create_png

    def create_html(self, filename: str = "plot.html", **options: Any) -> str:
        """Write an interactive plotly version (needs the ``html`` extra)."""
        from . import plotting

        style = self.style()
        options = dict(options)
        options.setdefault("fonts", style.fonts)
        options.setdefault("font_scale", style.font_scale)
        return plotting.write_html(self.graph(), str(filename), theme=style.theme, **options)

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
        merged = self._render_options(options)
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
