"""``vme`` -- the command line.

    vme render august.csv -o august.png --month 2026-08
    vme summary statement.ofx
    vme formats
"""

from __future__ import annotations

import os
import sys
import warnings
from typing import Any, Dict, Optional, Tuple

import click

from . import __version__
from .currencies import CURRENCIES, RateError, load_rates
from .data_store import SIGN_CONVENTIONS, CurrencyError
from .engines import CONTEXTS, ENGINES, get_style
from .io import FORMATS, LoaderError, LoaderWarning, describe_formats
from .plotting import RenderWarning
from .theme import THEMES
from .visualizer import HTML_SUFFIXES, IMAGE_SUFFIXES, Visualizer

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"], max_content_width=100)

#: The options of every command that reads a file. Defined once, so render,
#: summary and check cannot drift apart: a hint that one of them prints, such
#: as "--rate EUR=4.30", works on all three.
INPUT_OPTIONS = (
    click.option("-f", "--format", "fmt", type=click.Choice(sorted(FORMATS)),
                 help="Input format. Guessed from the file name when omitted."),
    click.option("-c", "--currency", default="USD", show_default=True,
                 help="Currency the report is in."),
    click.option("--rate", "rates", multiple=True, metavar="CODE=FACTOR",
                 help="Convert another currency into --currency, e.g. --rate EUR=4.30. "
                      "Repeatable."),
    click.option("--rates", "rates_file", metavar="FILE",
                 type=click.Path(exists=True, dir_okay=False, readable=True),
                 help="JSON or CSV file of conversion rates. --rate flags override it."),
    click.option("-m", "--month", metavar="YYYY-MM", help="Only this month."),
    click.option("-y", "--year", metavar="YYYY", help="Only this year."),
    click.option("-p", "--period", metavar="START..END", help="Only this date range."),
    click.option("--sign", type=click.Choice(SIGN_CONVENTIONS), default="auto",
                 show_default=True,
                 help="What a negative amount means when the file does not say."),
    click.option("--sheet", help="Worksheet name, for Excel input."),
    click.option("--encoding", help="Input encoding. Autodetected when omitted."),
    click.option("--delimiter", help="Column separator, for CSV input. Sniffed when omitted."),
    click.option("--dayfirst/--monthfirst", default=None,
                 help="How to read dates like 03/04/2026. Worked out from the file when omitted."),
)


def input_options(command: Any) -> Any:
    """Add :data:`INPUT_OPTIONS` to ``command``, in that order in its --help."""
    for option in reversed(INPUT_OPTIONS):
        command = option(command)
    return command


def _fail(message: str, hint: str = "") -> None:
    click.secho(f"error: {message}", fg="red", err=True)
    if hint:
        click.secho(hint, fg="yellow", err=True)
    raise SystemExit(2)


def _parse_rates(pairs: Tuple[str, ...], rates_file: Optional[str] = None,
                 target: str = "USD") -> Dict[str, Any]:
    """Merge a rates file with any ``--rate CODE=FACTOR`` flags (flags win)."""
    rates: Dict[str, Any] = {}
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
@input_options
@click.option("-t", "--title", default="", help="Heading drawn on the plot.")
@click.option("--subtitle", default="", help="Second line under the heading.")
@click.option("--theme", type=click.Choice(sorted(THEMES)), default="light",
              show_default=True, help="Colour scheme.")
@click.option("--engine", type=click.Choice(ENGINES), default="matplotlib", show_default=True,
              help="The look: vme's own (matplotlib), or seaborn's palette, fonts and type "
                   'sizes (needs: pip install "vme-py[seaborn]").')
@click.option("--palette", metavar="NAME",
              help="Seaborn palette for the categories, e.g. colorblind. Needs --engine seaborn.")
