"""The `vme` command line."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from vme.cli import main


@pytest.fixture
def run():
    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(main, [str(a) for a in args], catch_exceptions=False)

    return invoke


@pytest.fixture
def budget(tmp_path):
    path = tmp_path / "budget.csv"
    path.write_text(
        "date,category,label,amount,currency,kind\n"
        "2026-08-01,Income,Salary,6000,PLN,income\n"
        "2026-08-02,Housing,Rent,2000,PLN,expense\n"
        "2026-08-04,Groceries,Lidl,500,PLN,expense\n"
        "2026-08-06,Transport,Fuel,300,PLN,expense\n"
        "2026-09-04,Groceries,Lidl,450,PLN,expense\n",
        encoding="utf-8")
    return path


@pytest.fixture
def mixed(tmp_path):
    path = tmp_path / "mixed.csv"
    path.write_text(
        "date,category,label,amount,currency,kind\n"
        "2026-08-01,Income,Salary,6000,PLN,income\n"
        "2026-08-05,Travel,Hotel,200,EUR,expense\n"
        "2026-08-07,Travel,Train,1500,UAH,expense\n",
        encoding="utf-8")
    return path


class TestHelp:
    def test_bare_command_shows_help(self, run):
        result = run()
        assert result.exit_code == 0 and "Sankey" in result.output

    def test_version(self, run):
        from vme import __version__

        assert __version__ in run("--version").output

    @pytest.mark.parametrize("command", ["render", "summary", "check", "formats",
                                         "currencies", "sample"])
    def test_every_command_has_help(self, run, command):
        result = run(command, "--help")
        assert result.exit_code == 0 and result.output.strip()


class TestRender:
    def test_writes_a_png(self, run, budget, tmp_path):
        out = tmp_path / "out.png"
        result = run("render", budget, "-c", "PLN", "-o", out)
        assert result.exit_code == 0
        assert out.stat().st_size > 5_000
        assert "spent" in result.output

    def test_quiet_prints_only_the_path(self, run, budget, tmp_path):
        out = tmp_path / "out.png"
        result = run("render", budget, "-c", "PLN", "-o", out, "-q")
        assert result.output.strip() == str(out)

    def test_month_filter(self, run, budget, tmp_path):
        out = tmp_path / "aug.png"
        result = run("render", budget, "-c", "PLN", "-o", out, "-m", "2026-08")
        assert result.exit_code == 0 and "4 rows" in result.output

    def test_a_month_with_no_rows_is_explained(self, run, budget, tmp_path):
        result = run("render", budget, "-c", "PLN", "-o", tmp_path / "x.png",
                     "-m", "2026-12")
        assert result.exit_code == 2 and "no rows fall inside" in result.output

    def test_two_period_flags_are_refused(self, run, budget, tmp_path):
        result = run("render", budget, "-o", tmp_path / "x.png",
                     "-m", "2026-08", "-y", "2026")
        assert result.exit_code == 2 and "only one of" in result.output

    def test_an_unwritable_extension_is_refused(self, run, budget, tmp_path):
        result = run("render", budget, "-o", tmp_path / "x.docx")
        assert result.exit_code == 2 and "cannot write" in result.output

    def test_missing_output_directory_is_reported(self, run, budget, tmp_path):
        out = tmp_path / "nonexistent_dir" / "out.png"
        result = run("render", budget, "-c", "PLN", "-o", out)
        assert result.exit_code == 2 and "cannot write" in result.output

    def test_a_missing_file_is_refused(self, run, tmp_path):
        result = run("render", tmp_path / "nope.csv")
        assert result.exit_code == 2

    def test_svg_output(self, run, budget, tmp_path):
        out = tmp_path / "out.svg"
        run("render", budget, "-c", "PLN", "-o", out)
        assert out.read_text(encoding="utf-8").startswith("<?xml")

    def test_top_and_detail_flags(self, run, budget, tmp_path):
        out = tmp_path / "out.png"
        result = run("render", budget, "-c", "PLN", "-o", out, "--top", "2",
                     "--no-detail", "--no-savings", "--theme", "dark")
        assert result.exit_code == 0 and out.exists()

    def test_size_flags(self, run, budget, tmp_path):
        out = tmp_path / "out.png"
        result = run("render", budget, "-c", "PLN", "-o", out,
                     "--width", "900", "--height", "600", "--dpi", "100")
        assert result.exit_code == 0
        import struct
        with open(out, "rb") as handle:
            assert struct.unpack(">II", handle.read(24)[16:24]) == (900, 600)


class TestCurrencyFlags:
    def test_missing_rates_are_explained(self, run, mixed, tmp_path):
        result = run("render", mixed, "-c", "PLN", "-o", tmp_path / "x.png")
        assert result.exit_code == 2
        assert "EUR" in result.output and "--rate" in result.output

    def test_repeated_rate_flags(self, run, mixed, tmp_path):
        out = tmp_path / "x.png"
        result = run("render", mixed, "-c", "PLN", "-o", out,
                     "--rate", "EUR=4.30", "--rate", "UAH=0.095")
        assert result.exit_code == 0 and out.exists()

    def test_a_rates_file(self, run, mixed, tmp_path):
        rates = tmp_path / "rates.json"
        rates.write_text('{"EUR": 4.30, "UAH": 0.095}')
        out = tmp_path / "x.png"
        result = run("render", mixed, "-c", "PLN", "-o", out, "--rates", rates)
        assert result.exit_code == 0 and out.exists()

    def test_a_flag_overrides_the_file(self, run, mixed, tmp_path):
        rates = tmp_path / "rates.json"
        rates.write_text('{"EUR": 4.30, "UAH": 0.095}')
        first = run("summary", mixed, "-c", "PLN", "--rates", rates).output
        second = run("summary", mixed, "-c", "PLN", "--rates", rates,
                     "--rate", "EUR=8.60").output
        assert first != second

    def test_a_malformed_rate_is_refused(self, run, mixed, tmp_path):
        result = run("render", mixed, "-c", "PLN", "-o", tmp_path / "x.png",
                     "--rate", "EUR")
        assert result.exit_code == 2 and "CODE=FACTOR" in result.output

    def test_a_non_numeric_rate_is_refused(self, run, mixed, tmp_path):
        result = run("render", mixed, "-c", "PLN", "-o", tmp_path / "x.png",
                     "--rate", "EUR=lots")
        assert result.exit_code == 2 and "not a number" in result.output


class TestOtherCommands:
    def test_summary(self, run, budget):
        result = run("summary", budget, "-c", "PLN")
        assert result.exit_code == 0
        for expected in ("Housing", "Rent", "Income", "Spent"):
            assert expected in result.output

    def test_check_passes_clean_data(self, run, budget):
        result = run("check", budget, "-c", "PLN")
        assert result.exit_code == 0 and "look fine" in result.output

    def test_check_reports_mixed_currencies(self, run, mixed):
        result = run("check", mixed, "-c", "PLN")
        assert result.exit_code == 2 and "EUR" in result.output

    def test_a_statement_keeps_income_tax_on_the_spending_side(self, run, tmp_path):
        path = tmp_path / "statement.csv"
        path.write_text("date,category,label,amount\n"
                        "2026-08-01,Work,Salary,3000\n"
                        "2026-08-02,Taxes,Income tax,-500\n"
                        "2026-08-03,Utilities,Water & sewage,-80\n"
                        "2026-08-04,Groceries,Lidl,-120\n", encoding="utf-8")
        result = run("check", path)
        assert result.exit_code == 0
        assert "income $3,000" in result.output and "spent $700" in result.output

    def test_rupee_amounts_are_not_a_thousand_times_too_small(self, run, tmp_path):
        path = tmp_path / "inr.csv"
        path.write_text("date,label,amount\n"
                        '2026-08-01,Rent,"Rs. 1,000"\n'
                        "2026-08-02,Tea,Rs. 500\n", encoding="utf-8")
        result = run("check", path, "-c", "INR")
        assert result.exit_code == 0 and "spent ₹1,500" in result.output

    @pytest.mark.parametrize("command", ["render", "summary", "check"])
    def test_an_unreadable_date_is_a_note_not_an_error(self, run, tmp_path, command):
        path = tmp_path / "b.csv"
        path.write_text("date,label,amount\n2026-08-01,Rent,-2000\npending,Lidl,-45\n",
                        encoding="utf-8")
        output = ("-o", tmp_path / "b.png") if command == "render" else ()
        result = run(command, path, *output)
        assert result.exit_code == 0
        assert "note: " in result.output and "b.csv:3: cannot read the date" in result.output

    def test_a_us_file_keeps_the_whole_month(self, run, tmp_path):
        path = tmp_path / "us.csv"
        path.write_text("date,label,amount\n" + "".join(
            f"01/{d:02d}/2026,Shop,-10\n" for d in (2, 5, 10, 14, 20, 28)), encoding="utf-8")
        result = run("render", path, "-m", "2026-01", "-o", tmp_path / "us.png")
        assert result.exit_code == 0 and "6 rows" in result.output

    @pytest.mark.parametrize("command", ["render", "summary", "check"])
    def test_mixed_date_orders_ask_for_a_flag_every_command_has(self, run, tmp_path,
                                                                 command):
        path = tmp_path / "m.csv"
        path.write_text("date,label,amount\n13/01/2026,Shop,-10\n01/13/2026,Shop,-10\n",
                        encoding="utf-8")
        output = ("-o", tmp_path / "m.png") if command == "render" else ()
        result = run(command, path, *output)
        assert result.exit_code == 2 and "--monthfirst" in result.output
        assert run(command, path, "--dayfirst", *output).exit_code == 0

    def test_formats_lists_every_loader(self, run):
        output = run("formats").output
        for name in ("csv", "json", "ofx", "qif", "camt", "excel"):
            assert name in output

    def test_currencies_lists_the_table(self, run):
        output = run("currencies").output
        for code in ("EUR", "PLN", "UAH", "USD"):
            assert code in output

    def test_currencies_filters(self, run):
        output = run("currencies", "hryvnia").output
        assert "UAH" in output and "USD" not in output

    def test_currencies_reports_no_match(self, run):
        result = run("currencies", "klingon")
        assert result.exit_code == 1

    def test_sample_writes_a_file_you_can_render(self, run, tmp_path):
        out = tmp_path / "sample.csv"
        assert run("sample", out).exit_code == 0
        png = tmp_path / "sample.png"
        assert run("render", out, "-c", "PLN", "-o", png).exit_code == 0

    def test_sample_refuses_to_overwrite(self, run, tmp_path):
        out = tmp_path / "sample.csv"
        run("sample", out)
        assert run("sample", out).exit_code == 2
        assert run("sample", out, "--force").exit_code == 0

    def test_multicurrency_sample_renders_with_rates(self, run, tmp_path):
        out = tmp_path / "trip.csv"
        run("sample", out, "--kind", "multicurrency")
        png = tmp_path / "trip.png"
        result = run("render", out, "-c", "PLN", "-o", png,
                     "--rate", "EUR=4.30", "--rate", "UAH=0.095", "--rate", "USD=3.95")
        assert result.exit_code == 0 and png.exists()
