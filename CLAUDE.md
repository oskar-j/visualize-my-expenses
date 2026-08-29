# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`visualize-my-expenses` (package `vme`) — a library that turns a list of budget expenses into a
Sankey plot (monthly/yearly). Sankey rendering is the whole point of the project: money flows from
income → categories → labels, so the data model is inherently hierarchical even though the input is
a flat list of rows.

## State: prototype, mostly stubs

This is a pre-alpha skeleton. **Almost every method body is `pass`.** `vme/tools.py` and
`vme/plotting.py` are empty files. Do not assume any behavior described by a method name actually
works — read the body first. Verified current gaps:

- `Visualizer.__init__` calls `super(Calculator, self).__init__()`, which skips `Calculator.__init__`
  (it resolves to the *next* class after `Calculator` in the MRO, i.e. `CalculatorBase`). Result:
  `self.verbose` is never set, and `create_html()` raises `AttributeError` unless a `verbose=` kwarg
  was passed. The intended call is `super().__init__()`.
- `CalculatorBase._verify` returns `None`, so `create_html()` would always fall into the
  `'Data has bad structure'` branch even once `verbose` is fixed.
- `Calculator.set_rows` is the only real logic; `insert_row`, `_prepare`, `run`, `show_plot`,
  `print_to_console` are all no-ops.
- `Calculator.append_rows` reads `self.rows` before it may exist — it only works after `set_rows`.

There are no tests, no packaging config (`setup.py`/`pyproject.toml`), no linter config, and no CI.
If a task needs any of those, they have to be created.

## Commands

```bash
pip install -r requirements.txt   # numpy, pandas, plotly
python usage.py                   # the only entry point / smoke check
```

Run from the repo root — `usage.py` imports `vme` as a top-level package and there is no install step.

## Architecture

Single inheritance chain, one class per layer, each layer adding one responsibility:

```
CalculatorBase (vme/data_store.py)  — validation + console output contract (_verify, print_to_console)
      └── Calculator (vme/data_store.py) — row storage (set_rows / append_rows / insert_row), verbose flag
             └── Visualizer (vme/visualizer.py) — public API: create_html(), show_plot(), run()
```

`vme/__init__.py` re-exports only `Visualizer`; that is the intended public surface. Keep it that way —
callers should never need to import `Calculator` or `CalculatorBase` directly.

The `create_html()` flow is the template the rest should follow: validate via `_verify()` first, raise
on dirty data, and only then generate the plot. "Loose elements" in that error message means Sankey
nodes that do not connect into the flow graph — that is the validation `_verify` is meant to perform.

`vme/plotting.py` (empty) is where plotly Sankey construction belongs, and `vme/tools.py` (empty) is
for shared helpers; the visualizer should delegate to them rather than build figures inline.

## Data model

Rows are duck-typed — nothing validates their shape. The convention comes from `usage.py`:

```python
Expense = namedtuple('Expense', ['category', 'label', 'amount', 'currency'])
```

Each row carries its own `currency`, while `Visualizer(currency=...)` sets the display/target currency
(defaults to `'USD'`). Reconciling the two (conversion, or rejecting mixed currencies) is unimplemented
and is a decision that has not been made yet.

`numpy` and `pandas` are declared dependencies and imported in `data_store.py` but not yet used —
the row store is a plain list.
