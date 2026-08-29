"""The public API and the files it writes."""

from __future__ import annotations

import struct
from decimal import Decimal

import pytest

from vme import Visualizer
from vme.data_store import CurrencyError
from vme.theme import get_theme


def png_size(path):
    """Width and height straight out of the PNG IHDR chunk."""
    with open(path, "rb") as handle:
        header = handle.read(24)
    assert header[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", header[16:24])


class TestConstruction:
    def test_the_old_super_call_bug_is_gone(self, rows):
        # Visualizer.__init__ used to skip Calculator.__init__ and leave
        # self.verbose unset, so any render blew up with AttributeError
        assert Visualizer(rows).verbose is False

    def test_rows_are_coerced_from_dicts(self):
        v = Visualizer([{"category": "Food", "label": "Lidl", "amount": "12,50",
                         "currency": "PLN"}], currency="PLN")
        assert v.rows[0].amount == Decimal("12.50")

    def test_no_rows_is_allowed_until_you_draw(self):
        assert Visualizer().rows == []

    def test_from_file_titles_itself_after_the_file(self, csv_file):
        assert Visualizer.from_file(str(csv_file), currency="PLN").title == "Budget"

    def test_currency_is_normalised(self):
        assert Visualizer(currency="pln").currency == "PLN"

    def test_rates_accept_a_file_path(self, tmp_path):
        rates = tmp_path / "r.json"
        rates.write_text('{"EUR": 4.3}')
        v = Visualizer([{"category": "Food", "amount": 10, "currency": "EUR"}],
                       currency="PLN", rates=str(rates))
        assert v.rates["EUR"] == Decimal("4.3")

    def test_rates_of_the_wrong_type_are_refused(self):
        with pytest.raises(TypeError, match="mapping"):
            Visualizer([], rates=4.3)


class TestGraph:
    def test_graph_is_prepared_and_validated(self, rows):
        graph = Visualizer(rows, currency="PLN").graph()
        assert graph.node("hub").value == Decimal("7000")

    def test_empty_rows_raise_the_documented_message(self):
        with pytest.raises(ValueError, match="Data has bad structure"):
            Visualizer([]).graph()

    def test_the_message_lists_the_problems(self):
        with pytest.raises(ValueError, match="no rows to plot"):
            Visualizer([]).graph()

    def test_a_missing_rate_is_reported(self):
        v = Visualizer([{"category": "Food", "amount": 10, "currency": "EUR"}],
                       currency="PLN")
        with pytest.raises(CurrencyError, match="EUR"):
            v.graph()

    def test_prepare_is_idempotent(self, rows):
        v = Visualizer(rows, currency="PLN")
        v.prepare()
        first = list(v.rows)
        v.prepare()
        assert v.rows == first

    def test_the_period_filter_reaches_the_graph(self, csv_file):
        v = Visualizer.from_file(str(csv_file), currency="PLN", period="2026-08")
        assert len(v.graph().nodes_at(0)) == 1      # only the August salary
        assert v.subtitle == "August 2026"


class TestFooterAndConsole:
    def test_footer_reports_converted_totals(self):
        rows = [{"category": "Income", "label": "Pay", "amount": 100,
                 "currency": "EUR", "kind": "income"},
                {"category": "Food", "label": "Lidl", "amount": 50, "currency": "EUR"}]
        v = Visualizer(rows, currency="PLN", rates={"EUR": 4})
        footer = v.footer()
        assert "400" in footer and "200" in footer        # 100*4 in, 50*4 out
        assert "2 transactions" in footer

    def test_footer_names_an_overspend(self):
        rows = [{"category": "Income", "label": "Pay", "amount": 100, "kind": "income"},
                {"category": "Food", "label": "Lidl", "amount": 150}]
        assert "Overspent" in Visualizer(rows, currency="USD").footer()

    def test_console_output(self, rows, capsys):
        Visualizer(rows, currency="PLN").print_to_console()
        assert "Housing" in capsys.readouterr().out


class TestRendering:
    def test_writes_a_png(self, rows, tmp_path):
        out = tmp_path / "plot.png"
        assert Visualizer(rows, currency="PLN").create_png(str(out)) == str(out)
        assert out.stat().st_size > 5_000

    def test_png_honours_the_requested_size(self, rows, tmp_path):
        out = tmp_path / "plot.png"
        Visualizer(rows, currency="PLN").create_png(str(out), width=1200, height=800,
                                                    dpi=100)
        assert png_size(out) == (1200, 800)

    def test_height_scales_with_the_row_count_by_default(self, rows, tmp_path):
        small = tmp_path / "small.png"
        Visualizer(rows[:3], currency="PLN").create_png(str(small), width=800, dpi=100)
        big = tmp_path / "big.png"
        many = list(rows) + [{"category": f"Cat{i}", "label": f"L{i}", "amount": 10}
                             for i in range(12)]
        Visualizer(many, currency="PLN").create_png(str(big), width=800, dpi=100)
        assert png_size(big)[1] > png_size(small)[1]

    @pytest.mark.parametrize("suffix", [".png", ".svg", ".pdf"])
    def test_vector_and_raster_formats(self, rows, tmp_path, suffix):
        out = tmp_path / f"plot{suffix}"
        Visualizer(rows, currency="PLN").save(str(out))
        assert out.stat().st_size > 1_000

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_both_themes_render(self, rows, tmp_path, theme):
        out = tmp_path / f"{theme}.png"
        Visualizer(rows, currency="PLN", theme=theme).create_png(str(out))
        assert out.exists()

    def test_an_unknown_theme_is_rejected(self, rows):
        with pytest.raises(ValueError, match="unknown theme"):
            Visualizer(rows, theme="neon").theme()

    def test_an_unknown_extension_is_rejected(self, rows, tmp_path):
        with pytest.raises(ValueError, match="don't know how to write"):
            Visualizer(rows, currency="PLN").save(str(tmp_path / "plot.docx"))

    def test_transparent_background(self, rows, tmp_path):
        out = tmp_path / "t.png"
        Visualizer(rows, currency="PLN").create_png(str(out), transparent=True)
        assert out.exists()

    def test_run_writes_the_default_file(self, rows, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert Visualizer(rows, currency="PLN").run() == "expenses.png"
        assert (tmp_path / "expenses.png").exists()

    def test_html_needs_plotly(self, rows, tmp_path):
        pytest.importorskip("plotly")
        out = tmp_path / "plot.html"
        Visualizer(rows, currency="PLN").create_html(str(out))
        assert "sankey" in out.read_text().lower()

    def test_save_picks_html_by_extension(self, rows, tmp_path):
        pytest.importorskip("plotly")
        out = tmp_path / "plot.html"
        Visualizer(rows, currency="PLN").save(str(out))
        assert out.stat().st_size > 1_000


class TestTheme:
    def test_palette_slots_are_distinct(self):
        for name in ("light", "dark"):
            theme = get_theme(name)
            assert len(set(theme.categorical)) == len(theme.categorical)

    def test_beyond_the_last_slot_is_grey(self):
        theme = get_theme("light")
        assert theme.color_for(len(theme.categorical)) == theme.other
        assert theme.color_for(-1) == theme.other
