"""Engines: vme's own look, or seaborn's palette, fonts and type sizes."""

from __future__ import annotations

import colorsys
import struct
import sys
from pathlib import Path

import pytest

from vme import Visualizer
from vme.engines import CONTEXTS, SLOTS, get_style
from vme.plotting import _figure_size, _fonts, layout_graph, render
from vme.theme import FONT_STACK, get_theme

ROOT = Path(__file__).resolve().parent.parent
seaborn = pytest.importorskip("seaborn")


def png_height(path):
    with open(path, "rb") as handle:
        return struct.unpack(">II", handle.read(24)[16:24])[1]


def saturation(colour):
    rgb = (int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(*rgb)[2]


class TestMatplotlibEngine:
    def test_is_vme_s_own_look(self):
        style = get_style()
        assert style.engine == "matplotlib"
        assert style.theme == get_theme("light")
        assert style.fonts == tuple(FONT_STACK) and style.font_scale == 1.0

    @pytest.mark.parametrize("options", [dict(palette="deep"), dict(context="talk")])
    def test_seaborn_options_say_which_engine_they_need(self, options):
        with pytest.raises(ValueError, match="--engine seaborn"):
            get_style("matplotlib", **options)

    def test_an_unknown_engine_lists_the_known_ones(self):
        with pytest.raises(ValueError, match="matplotlib, seaborn"):
            get_style("plotly")


class TestSeabornEngine:
    def test_defaults_to_seaborn_s_own_defaults(self):
        style = get_style("seaborn")
        deep = [c for c in seaborn.color_palette("deep").as_hex() if saturation(c) >= 0.08]
        assert list(style.theme.categorical) == deep[:SLOTS]
        assert style.fonts == tuple(seaborn.axes_style("darkgrid")["font.sans-serif"])
        assert style.font_scale == 1.0                 # notebook

    @pytest.mark.parametrize("context,scale", [("paper", 0.8), ("notebook", 1.0),
                                               ("talk", 1.5), ("poster", 2.0)])
    def test_a_context_scales_the_type(self, context, scale):
        assert get_style("seaborn", context=context).font_scale == pytest.approx(scale)

    @pytest.mark.parametrize("palette", ["deep", "colorblind", "muted", "tab10", "Set2"])
    def test_palettes_leave_out_grey_which_means_other(self, palette):
        colours = get_style("seaborn", palette=palette).theme.categorical
        assert 0 < len(colours) <= SLOTS
        assert all(saturation(c) >= 0.08 for c in colours)

    def test_background_and_fixed_colours_stay_vme_s(self):
        for theme in ("light", "dark"):
            own, seaborn_style = get_theme(theme), get_style("seaborn", theme=theme).theme
            for field in ("surface", "ink", "income", "savings", "hub", "other"):
                assert getattr(seaborn_style, field) == getattr(own, field), (theme, field)

    def test_an_unknown_palette_suggests_real_ones(self):
        with pytest.raises(ValueError, match="not a seaborn palette; try one of: deep"):
            get_style("seaborn", palette="wibble")

    def test_an_unknown_context_lists_the_known_ones(self):
        with pytest.raises(ValueError, match=", ".join(CONTEXTS)):
            get_style("seaborn", context="huge")

    def test_without_seaborn_installed_it_says_how_to_get_it(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "seaborn", None)
        with pytest.raises(ImportError, match=r'pip install "vme-py\[seaborn\]"'):
            get_style("seaborn")


class TestVisualizer:
    def test_categories_take_the_seaborn_palette(self, rows):
        v = Visualizer(rows, currency="PLN", engine="seaborn", palette="colorblind")
        expected = get_style("seaborn", palette="colorblind").theme.categorical
        assert v.graph().node("cat:Housing").color == expected[0]

    def test_a_bad_palette_fails_when_the_visualizer_is_made(self, rows):
        with pytest.raises(ValueError, match="not a seaborn palette"):
            Visualizer(rows, engine="seaborn", palette="wibble")

    def test_writes_a_png(self, rows, tmp_path):
        out = tmp_path / "sns.png"
        Visualizer(rows, currency="PLN", engine="seaborn").create_png(str(out))
        assert out.stat().st_size > 5_000

    def test_bigger_type_gets_a_taller_image(self, rows, tmp_path):
        heights = {}
        for context in ("notebook", "talk", "poster"):
            out = tmp_path / f"{context}.png"
            Visualizer(rows, currency="PLN", engine="seaborn", context=context) \
                .create_png(str(out))
            heights[context] = png_height(out)
        assert heights["notebook"] < heights["talk"] < heights["poster"]

    def test_html_uses_the_seaborn_fonts_and_palette(self, rows, tmp_path):
        pytest.importorskip("plotly")
        out = tmp_path / "sns.html"
        Visualizer(rows, currency="PLN", engine="seaborn").create_html(str(out))
        page = out.read_text(encoding="utf-8")
        assert "Arial" in page
        assert get_style("seaborn").theme.categorical[0] in page


class TestLabelsInTheEngineFont:
    def test_text_is_drawn_and_measured_in_the_engine_s_fonts(self, rows):
        style = get_style("seaborn")
        graph = Visualizer(rows, currency="PLN", engine="seaborn").graph()
        figure = render(graph, theme=style.theme, fonts=style.fonts)
        families = {tuple(t.get_fontfamily()) for t in figure.axes[0].texts}
        assert families == {tuple(_fonts(style.fonts))}

    def test_an_uninstalled_stack_falls_back_to_a_font_that_exists(self):
        assert _fonts(["No Such Font"]) == ["DejaVu Sans"]
        assert _fonts(["No Such Font", "DejaVu Sans"]) == ["DejaVu Sans"]


class TestEveryNodeKeepsItsName:
    """A name that could not fit beside its value used to vanish, value left alone."""

    @pytest.mark.parametrize("width,font_scale", [(900, 1.0), (1600, 1.5), (1600, 2.0)])
    def test_no_node_loses_its_whole_name(self, width, font_scale):
        v = Visualizer.from_file(str(ROOT / "examples" / "budget-august.csv"), currency="PLN")
        graph = v.graph()
        figure = render(graph, theme=v.theme(), width=width, font_scale=font_scale)
        drawn = [t.get_text() for t in figure.axes[0].texts]
        for node in graph.nodes:
            assert any(text == node.label
                       or (text.endswith("…") and node.label.startswith(text[:-1].rstrip()))
                       for text in drawn), f"{node.label!r} has no visible name"

    def test_room_to_spare_keeps_every_value(self):
        v = Visualizer.from_file(str(ROOT / "examples" / "budget-august.csv"), currency="PLN")
        graph = v.graph()
        drawn = [t.get_text() for t in render(graph, theme=v.theme()).axes[0].texts]
        assert sum("zł" in text for text in drawn) == len(graph.nodes)


def test_the_automatic_height_grows_with_the_type(rows):
    layout = layout_graph(Visualizer(rows, currency="PLN").graph())
    plain = _figure_size(layout, 1600, None, 200)[1]
    assert _figure_size(layout, 1600, None, 200, font_scale=1.5)[1] > plain
    assert _figure_size(layout, 1600, 900, 200, font_scale=1.5)[1] == 900 / 200  # asked for
