"""Drawing a :class:`~vme.models.SankeyGraph`.

Layout is computed once, in value space, and is renderer-independent; the
matplotlib backend (PNG/SVG/PDF, no browser needed) and the optional plotly
backend (interactive HTML) both consume the same placement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from .models import Link, SankeyGraph
from .theme import FONT_STACK, Theme, get_theme
from .currencies import format_money, get_currency

__all__ = ["Layout", "layout_graph", "render", "save", "show", "to_plotly", "write_html"]

ZERO = Decimal("0")

#: Node ordering rank per node kind -- savings always sinks to the bottom.
_KIND_RANK = {"income": 0, "hub": 0, "category": 0, "leaf": 0, "savings": 9}


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


@dataclass
class Placement:
    node: Node
    depth: int
    order: int
    top: float      # in value units, measured downwards from 0
    height: float

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def middle(self) -> float:
        return self.top + self.height / 2


@dataclass
class Ribbon:
    link: Link
    source_top: float
    target_top: float
    height: float
    color: str


@dataclass
class Layout:
    placements: "Dict[str, Placement]" = field(default_factory=dict)
    ribbons: "List[Ribbon]" = field(default_factory=list)
    columns: "List[int]" = field(default_factory=list)
    span: float = 1.0          # tallest column, in value units
    gap: float = 0.0

    def column(self, depth: int) -> "List[Placement]":
        return sorted((p for p in self.placements.values() if p.depth == depth),
                      key=lambda p: p.order)

    @property
    def widest_column(self) -> int:
        return max((len(self.column(d)) for d in self.columns), default=0)


def layout_graph(graph: SankeyGraph, gap_fraction: float = 0.018,
                 gap: Optional[float] = None) -> Layout:
    """Stack each column top-down, then slice the ribbons off the node edges.

    ``gap`` sets the space between nodes in value units directly; without it the
    gap is ``gap_fraction`` of the tallest column.
    """
    layout = Layout(columns=graph.depths)
    if not graph.nodes:
        return layout

    outgoing: "Dict[str, List[Link]]" = {}
    incoming: "Dict[str, List[Link]]" = {}
    for link in graph.links:
        outgoing.setdefault(link.source, []).append(link)
        incoming.setdefault(link.target, []).append(link)

    column_sums = {
        depth: sum((n.float_value for n in graph.nodes_at(depth)), 0.0)
        for depth in layout.columns
    }
    span_values = max(column_sums.values()) if column_sums else 0.0
    if gap is None:
        gap = gap_fraction * span_values if span_values else 0.0

    previous_order: "Dict[str, int]" = {}
    heights: "Dict[int, float]" = {}
    for depth in layout.columns:
        nodes = graph.nodes_at(depth)
        nodes.sort(key=lambda n: (
            _KIND_RANK.get(n.kind, 0),
            min((previous_order.get(link.source, 10_000) for link in incoming.get(n.key, [])),
                default=10_000),
            -n.float_value,
            n.label,
        ))
        heights[depth] = sum(n.float_value for n in nodes) + gap * max(len(nodes) - 1, 0)
        for order, node in enumerate(nodes):
            previous_order[node.key] = order
            layout.placements[node.key] = Placement(node, depth, order, 0.0, node.float_value)

    span = max(heights.values()) if heights else 0.0
    layout.span = span or 1.0
    layout.gap = gap

    for depth in layout.columns:
        cursor = (span - heights[depth]) / 2.0     # centre the column vertically
        for placement in layout.column(depth):
            placement.top = cursor
            cursor += placement.height + gap

    # Ribbons: consume each node's edge top-down, in the order of the far column.
    source_cursor = {key: p.top for key, p in layout.placements.items()}
    target_cursor = {key: p.top for key, p in layout.placements.items()}

    for depth in layout.columns:
        for placement in layout.column(depth):
            links = outgoing.get(placement.node.key, [])
            links.sort(key=lambda link: (
                layout.placements[link.target].order
                if link.target in layout.placements else 0))
            for link in links:
                target = layout.placements.get(link.target)
                if target is None:
                    continue
                height = link.float_value
                ribbon = Ribbon(
                    link=link,
                    source_top=source_cursor[placement.node.key],
                    target_top=target_cursor[link.target],
                    height=height,
                    color=link.color or placement.node.color or "#898781",
                )
                source_cursor[placement.node.key] += height
                target_cursor[link.target] += height
                layout.ribbons.append(ribbon)

    return layout


# --------------------------------------------------------------------------- #
# matplotlib backend
# --------------------------------------------------------------------------- #


def _figure_size(layout: Layout, width: int, height: Optional[int],
                 dpi: int) -> "Tuple[float, float]":
    if height is None:
        rows = max(layout.widest_column, 3)
        height = int(min(2400, max(700, 150 + 66 * rows)))
    return width / float(dpi), height / float(dpi)


#: Fallback advance width per character, in em, used only if measuring fails.
_EM_PER_CHAR = 0.55

#: Space left between a node's name and the value printed after it.
_INLINE_GAP_IN = 0.10

_RESOLVED_FONTS: "Optional[List[str]]" = None
_WIDTHS: "Dict[tuple, float]" = {}


def _fonts() -> "List[str]":
    """The font stack, filtered to what is actually installed (cached)."""
    global _RESOLVED_FONTS
    if _RESOLVED_FONTS is None:
        from matplotlib import font_manager

        installed = {face.name for face in font_manager.fontManager.ttflist}
        _RESOLVED_FONTS = [name for name in FONT_STACK if name in installed] or \
            ["DejaVu Sans"]
    return _RESOLVED_FONTS


def _text_inches(text: str, font_pt: float, weight: str = "normal") -> float:
    """Width of ``text`` in inches, measured in the real font (cached)."""
    if not text:
        return 0.0
    key = (text, round(font_pt, 2), weight)
    known = _WIDTHS.get(key)
    if known is not None:
        return known
    try:
        from matplotlib.font_manager import FontProperties
        from matplotlib.textpath import TextPath

        prop = FontProperties(family=_fonts(), weight=weight, size=font_pt)
        width = TextPath((0, 0), text, size=font_pt, prop=prop).get_extents().width / 72.0
    except Exception:  # pragma: no cover - font backends vary
        width = len(text) * _EM_PER_CHAR * font_pt / 72.0
    _WIDTHS[key] = width
    return width


def _fit(text: str, font_pt: float, inches: float, weight: str = "normal") -> str:
    """Truncate ``text`` with an ellipsis so it fits ``inches``."""
    if inches <= 0:
        return ""
    if _text_inches(text, font_pt, weight) <= inches:
        return text
    low, high = 1, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = text[:middle].rstrip() + "\u2026"
        if _text_inches(candidate, font_pt, weight) <= inches:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "\u2026" if low >= 2 else ""


def render(graph: SankeyGraph, theme: Optional[Theme] = None, width: int = 1600,
           height: Optional[int] = None, dpi: int = 200, show_values: bool = True,
           show_percent: bool = True, node_width: float = 0.013,
           curvature: float = 0.5, font_scale: float = 1.0, footer: str = ""):
    """Build (but do not save) a matplotlib ``Figure`` for ``graph``."""
    import matplotlib.patheffects as path_effects
    from matplotlib.figure import Figure
    from matplotlib.patches import PathPatch, Rectangle
    from matplotlib.path import Path

    theme = theme or get_theme("light")
    layout = layout_graph(graph, gap_fraction=0.0)   # first pass: measure only
    if not layout.placements:
        raise ValueError("nothing to draw: the graph has no nodes")

    fig_w, fig_h = _figure_size(layout, width, height, dpi)
    fig = Figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=theme.surface)

    base_pt = 10.0 * font_scale
    value_pt = 8.6 * font_scale
    title_pt = 15.0 * font_scale
    font = _fonts()

    first, last = layout.columns[0], layout.columns[-1]
    total = graph.total or Decimal("1")
    spec = get_currency(graph.currency)

    # One decimal policy for every node: mixing "3 200 zł" with "23,99 zł" in the
    # same column reads as two different scales.
    places = 0 if float(total) >= 500 else spec.decimals

    def node_text(placement: Placement) -> "Tuple[str, str]":
        node = placement.node
        text = format_money(node.value, graph.currency, places)
        if show_percent and total:
            share = float(node.value) / float(total) * 100
            if share >= 0.5:
                text = f"{text}   {share:.0f}%"
        return node.label, text

    # Vertical room comes first: it decides whether a label is one line or two,
    # which in turn decides how much horizontal room the outer columns need.
    has_header = bool(graph.title or graph.subtitle)
    top_pad = (0.12 if graph.subtitle else 0.09) if has_header else 0.03
    bottom_pad = 0.075 if footer else 0.03
    axes_h_in = fig_h * max(1 - top_pad - bottom_pad, 0.05)

    # Re-lay out with a gap wide enough that two neighbouring labels never touch.
    # Every node needs one text line of clearance, and node heights are fixed by
    # the values, so the clearance has to come out of the gap. The gap widens the
    # span, which is why it is solved for rather than guessed.
    line_in = base_pt * 1.3 / 72.0
    rows = max(layout.widest_column, 1)
    packed = layout.span                       # tallest column, gaps excluded
    denominator = 1 - line_in * (rows - 1) / axes_h_in
    if packed > 0 and denominator > 0.25:
        wanted = (line_in * packed / axes_h_in) / denominator
        gap = min(max(wanted, packed * 0.012), packed * 0.05)
    else:                                      # forced into a short figure
        gap = packed * 0.012
    layout = layout_graph(graph, gap=gap)

    units_per_inch = layout.span / max(axes_h_in, 1e-6)
    line_units = base_pt * 1.3 / 72.0 * units_per_inch

    def is_stacked(placement: Placement) -> bool:
        return show_values and placement.height >= line_units * 2.0

    def needed_inches(placement: Placement) -> float:
        name, value = node_text(placement)
        wide = _text_inches(name, base_pt, "medium")
        if not show_values:
            return wide
        if is_stacked(placement):
            return max(wide, _text_inches(value, value_pt))
        return wide + _INLINE_GAP_IN + _text_inches(value, value_pt)

    gutter_in = 0.12                # breathing room between a bar and its label
    max_pad_in = fig_w * 0.30

    def column_pad(depth: int) -> float:
        if depth == first == last:
            return 0.02
        wanted = max((needed_inches(p) for p in layout.column(depth)), default=0.0)
        return (min(wanted, max_pad_in) + gutter_in) / fig_w

    left_pad = column_pad(first) if first != last else 0.02
    right_pad = column_pad(last)

    axes = fig.add_axes([left_pad, bottom_pad,
                         max(0.05, 1 - left_pad - right_pad),
                         max(0.05, 1 - top_pad - bottom_pad)])
    axes.set_facecolor(theme.surface)
    axes.set_xlim(0, 1)
    axes.set_ylim(layout.span, 0)          # value units, first row at the top
    axes.axis("off")

    axes_w_in = fig_w * max(1 - left_pad - right_pad, 0.05)
    depth_count = max(len(layout.columns) - 1, 1)
    x_of = {depth: index / depth_count * (1 - node_width)
            for index, depth in enumerate(layout.columns)}
    #: How much room an interior label has before it reaches the next column.
    interior_in = (axes_w_in / depth_count) - (node_width * axes_w_in) - 0.10

    # ---- ribbons first, so node bars sit on top of them
    for ribbon in layout.ribbons:
        source = layout.placements[ribbon.link.source]
        target = layout.placements[ribbon.link.target]
        x0 = x_of[source.depth] + node_width
        x1 = x_of[target.depth]
        c0 = x0 + (x1 - x0) * curvature
        c1 = x1 - (x1 - x0) * curvature
        s_top, s_bottom = ribbon.source_top, ribbon.source_top + ribbon.height
        t_top, t_bottom = ribbon.target_top, ribbon.target_top + ribbon.height

        path = Path(
            [(x0, s_top), (c0, s_top), (c1, t_top), (x1, t_top),
             (x1, t_bottom), (c1, t_bottom), (c0, s_bottom), (x0, s_bottom),
             (x0, s_top)],
            [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.CLOSEPOLY],
        )
        axes.add_patch(PathPatch(path, facecolor=ribbon.color, edgecolor="none",
                                 alpha=theme.ribbon_alpha, zorder=1))

    halo = [path_effects.withStroke(linewidth=2.6, foreground=theme.surface)]
    common = dict(fontfamily=font, va="center", zorder=4)

    for placement in layout.placements.values():
        node = placement.node
        x = x_of[placement.depth]
        axes.add_patch(Rectangle((x, placement.top), node_width, placement.height,
                                 facecolor=node.color or theme.other,
                                 edgecolor="none", zorder=3))

        name, value = node_text(placement)
        outer = placement.depth in (first, last)
        if placement.depth == first and first != last:
            text_x, align, effects = x - 0.012, "right", []
        else:
            text_x, align, effects = x + node_width + 0.012, "left", \
                ([] if placement.depth == last else halo)

        stacked = is_stacked(placement)
        room_in = ((left_pad if align == "right" else right_pad) * fig_w - gutter_in
                   if outer else interior_in)
        if room_in > 0:
            # Two lines are only an option where the node is tall enough for them;
            # a short node has to fit its value beside the name or lose some name.
            if show_values and not stacked:
                room_in -= _INLINE_GAP_IN + _text_inches(value, value_pt)
            name = _fit(name, base_pt, room_in, "medium")

        if stacked:
            half = line_units * 0.55
            axes.text(text_x, placement.middle - half, name, ha=align,
                      fontsize=base_pt, color=theme.ink, fontweight="medium",
                      path_effects=effects, **common)
            axes.text(text_x, placement.middle + half, value, ha=align,
                      fontsize=value_pt, color=theme.ink_secondary,
                      path_effects=effects, **common)
            continue

        axes.text(text_x, placement.middle, name, ha=align, fontsize=base_pt,
                  color=theme.ink, fontweight="medium", path_effects=effects, **common)
        if show_values:
            step = (_text_inches(name, base_pt, "medium") + _INLINE_GAP_IN) / axes_w_in
            axes.text(text_x + (-step if align == "right" else step),
                      placement.middle, value, ha=align, fontsize=value_pt,
                      color=theme.ink_muted, path_effects=effects, **common)

    head_x = 0.02 if left_pad <= 0.1 else left_pad * 0.35
    if graph.title:
        fig.text(head_x, 0.965, graph.title, ha="left", va="top", fontsize=title_pt,
                 color=theme.ink, fontweight="semibold", fontfamily=font)
    if graph.subtitle:
        fig.text(head_x, 0.965 - (title_pt + 8) / (fig_h * 72), graph.subtitle,
                 ha="left", va="top", fontsize=base_pt, color=theme.ink_secondary,
                 fontfamily=font)
    if footer:
        fig.text(head_x, 0.022, footer, ha="left", va="bottom", fontsize=value_pt,
                 color=theme.ink_muted, fontfamily=font)

    return fig


def save(graph: SankeyGraph, path: str, theme: Optional[Theme] = None,
         transparent: bool = False, **options) -> str:
    """Render ``graph`` and write it to ``path`` (``.png``, ``.svg`` or ``.pdf``)."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    theme = theme or get_theme("light")
    dpi = int(options.pop("dpi", 200))
    figure = render(graph, theme=theme, dpi=dpi, **options)
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=dpi, facecolor="none" if transparent else theme.surface,
                   transparent=transparent)
    return str(path)


