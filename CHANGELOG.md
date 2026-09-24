# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The `## [x.y.z]` headings are load-bearing: a version is published only if this
file has a section for it, and that section becomes the GitHub Release notes.
`tests/test_changelog.py` checks it, so a version bump without its section
fails CI before it can be merged.

## [0.1.1]

The changelog release: from this version on, every release says what changed,
and CI will not publish one that does not.

### Added

- **`CHANGELOG.md`**, this file, with an entry for every release since 0.1.0.
- **A version bump now needs its changelog section.** `tests/test_changelog.py`
  fails when the version in `pyproject.toml` has no `## [x.y.z]` section here,
  when a section has no link to its GitHub Release at the bottom of the file,
  or when the sections are not newest first. It runs in every test job, and the
  PyPI upload waits for every test job, so nothing is published undocumented.
- **A preview of the release notes.** On a pull request that bumps the version,
  the `version check` job puts the section that will become the GitHub Release
  notes into the run summary.

### Changed

- **GitHub Release notes come from this file** rather than from GitHub's
  generated list of merged pull requests.
- The `Changelog` link on PyPI points to this file rather than to the GitHub
  Releases page.
- The sdist includes `CHANGELOG.md`, which its own test suite now reads.

## [0.1.0]

The first release on PyPI, as [`vme-py`](https://pypi.org/project/vme-py/0.1.0/):
the proof of concept (#1) and the packaging and release automation around it
(#2).

### Added

- **`vme`, a command line with six commands.** `render` draws the Sankey
  diagram, `summary` prints the same breakdown as a table, `check` reports
  anything that would stop a file being plotted, `formats` and `currencies`
  list what is supported, and `sample` writes an example file to start from.
- **Seven input formats**, guessed from the file name: CSV/TSV, JSON, JSON
  Lines, OFX/QFX, QIF, ISO 20022 camt.052/053/054 and Excel (the `excel`
  extra). Column names are matched loosely, so most bank exports load
  untouched, and amounts written as `1,234.56`, `1.234,56`, `1 234,56`,
  `(12.00)` or `120.00-` all parse.
- **Several currencies in one file.** Each row carries its own currency, and
  the chart is drawn in one of them at rates the caller gives: `--rate
  EUR=4.30`, or a JSON or CSV file passed with `--rates`. Rates are never
  fetched from the network, so the same input always draws the same picture.
  48 currencies know their own symbol, decimal places and separators.
- **A chart that always balances.** Money flows from income through the
  budget to categories and the labels inside them; what was not spent leaves
  as "Savings / left over", and spending beyond income arrives from a "From
  savings" node.
- **Output as PNG, SVG, PDF, JPEG, WebP or EPS** through matplotlib, and as an
  interactive HTML page through plotly (the `html` extra).
- **Light and dark themes**, with palettes checked for colour-blind separation
  and for contrast against their own background. Every node carries a visible
  label, so no reading of the chart depends on telling two colours apart.
- **Filters and folding**: one month, year or date range; the biggest N
  categories; a minimum share of the total; a cap on the detail rows shown
  inside one category. Whatever is cut is folded into "Other".
- **A Python API** around `vme.Visualizer`, which reads any supported file, or
  rows built in code as dicts, dataclasses, namedtuples or `vme.Expense`.
- **Installation with pip or uv** on Python 3.9 to 3.14, with `excel`, `html`
  and `all` extras, and a committed `uv.lock` for development.
- **CI on every pull request**: ruff, the tests on Linux (Python 3.9 to 3.14),
  macOS and Windows, and a build whose wheel is installed with plain pip and
  run. A merge to `master` with a new version publishes it to PyPI through
  Trusted Publishing, then tags it and creates a GitHub Release.

### Notes

- The distribution is called `vme-py` because `vme` is taken on PyPI; the
  import package and the command are both `vme`.
- Rows in a currency with no rate are refused rather than guessed at: the
  error names each missing currency and the flag that supplies its rate.

[0.1.1]: https://github.com/oskar-j/visualize-my-expenses/releases/tag/v0.1.1
[0.1.0]: https://github.com/oskar-j/visualize-my-expenses/releases/tag/v0.1.0
