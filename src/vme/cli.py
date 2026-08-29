"""``vme`` -- the command line.

    vme render august.csv -o august.png --month 2026-08
    vme summary statement.ofx
    vme formats
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional, Tuple

import click

from . import __version__
from .currencies import CURRENCIES, RateError, get_currency, load_rates
from .data_store import SIGN_CONVENTIONS, CurrencyError
from .io import FORMATS, LoaderError, describe_formats
from .theme import THEMES
from .visualizer import HTML_SUFFIXES, IMAGE_SUFFIXES, Visualizer

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"], max_content_width=100)


def _fail(message: str, hint: str = "") -> None:
    click.secho(f"error: {message}", fg="red", err=True)
    if hint:
        click.secho(hint, fg="yellow", err=True)
    raise SystemExit(2)


def _parse_rates(pairs: "Tuple[str, ...]", rates_file: Optional[str] = None,
                 target: str = "USD") -> "Dict[str, Any]":
    """Merge a rates file with any ``--rate CODE=FACTOR`` flags (flags win)."""
    rates: "Dict[str, Any]" = {}
    if rates_file:
        try:
            rates.update(load_rates(rates_file, target))
        except RateError as exc:
            _fail(str(exc))
    for pair in pairs:
        if "=" not in pair:
            _fail(f"bad --rate {pair!r}",
                  "Use CODE=FACTOR, for example --rate EUR=4.30")
        code, _, factor = pair.partition("=")
        try:
            value = float(factor)
        except ValueError:
            _fail(f"bad --rate {pair!r}: {factor!r} is not a number")
            return rates  # unreachable; keeps type checkers happy
        if value <= 0:
            _fail(f"bad --rate {pair!r}: the rate must be positive")
        rates[code.strip().upper()] = value
    return rates


def _period(month: Optional[str], year: Optional[str],
            period: Optional[str]) -> Optional[str]:
    given = [value for value in (month, year, period) if value]
    if len(given) > 1:
        _fail("use only one of --month, --year and --period")
    return given[0] if given else None


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(__version__, "-V", "--version", prog_name="vme")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Turn a list of budget expenses into a Sankey diagram.

    \b
    Quick start:
      vme sample budget.csv            write an example file to start from
      vme render budget.csv            draw expenses.png
      vme render budget.csv -o may.png --month 2026-05
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# --------------------------------------------------------------------------- #


@main.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option("-o", "--output", default="expenses.png", show_default=True,
              type=click.Path(dir_okay=False, writable=True),
              help="Where to write the picture (.png, .svg, .pdf, or .html).")
@click.option("-f", "--format", "fmt", type=click.Choice(sorted(FORMATS)),
              help="Input format. Guessed from the file name when omitted.")
@click.option("-c", "--currency", default="USD", show_default=True,
              help="Currency the report is drawn in.")
@click.option("--rate", "rates", multiple=True, metavar="CODE=FACTOR",
              help="Convert another currency into --currency, e.g. --rate EUR=4.30. Repeatable.")
@click.option("--rates", "rates_file", metavar="FILE",
              type=click.Path(exists=True, dir_okay=False, readable=True),
              help="JSON or CSV file of conversion rates. --rate flags override it.")
@click.option("-m", "--month", metavar="YYYY-MM", help="Only this month.")
@click.option("-y", "--year", metavar="YYYY", help="Only this year.")
@click.option("-p", "--period", metavar="START..END", help="Only this date range.")
@click.option("-t", "--title", default="", help="Heading drawn on the plot.")
@click.option("--subtitle", default="", help="Second line under the heading.")
@click.option("--theme", type=click.Choice(sorted(THEMES)), default="light",
              show_default=True, help="Colour scheme.")
@click.option("--sign", type=click.Choice(SIGN_CONVENTIONS), default="auto",
              show_default=True,
              help="What a negative amount means when the file does not say.")
@click.option("--top", "top_categories", type=click.IntRange(1, 40), metavar="N",
              help="Keep the N biggest categories, fold the rest into 'Other'.")
@click.option("--max-labels", type=click.IntRange(1, 40), default=6, show_default=True,
              help="Most detail rows to show inside one category.")
@click.option("--min-share", type=click.FloatRange(0, 100), default=0.0,
              help="Fold anything under this percent of the total into 'Other'.")
@click.option("--no-detail", is_flag=True, help="Stop at categories; skip the label column.")
@click.option("--no-savings", is_flag=True, help="Do not draw the left-over branch.")
@click.option("--group-income", is_flag=True, help="Group income by category, not by label.")
@click.option("--width", type=click.IntRange(400, 8000), default=1600, show_default=True,
              help="Image width in pixels.")
@click.option("--height", type=click.IntRange(300, 8000),
              help="Image height in pixels. Scales with the row count when omitted.")
@click.option("--dpi", type=click.IntRange(50, 600), default=200, show_default=True,
              help="Dots per inch.")
@click.option("--transparent", is_flag=True, help="Transparent background.")
@click.option("--no-percent", is_flag=True, help="Hide the percentage next to each amount.")
@click.option("--sheet", help="Worksheet name, for Excel input.")
@click.option("--encoding", help="Input encoding. Autodetected when omitted.")
@click.option("--delimiter", help="Column separator, for CSV input. Sniffed when omitted.")
@click.option("--dayfirst/--monthfirst", default=None,
              help="How to read ambiguous dates like 03/04/2026.")
@click.option("--open", "open_after", is_flag=True, help="Open the result when done.")
@click.option("-q", "--quiet", is_flag=True, help="Only print the output path.")
@click.option("-v", "--verbose", is_flag=True, help="Explain what is being filtered out.")
def render(source: str, output: str, fmt: Optional[str], currency: str,
           rates: "Tuple[str, ...]", rates_file: Optional[str],
           month: Optional[str], year: Optional[str],
           period: Optional[str], title: str, subtitle: str, theme: str, sign: str,
           top_categories: Optional[int], max_labels: int, min_share: float,
           no_detail: bool, no_savings: bool, group_income: bool, width: int,
           height: Optional[int], dpi: int, transparent: bool, no_percent: bool,
           sheet: Optional[str], encoding: Optional[str], delimiter: Optional[str],
           dayfirst: Optional[bool], open_after: bool, quiet: bool,
           verbose: bool) -> None:
    """Draw SOURCE as a Sankey diagram.

    \b
    Examples:
      vme render budget.csv -o august.png --month 2026-08
      vme render statement.ofx -c EUR --top 8 --theme dark
      vme render trip.csv -c PLN --rate EUR=4.30 --rate UAH=0.095
      vme render expenses.json -o report.html
    """
    suffix = os.path.splitext(output)[1].lower()
    if suffix not in IMAGE_SUFFIXES + HTML_SUFFIXES:
        _fail(f"cannot write {suffix or output!r}",
              "Supported: " + ", ".join(IMAGE_SUFFIXES + HTML_SUFFIXES))

    loader_options = {k: v for k, v in (
        ("sheet", sheet), ("encoding", encoding), ("delimiter", delimiter),
        ("dayfirst", dayfirst)) if v is not None}

    visualizer = _build(source, fmt, currency, loader_options, dict(
        title=title, subtitle=subtitle, theme=theme, sign=sign,
        rates=_parse_rates(rates, rates_file, currency),
        period=_period(month, year, period),
        verbose=verbose, detail=not no_detail, top_categories=top_categories,
        max_labels=max_labels, min_share=min_share, show_savings=not no_savings,
        group_income=group_income,
    ))

    render_options: "Dict[str, Any]" = {}
    if suffix not in HTML_SUFFIXES:
        render_options = dict(width=width, height=height, dpi=dpi,
                              transparent=transparent, show_percent=not no_percent)

    try:
        written = visualizer.save(output, **render_options)
    except (ValueError, CurrencyError, ImportError) as exc:
        _fail(str(exc))

    if quiet:
        click.echo(written)
    else:
        click.secho(f"✓ {written}", fg="green", bold=True)
        click.echo(_totals_line(visualizer.totals(), visualizer.currency,
                                len(visualizer.rows)))

    if open_after:
        _open(written)


# --------------------------------------------------------------------------- #


@main.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option("-f", "--format", "fmt", type=click.Choice(sorted(FORMATS)),
              help="Input format. Guessed from the file name when omitted.")
@click.option("-c", "--currency", default="USD", show_default=True,
              help="Currency the report is shown in.")
@click.option("--rate", "rates", multiple=True, metavar="CODE=FACTOR",
              help="Convert another currency into --currency. Repeatable.")
@click.option("--rates", "rates_file", metavar="FILE",
              type=click.Path(exists=True, dir_okay=False, readable=True),
              help="JSON or CSV file of conversion rates.")
@click.option("-m", "--month", metavar="YYYY-MM", help="Only this month.")
@click.option("-y", "--year", metavar="YYYY", help="Only this year.")
@click.option("-p", "--period", metavar="START..END", help="Only this date range.")
@click.option("--sign", type=click.Choice(SIGN_CONVENTIONS), default="auto",
              show_default=True)
@click.option("--sheet", help="Worksheet name, for Excel input.")
@click.option("--encoding", help="Input encoding. Autodetected when omitted.")
@click.option("-v", "--verbose", is_flag=True)
def summary(source: str, fmt: Optional[str], currency: str, rates: "Tuple[str, ...]",
            rates_file: Optional[str],
            month: Optional[str], year: Optional[str], period: Optional[str],
            sign: str, sheet: Optional[str], encoding: Optional[str],
            verbose: bool) -> None:
    """Print the breakdown as a table, without drawing anything."""
    loader_options = {k: v for k, v in (("sheet", sheet), ("encoding", encoding))
                      if v is not None}
    visualizer = _build(source, fmt, currency, loader_options, dict(
        sign=sign, rates=_parse_rates(rates, rates_file, currency),
        period=_period(month, year, period), verbose=verbose,
    ))
    try:
        visualizer.print_to_console()
    except (ValueError, CurrencyError) as exc:
        _fail(str(exc))


@main.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option("-f", "--format", "fmt", type=click.Choice(sorted(FORMATS)))
@click.option("-c", "--currency", default="USD", show_default=True)
@click.option("--sign", type=click.Choice(SIGN_CONVENTIONS), default="auto",
              show_default=True)
def check(source: str, fmt: Optional[str], currency: str, sign: str) -> None:
    """Read SOURCE and report anything that would stop it being plotted."""
    visualizer = _build(source, fmt, currency, {}, dict(sign=sign))
    try:
        visualizer.prepare()
    except (ValueError, CurrencyError) as exc:
        _fail(str(exc))
    problems = visualizer.problems()
    if not problems:
        click.secho(f"✓ {len(visualizer.rows)} rows look fine", fg="green", bold=True)
        span = visualizer.date_range()
        if span:
            click.echo(f"  dates {span[0].isoformat()} .. {span[1].isoformat()}")
        click.echo("  " + _totals_line(visualizer.totals(), visualizer.currency,
                                       len(visualizer.rows)))
        return
    click.secho(f"✗ {len(problems)} problem(s)", fg="red", bold=True)
    for problem in problems:
        click.echo(f"  - {problem}")
    raise SystemExit(1)


@main.command()
def formats() -> None:
    """List the input formats vme can read."""
    click.secho("Input formats", bold=True)
    for name, extensions, description, requires in describe_formats():
        note = click.style(f"  (needs {requires})", fg="yellow") if requires else ""
        click.echo(f"  {click.style(name, fg='cyan'):<18} {extensions:<16} "
                   f"{description}{note}")
    click.echo("\nOutput: " + ", ".join(IMAGE_SUFFIXES) + " and .html (needs plotly)")


@main.command()
@click.argument("query", required=False)
def currencies(query: Optional[str]) -> None:
    """List the currencies vme knows how to format.

    \b
    Any ISO code works even if it is not listed -- an unknown code is printed
    as-is. QUERY filters by code or name, e.g. `vme currencies zlot`.
    """
    needle = (query or "").strip().lower()
    matches = [c for c in CURRENCIES.values()
               if not needle or needle in c.code.lower() or needle in c.name.lower()]
    if not matches:
        click.secho(f"nothing matches {query!r}", fg="yellow")
        raise SystemExit(1)
    click.secho(f"{len(matches)} currencies", bold=True)
    for spec in sorted(matches, key=lambda c: c.code):
        example = _example(spec.code)
        click.echo(f"  {click.style(spec.code, fg='cyan')}  {spec.symbol:<4} "
                   f"{spec.name:<24} {example}")
    click.echo("\nMix currencies in one file and convert them at render time:")
    click.echo("  vme render trip.csv -c PLN --rate EUR=4.30 --rate UAH=0.095")


def _example(code: str) -> str:
    from .currencies import format_money

    return format_money(1234.5, code)


@main.command()
@click.argument("destination", type=click.Path(dir_okay=False, writable=True),
                default="sample-budget.csv")
@click.option("--kind", type=click.Choice(["simple", "multicurrency"]),
              default="simple", show_default=True,
              help="'multicurrency' mixes EUR, PLN, UAH and USD in one file.")
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
def sample(destination: str, kind: str, force: bool) -> None:
    """Write an example CSV you can edit and render straight away."""
    if os.path.exists(destination) and not force:
        _fail(f"{destination} already exists", "Pass --force to overwrite it.")
    from .examples import MULTICURRENCY_CSV, SAMPLE_CSV

    body = MULTICURRENCY_CSV if kind == "multicurrency" else SAMPLE_CSV
    try:
        with open(destination, "w", encoding="utf-8", newline="") as handle:
            handle.write(body)
    except OSError as exc:
        _fail(f"cannot write {destination}: {exc}")
    click.secho(f"✓ {destination}", fg="green", bold=True)
    if kind == "multicurrency":
        click.echo(f"  now try:  vme render {destination} -c PLN "
                   "--rate EUR=4.30 --rate UAH=0.095 --rate USD=3.95")
    else:
        click.echo(f"  now try:  vme render {destination} -c PLN -o august.png")


# --------------------------------------------------------------------------- #


def _build(source: str, fmt: Optional[str], currency: str,
           loader_options: "Dict[str, Any]", kwargs: "Dict[str, Any]") -> Visualizer:
    try:
        return Visualizer.from_file(source, fmt=fmt, currency=currency,
                                    loader_options=loader_options, **kwargs)
    except LoaderError as exc:
        _fail(str(exc))
    except (ValueError, TypeError) as exc:
        _fail(f"{source}: {exc}")


def _totals_line(totals: "Dict[str, Any]", currency: str, count: int) -> str:
    from .tools import format_money

    parts = []
    if totals["income"]:
        parts.append(f"income {format_money(totals['income'], currency, 0)}")
    parts.append(f"spent {format_money(totals['spent'], currency, 0)}")
    if totals["income"]:
        leftover = totals["net"]
        parts.append(("left over " if leftover >= 0 else "overspent ")
                     + format_money(abs(leftover), currency, 0))
    parts.append(f"{count} rows")
    return "  ".join(parts)


def _open(path: str) -> None:
    import subprocess

    opener = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
    try:
        subprocess.run([opener, path], check=False, shell=(opener == "start"))
    except OSError as exc:  # pragma: no cover - platform dependent
        click.secho(f"could not open {path}: {exc}", fg="yellow", err=True)


if __name__ == "__main__":  # pragma: no cover
    main()