def show(graph: SankeyGraph, theme: Optional[Theme] = None, **options) -> None:
    """Open the plot in an interactive window."""
    import matplotlib.pyplot as plt

    figure = render(graph, theme=theme, **options)
    manager = plt.figure().canvas.manager
    manager.canvas.figure = figure
    figure.set_canvas(manager.canvas)
    plt.show()


# --------------------------------------------------------------------------- #
# plotly backend (optional) -- interactive HTML
# --------------------------------------------------------------------------- #


def to_plotly(graph: SankeyGraph, theme: Optional[Theme] = None):
    """Build a plotly ``Figure``. Requires the ``html`` extra."""
    try:
        import plotly.graph_objects as go
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "HTML output needs plotly. Install it with:  "
            'pip install "visualize-my-expenses[html]"'
        ) from exc

    theme = theme or get_theme("light")
    layout = layout_graph(graph)
    ordered = sorted(layout.placements.values(), key=lambda p: (p.depth, p.order))
    index = {placement.node.key: number for number, placement in enumerate(ordered)}

    labels = [f"{p.node.label}  {format_money(p.node.value, graph.currency, 0)}"
              for p in ordered]
    symbol = get_currency(graph.currency).symbol
    colors = [p.node.color or theme.other for p in ordered]

    figure = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(
            label=labels,
            color=colors,
            pad=14,
            thickness=16,
            line=dict(width=0),
            x=[p.depth / max(len(layout.columns) - 1, 1) for p in ordered],
        ),
        link=dict(
            source=[index[r.link.source] for r in layout.ribbons],
            target=[index[r.link.target] for r in layout.ribbons],
            value=[r.link.float_value for r in layout.ribbons],
            color=[_rgba(r.color, theme.ribbon_alpha) for r in layout.ribbons],
            hovertemplate="%{source.label} → %{target.label}<br>"
                          "%{value:,.2f} " + (symbol or graph.currency)
                          + "<extra></extra>",
        ),
    ))
    heading = graph.title or "Where the money went"
    if graph.subtitle:
        heading += f"<br><span style='font-size:0.7em;color:{theme.ink_secondary}'>" \
                   f"{graph.subtitle}</span>"
    figure.update_layout(
        title=dict(text=heading, x=0.02, xanchor="left",
                   font=dict(size=20, color=theme.ink)),
        paper_bgcolor=theme.surface,
        plot_bgcolor=theme.surface,
        font=dict(family=", ".join(FONT_STACK), size=13, color=theme.ink),
        margin=dict(l=24, r=24, t=80, b=32),
    )
    return figure


def _rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red},{green},{blue},{alpha:.2f})"


def write_html(graph: SankeyGraph, path: str, theme: Optional[Theme] = None,
               include_plotlyjs: str = "cdn") -> str:
    figure = to_plotly(graph, theme)
    figure.write_html(str(path), include_plotlyjs=include_plotlyjs,
                      full_html=True, config={"displaylogo": False})
    return str(path)
