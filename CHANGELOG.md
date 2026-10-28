# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The `## [x.y.z]` headings are load-bearing: a version is published only if this
file has a section for it, and that section becomes the GitHub Release notes.
`tests/test_changelog.py` checks it, so a version bump without its section
fails CI before it can be merged.

## [0.2.0]

A choice of look: vme's own, or seaborn's. Also, Python 3.10 is now the oldest
supported version.

### Added

- **`--engine seaborn` draws the chart in seaborn's look**: a seaborn palette
  for the categories, seaborn's fonts, and the type sizes of a seaborn
  context. `--palette` picks the palette (`deep` unless you name another, such
  as `colorblind`, `muted` or `Set2`) and `--context` the size (`paper`,
  `notebook`, `talk` or `poster`; `notebook` unless you say otherwise). From
  Python: `Visualizer(rows, engine="seaborn", palette="colorblind",
  context="talk")`. HTML output takes the same palette and fonts.
- **The `seaborn` extra**: `pip install "vme-py[seaborn]"`, also part of
  `vme-py[all]`. Without it, `--engine seaborn` stops with that install
  command instead of a traceback.
- `vme formats` lists the engines. `vme.plotting.render`, `to_plotly` and
  `write_html` take a `fonts` stack, and the last two a `font_scale`, for
  drawing a graph yourself in a given look.

### Changed

- **Bigger type gets a taller image.** When `--height` is not given, the
  image now grows with the type size (a seaborn context, or `font_scale` from
  Python) as it already did with the number of rows. Before, larger type kept
  the same height and the labels overlapped.
- **`Visualizer` checks its look when it is created.** An unknown theme,
  engine or palette, or `engine="seaborn"` without seaborn installed, now
  raises from `Visualizer(...)` rather than from the first `create_png`.

### Fixed

- **No node loses its whole name.** In a narrow image, or with larger type, a
  name that could not fit beside its value was shortened, sometimes to
  nothing: a category was drawn as just "629 zł 6%". Now, where none of the
  name would be left, the value gives way instead. Charts whose names fit come
  out exactly as before.

### Removed

- **Python 3.9.** It reached its end of life in October 2025. vme now needs
  Python 3.10 or newer; on Python 3.9, pip keeps installing vme 0.1.4.

### Notes

- **Seaborn styles what matplotlib draws**, since seaborn has no Sankey chart
  of its own. That is also why the seaborn extra always installs matplotlib:
  Python packages cannot declare "matplotlib or seaborn", and seaborn needs
  matplotlib anyway.
- **vme checks its own palettes; seaborn's are yours to choose.** vme's
  palettes are checked for colour-blind separation and for contrast against
  their background. A seaborn palette is not, though vme leaves out its grey,
  which vme keeps for "Other", and uses at most 8 colours. The background,
  light or dark, and the colours of income, savings and "Other" stay vme's
  under either engine.

## [0.1.4]

A fix for budgets that already have a category called "Other".

### Fixed