@click.option("--context", type=click.Choice(CONTEXTS),
              help="Seaborn type size (default notebook). Needs --engine seaborn.")
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
@click.option("--open", "open_after", is_flag=True, help="Open the result when done.")
@click.option("-q", "--quiet", is_flag=True, help="Only print the output path.")
@click.option("-v", "--verbose", is_flag=True, help="Explain what is being filtered out.")
def render(source: str, output: str, title: str, subtitle: str, theme: str, engine: str,
           palette: Optional[str], context: Optional[str], top_categories: Optional[int],
           max_labels: int, min_share: float, no_detail: bool, no_savings: bool,
           group_income: bool, width: int, height: Optional[int], dpi: int,
           transparent: bool, no_percent: bool, open_after: bool, quiet: bool,
           verbose: bool, **inputs: Any) -> None:
    """Draw SOURCE as a Sankey diagram.

    \b
    Examples:
      vme render budget.csv -o august.png --month 2026-08
      vme render statement.ofx -c EUR --top 8 --theme dark
      vme render trip.csv -c PLN --rate EUR=4.30 --rate UAH=0.095
      vme render expenses.json -o report.html
      vme render budget.csv --engine seaborn --palette colorblind --context talk
    """
    suffix = os.path.splitext(output)[1].lower()
    if suffix not in IMAGE_SUFFIXES + HTML_SUFFIXES:
        _fail(f"cannot write {suffix or output!r}",
              "Supported: " + ", ".join(IMAGE_SUFFIXES + HTML_SUFFIXES))

    try:  # before reading the file: a missing seaborn should not wait for a big load
        get_style(engine, theme, palette, context)
    except (ValueError, ImportError) as exc:
        _fail(str(exc))

    visualizer = _read(
        source, inputs, title=title, subtitle=subtitle, theme=theme,
        engine=engine, palette=palette, context=context,
        verbose=verbose, detail=not no_detail, top_categories=top_categories,
        max_labels=max_labels, min_share=min_share, show_savings=not no_savings,
        group_income=group_income,
    )

    render_options: Dict[str, Any] = {}
    if suffix not in HTML_SUFFIXES:
        render_options = dict(width=width, height=height, dpi=dpi,
                              transparent=transparent, show_percent=not no_percent)

    try:
        with warnings.catch_warnings(record=True) as raised:
            warnings.simplefilter("always", RenderWarning)
            written = visualizer.save(output, **render_options)
    except (ValueError, CurrencyError, ImportError) as exc:
        _fail(str(exc))
    except OSError as exc:
        _fail(f"cannot write {output}: {exc.strerror or exc}")

    for warning in raised:
        if issubclass(warning.category, RenderWarning):
            click.secho(f"note: {warning.message}", fg="yellow", err=True)

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
@input_options
@click.option("-v", "--verbose", is_flag=True, help="Explain what is being filtered out.")
def summary(source: str, verbose: bool, **inputs: Any) -> None:
    """Print the breakdown as a table, without drawing anything."""
    visualizer = _read(source, inputs, verbose=verbose)
    try:
        visualizer.print_to_console()
    except (ValueError, CurrencyError) as exc:
        _fail(str(exc))


@main.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, readable=True))
@input_options
def check(source: str, **inputs: Any) -> None:
    """Read SOURCE and report anything that would stop it being plotted.

    It reads the file with the same options as render, so a file that passes
    here draws there.
    """
    visualizer = _read(source, inputs)
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
    click.echo("Engines: matplotlib (vme's own look), seaborn (needs vme-py[seaborn]); "
               "pick one with vme render --engine")


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


def _read(source: str, inputs: Dict[str, Any], **kwargs: Any) -> Visualizer:
    """Read SOURCE as :data:`INPUT_OPTIONS` say; ``kwargs`` go to the Visualizer."""
    loader_options = {key: inputs[key] for key in ("sheet", "encoding", "delimiter", "dayfirst")
                      if inputs[key] is not None}
    currency = inputs["currency"]
    return _build(source, inputs["fmt"], currency, loader_options, dict(
        sign=inputs["sign"],
        rates=_parse_rates(inputs["rates"], inputs["rates_file"], currency),
        period=_period(inputs["month"], inputs["year"], inputs["period"]),
        **kwargs,
    ))


def _build(source: str, fmt: Optional[str], currency: str,
           loader_options: Dict[str, Any], kwargs: Dict[str, Any]) -> Visualizer:
    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always", LoaderWarning)
        try:
            visualizer = Visualizer.from_file(source, fmt=fmt, currency=currency,
                                              loader_options=loader_options, **kwargs)
        except LoaderError as exc:
            _fail(str(exc))
        except (ValueError, TypeError) as exc:
            _fail(f"{source}: {exc}")
    for warning in raised:
        if issubclass(warning.category, LoaderWarning):
            click.secho(f"note: {warning.message}", fg="yellow", err=True)
        else:  # not ours to reword: show it as Python would have
            warnings.showwarning(warning.message, warning.category,
                                 warning.filename, warning.lineno)
    return visualizer


def _totals_line(totals: Dict[str, Any], currency: str, count: int) -> str:
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
