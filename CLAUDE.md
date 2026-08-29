# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`visualize-my-expenses` (package `vme`) — a library and CLI that turns a flat list of budget rows
into a Sankey diagram, normally shared as a PNG. Sankey rendering is the whole point: money flows
income → budget hub → categories → labels, so the data model is hierarchical even though the input
is a flat list.

Not published to PyPI. It is installed from a clone, with `uv sync` or `pip install -e .`.

## Commands

```bash
uv sync                                  # or: pip install -e ".[all]"
uv run pytest                            # 248 tests, ~3s
uv run ruff check src tests
uv run python usage.py                   # smoke check; writes examples/output/usage-*.png
uv run vme render examples/budget-august.csv -c PLN -o /tmp/a.png
```

`uv.lock` is gitignored on purpose — this is a library, so dev environments are resolved fresh.

## Architecture

The inheritance chain from the original prototype is kept, one responsibility per layer:

```
CalculatorBase (data_store.py)  validation + console output  (problems, _verify, print_to_console)
   └── Calculator (data_store.py)  rows, sign conventions, conversion, period filter
          └── Visualizer (visualizer.py)  public API: create_png / create_html / save / run
```

`vme/__init__.py` re-exports `Visualizer` plus `Expense`, `SankeyGraph` and `load`. `Visualizer` is
the intended surface; callers should not need `Calculator` or `CalculatorBase`.

Around that chain sit modules that know nothing about each other:

| Module | Owns |
|---|---|
| `models.py` | `Expense` (frozen, `Decimal`, direction in `kind`), `Node`/`Link`/`SankeyGraph` |
| `currencies.py` | ~50 currencies' formatting rules; rate files (JSON/CSV) |
| `tools.py` | amount/date/direction parsing, duck-typed row coercion |
| `io/` | one self-registering module per input format |
| `sankey.py` | rows → `SankeyGraph`: folding into "Other", the savings branch |
| `plotting.py` | layout (renderer-independent) + matplotlib and plotly backends |
| `theme.py` | light/dark palettes |
| `cli.py` | the click commands |

Data path, in order: `io.load` → `coerce_row` → `apply_sign_convention` → `convert` → period filter
→ `build_graph` → `layout_graph` → a backend. Anything that changes totals must run before
`footer()` reads them — a bug once had the footer summing pre-conversion amounts.

## Things that are easy to get wrong

- **Direction, not sign.** `Expense.amount` is always non-negative; `kind` carries the direction.
  Loaders emit `kind=AUTO` when the file did not say, and `apply_sign_convention` resolves every
  `AUTO` row at once (a file with any negative amount is read as a bank statement). A row that
  reaches the plotter still `AUTO`, or with a negative amount, is a bug — `problems()` reports both.
- **Constructing `Expense` directly defaults to `EXPENSE`,** not `AUTO`. Income must say `kind="income"`.
- **Currencies never convert themselves.** Rates come from the caller; nothing hits the network,
  so the same input always draws the same picture.
- **Money formatting is per-currency** (symbol, position, decimals, separators) and rounds
  ROUND_HALF_UP. The digit-group separator is a narrow no-break space (`GROUP_SPACE`, U+202F) — tests
  comparing formatted output must use it, not a plain space.
- **Label geometry is measured, not estimated.** `_text_inches` measures with matplotlib's
  `TextPath`; margins, truncation and the inter-node gap are all derived from those measurements.
  The gap is *solved for* so every node gets a text line of clearance — see the comment in `render`.
  Changing font sizes or padding without re-deriving it brings back overlapping labels.
- **Rendering tests must use the Agg backend** (`tests/conftest.py` sets it).

## Conventions

- Python 3.9 is supported, so `typing.Optional`/`Dict`/`List` stay; ruff's PEP 604/585 rules are
  disabled in `pyproject.toml` for that reason.
- Errors that a user can act on say what to do (`--rate EUR=4.30`, `pip install "...[excel]"`).
  Loader errors name the file and line.
- Palettes are validated for colour-blind separation and contrast against their own surface, and
  every node carries a visible label — no reading of the chart depends on distinguishing two hues.
  Do not add a ninth categorical colour; past slot 8 things fold into a grey "Other".