- **A category called "Other" keeps its labels when `--top` or `--min-share`
  folds smaller categories into it** (#7). The folded categories and the real
  "Other" shared one node, but its detail column showed only the folded ones:
  "Other" read 490 zł while passing on 90 zł, and its own labels were missing
  from the chart. The same happened when the real "Other" was small enough to
  be folded itself. Now "Other" is one bucket that lists its own labels first,
  then one row per folded category, and passes on exactly what it holds.
- **That "Other" is grey, its labels too.** The duplicate gave the bar one
  palette colour and its labels another, and used up a palette slot, so the
  categories after it changed colour. A category called "Other" with nothing
  folded into it keeps its palette colour, as before.

## [0.1.3]

Amounts and dates the way bank exports actually write them: a currency
abbreviation no longer shrinks an amount a thousandfold, a time after the date
no longer loses the date, and a date that still cannot be read is reported
instead of disappearing.

### Fixed

- **A currency written with a dot before the amount no longer moves the
  decimal point** (#6). `Rs. 500` and `kr. 500` were read as 0.5, and
  `Rs. 1,500` as 1.5, because the dot of the abbreviation was taken for a
  decimal point. A currency around the number is now dropped whole, dot
  included, while a real leading decimal point (`.50`, `$.50`) still counts.
- **Exponent notation is read as a number** (#6). `1.5E+3`, as spreadsheets
  write large or small values, was read as 1.53; it is now 1500.
- **`1.234.567` is read as 1234567** (#6), with the dots grouping thousands,
  instead of being refused.
- **`500,-` is 500, not −500.** The dash after the comma is the usual way to
  write a whole amount in German, Polish and Scandinavian prices, but it was
  read as a trailing minus. One such row also made `auto` read the whole file
  as a bank statement, turning every other row into income. `120.00-` is still
  negative.
- **A time after the date no longer loses the date** (#10). `15.01.2024 10:23`,
  `01/15/2024 10:23:00 PM` and similar loaded with no date at all, so
  `--month`, `--year` and `--period` left those rows out. `Jan 15, 2024` and
  `January 15, 2024` are read now too.

### Added

- **A note for every date that cannot be read** (#10). Such a row still loads,
  undated, but the CLI now says so on every command that reads a file, naming
  the file and line: `note: bank.csv:5: cannot read the date 'pending' ...`.
  From Python it is a `vme.io.LoaderWarning`. A blank date cell is not
  reported.

## [0.1.2]

Two fixes for charts that came out wrong without any error: expenses drawn as
income, and dates in one file read in two different orders. Also two smaller
fixes, contributed in #15: OFX names written with `&amp;`, and a traceback
when the output folder does not exist.

### Fixed

- **A bank statement no longer turns expenses into income because of their
  names** (#4). A payment labelled "Income tax" or "Water & sewage" (which
  contains "wage") was drawn as income, and so was a row whose type column said
  "Credit Card". In a statement, where amounts carry a sign, the sign now
  decides on its own. In a plain list of positive amounts, a row still counts
  as income when its category or label names income ("Income", "Salary",
  "Wages", "Payroll", "Bonus"), but only as a whole word and not when the same
  text names a cost, so "Income tax" stays spending. The category is read
  before the label: category "Income" with label "Tax refund" is income.
- **A type or direction column with several words no longer decides the
  direction by its first letters** (#4). "Credit Card" and "Debit Card" say
  how a purchase was paid, not which way the money went, so the amount's sign
  decides. One-word values ("Credit", "DBIT", "Credited") and phrases with an
  unmistakable direction ("Incoming transfer", "Outgoing transfer") work as
  before.
- **Dates are read in one order for the whole file** (#5). Without
  `--dayfirst` or `--monthfirst`, each date was read on its own, so a US
  statement had 01/02 to 01/12 read as 1 February to 1 December while 01/13
  onwards stayed in January, and `--month` quietly dropped those rows. Now a
  single date that can only be read one way (13/01 or 01/13) settles the
  order for every row in a CSV, JSON, JSON Lines, Excel or QIF file. A file
  with dates written both ways stops with an error asking for `--dayfirst` or
  `--monthfirst` instead of being guessed at.
- **OFX names and memos show `&`, `<` and `>` as written** (#12, #15). OFX
  escapes them, and the loader kept the escaped form, so a chart read
  `H&amp;M` instead of `H&M`.
- **`vme render` reports an output folder that does not exist** (#13, #15)
  with an `error: cannot write ...` line, instead of a Python traceback.

### Added

- **`--dayfirst/--monthfirst` on `vme summary` and `vme check`**, so the flag
  that the new date error asks for exists on every command that reads a file.

### Changed

- **In the Python API, rows read with no direction stay `AUTO` until
  `apply_sign_convention`.** `coerce_row` used to mark a row that looked like
  income as income straight away. It now leaves that call to the sign
  convention, which is the step that knows whether the file is signed.
  `Visualizer` users see no difference.
- **`coerce_rows` works out the date order across all the rows it is given**,
  as the loaders do, and raises `ValueError` when they disagree.

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

[0.2.0]: https://github.com/oskar-j/visualize-my-expenses/releases/tag/v0.2.0
[0.1.4]: https://github.com/oskar-j/visualize-my-expenses/releases/tag/v0.1.4
[0.1.3]: https://github.com/oskar-j/visualize-my-expenses/releases/tag/v0.1.3
[0.1.2]: https://github.com/oskar-j/visualize-my-expenses/releases/tag/v0.1.2
[0.1.1]: https://github.com/oskar-j/visualize-my-expenses/releases/tag/v0.1.1
[0.1.0]: https://github.com/oskar-j/visualize-my-expenses/releases/tag/v0.1.0
