# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`visualize-my-expenses` — on PyPI as `vme-py`, imported and run as `vme` — a library and CLI that turns a flat list of budget rows
into a Sankey diagram, normally shared as a PNG. Sankey rendering is the whole point: money flows
income → budget hub → categories → labels, so the data model is hierarchical even though the input
is a flat list.

Users install it with `pip install vme-py`; CI publishes it (see Releasing). For development it is
installed from a clone, with `uv sync` or `pip install -e .`.

## Commands

```bash
uv sync                                  # or: pip install -e ".[all]"
uv run pytest                            # 255 tests, ~5s
uv run ruff check src tests
uv run python usage.py                   # smoke check; writes examples/output/usage-*.png
uv run vme render examples/budget-august.csv -c PLN -o /tmp/a.png
```

Both uv and pip must keep working. `uv.lock` is committed and CI installs from it with `--locked`,
so any change to dependencies or the version in `pyproject.toml` needs `uv lock` too, or CI fails.
The lock pins only the dev/CI environment: PyPI users get the ranges in `pyproject.toml`, and the
CI build job installs the wheel with plain pip to check exactly that.

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

## Releasing

`.github/workflows/ci.yml` lints, tests and builds every PR. On a push to `master` it does the same,
then publishes to PyPI — only if the version in `pyproject.toml` is not on PyPI yet — and tags
`vX.Y.Z` with a GitHub release. A release is: bump the version in the PR, add its `CHANGELOG.md`
section, merge.

- **The version lives only in `pyproject.toml`.** Bump it with `uv version --bump patch`, which
  updates `uv.lock` in the same step. `vme.__version__` reads it from the installed metadata, so
  after a bump the dev environment reports the old number until it is reinstalled (`uv sync` does
  that; with pip, run `pip install -e .` again).
- **The distribution is `vme-py`; the package is `vme`.** Install hints in error messages name
  `vme-py[extra]`, and `importlib.metadata` lookups must use `vme-py`.
- **PyPI's trusted publisher is tied to `ci.yml` and the `pypi` environment** of
  `oskar-j/visualize-my-expenses`. Renaming the workflow file, the environment or the repository
  stops publishing until the publisher on pypi.org is edited to match.
- **A version can be uploaded once.** PyPI refuses a re-upload even after the release is deleted, so
  a bad release is fixed by bumping again.
- **Every version needs a `CHANGELOG.md` section, and the heading is load-bearing.** It must be
  exactly `## [x.y.z]` (no date after it), newest first, with a
  `[x.y.z]: https://github.com/oskar-j/visualize-my-expenses/releases/tag/vx.y.z` line at the
  bottom. `tests/test_changelog.py` enforces all three. The section becomes the GitHub Release notes
  verbatim, so write it for users. The style follows the author's walsh-hadamard-transform project:
  Keep a Changelog groups (`Added`, `Changed`, `Fixed`, `Removed`, `Notes`), an optional lead
  paragraph, and bullets that open with a bold sentence saying what changed, then why.

## Conventions

- Python 3.9 is supported, so `typing.Optional`/`Dict`/`List` stay; ruff's PEP 604/585 rules are
  disabled in `pyproject.toml` for that reason.
- Errors that a user can act on say what to do (`--rate EUR=4.30`, `pip install "vme-py[excel]"`).
  Loader errors name the file and line.
- Palettes are validated for colour-blind separation and contrast against their own surface, and
  every node carries a visible label — no reading of the chart depends on distinguishing two hues.
  Do not add a ninth categorical colour; past slot 8 things fold into a grey "Other".
