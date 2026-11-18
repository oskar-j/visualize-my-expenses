"""Categorisation rules: give the payees of a bank statement budget categories.

A rules file is a list of rules, tried top to bottom; the first one that
matches a row decides it::

    match,category,label
    lidl,Groceries,Lidl
    orlen|shell|bp,Transport,Fuel
    re:^netflix,Subscriptions,Netflix
    transfer to savings,skip,

* ``match`` is looked for in the row's label (its payee or description) and its
  note -- never its category, where a short pattern such as ``car`` would catch
  every "Card payments" row. Case, accents and runs of spaces do not matter.
  ``|`` separates alternatives; ``re:`` starts a regular expression.
* ``category`` replaces the row's category, and ``skip`` drops the row: a
  transfer between your own accounts, say. A rule with no category yet does
  nothing, which is what ``vme uncategorized --write`` relies on.
* ``label``, when given, replaces the label, so "LIDL SP. Z O.O. 1234" and
  "LIDL SP. Z O.O. 5678" both become "Lidl".

Rules run before anything else decides about a row, so a row they rename to
"Salary" is read as income by the ``expenses`` sign convention too.
"""

from __future__ import annotations

import csv
import io as _io
import json
import os
import re
import string
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Pattern,
    Sequence,
    Set,
    Tuple,
)

from .currencies import format_money
from .models import INCOME, Expense

__all__ = ["COLUMNS", "SKIP", "Categorised", "Rule", "RuleReport", "Rules", "RulesError",
           "Suggestion", "fold", "load_rules", "suggest", "write_rules"]

#: The category that drops a row instead of naming one.
SKIP = "skip"

#: The columns of a rules file. ``comment`` is for people and is ignored.
COLUMNS = ("match", "category", "label", "comment")

#: Letters that Unicode does not split into a base letter and an accent.
_LETTERS = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O",
                          "ħ": "h", "Ħ": "H", "ı": "i", "ß": "ss", "æ": "ae", "Æ": "AE",
                          "œ": "oe", "Œ": "OE"})


class RulesError(ValueError):
    """A rule vme cannot use. The message names the file and line."""


def fold(text: Any) -> str:
    """Text the way rules compare it: accents off, runs of spaces as one.

    ``"Żabka  Polska"`` -> ``"Zabka Polska"``. Case is kept; matching ignores it.
    """
    decomposed = unicodedata.normalize("NFKD", str(text or "").translate(_LETTERS))
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain.split())


def _haystack(row: Expense) -> str:
    """Where a rule looks: the label and the note, on separate lines."""
    return f"{fold(row.label)}\n{fold(row.note)}"


def _compile(match: str, where: str) -> Pattern[str]:
    if match[:3].lower() == "re:":
        expression = fold(match[3:])
        if not expression:
            raise RulesError(f"{where}: {match!r} has no expression after re:")
        try:
            return re.compile(expression, re.IGNORECASE)
        except re.error as exc:
            raise RulesError(
                f"{where}: {match[3:]!r} is not a regular expression vme can read: {exc}"
            ) from exc
    alternatives = [part for part in (fold(part) for part in match.split("|")) if part]
    if not alternatives:
        raise RulesError(f"{where}: {match!r} has nothing to look for")
    return re.compile("|".join(re.escape(part) for part in alternatives), re.IGNORECASE)


@dataclass(frozen=True)
class Rule:
    """One line of a rules file: rows whose label or note has ``match`` get
    ``category`` and, when given, ``label``."""

    match: str
    category: str = ""
    label: str = ""
    #: Where the rule came from, for messages: ``"rules.csv line 4"``.
    where: str = ""
    pattern: Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        match = str(self.match or "").strip()
        where = self.where or (f"rule {match!r}" if match else "rule")
        if not match:
            raise RulesError(f"{where}: the match is empty")
        object.__setattr__(self, "match", match)
        object.__setattr__(self, "category", str(self.category or "").strip())
        object.__setattr__(self, "label", str(self.label or "").strip())
        object.__setattr__(self, "where", where)
        object.__setattr__(self, "pattern", _compile(match, where))

    @property
    def skips(self) -> bool:
        """A rule that drops the rows it matches."""
        return self.category.casefold() == SKIP

    @property
    def complete(self) -> bool:
        """False until the rule has a category: until then it does nothing."""
        return bool(self.category)

    def matches(self, row: Expense) -> bool:
        return self.pattern.search(_haystack(row)) is not None

    def apply(self, row: Expense) -> Expense:
        """``row`` with this rule's category, and its label if it has one."""
        return row.replace(category=self.category, label=self.label or row.label)


class Categorised(NamedTuple):
    """What :meth:`Rules.categorise` made of some rows."""

    #: The rows kept, with the category and label their rule gave them.
    rows: List[Expense]
    #: The rule that decided each kept row, or ``None`` where none matched.
    rules: List[Optional[Rule]]
    #: The rows a ``skip`` rule dropped.
    skipped: List[Expense]
    #: Every rule that matched at least one row.
    used: Set[Rule]


class Rules:
    """Rules in order: the first complete one that matches a row decides it."""

    def __init__(self, rules: Iterable[Rule] = (), source: str = "") -> None:
        self.rules: List[Rule] = list(rules)
        #: The file the rules were read from, if any.
        self.source = source

    def __iter__(self) -> Iterator[Rule]:
        return iter(self.rules)

    def __len__(self) -> int:
        return len(self.rules)

    def __repr__(self) -> str:
        origin = f" from {self.source}" if self.source else ""
        return f"<Rules: {len(self.rules)}{origin}>"

    @property
    def name(self) -> str:
        """How messages refer to these rules: the file name, or "rules"."""
        return self.source or "rules"

    @property
    def incomplete(self) -> List[Rule]:
        """Rules without a category yet: they do nothing until it is filled in."""
        return [rule for rule in self.rules if not rule.complete]

    def rule_for(self, row: Expense) -> Optional[Rule]:
        """The first complete rule that matches ``row``, or ``None``."""
        text = _haystack(row)
        for rule in self.rules:
            if rule.complete and rule.pattern.search(text):
                return rule
        return None

    def categorise(self, rows: Iterable[Expense]) -> Categorised:
        """Apply the rules to ``rows``: recategorise, relabel, drop the skipped."""
        kept: List[Expense] = []
        decided_by: List[Optional[Rule]] = []
        skipped: List[Expense] = []
        used: Set[Rule] = set()
        for row in rows:
            rule = self.rule_for(row)
            if rule is not None:
                used.add(rule)
                if rule.skips:
                    skipped.append(row)
                    continue
                row = rule.apply(row)
            kept.append(row)
            decided_by.append(rule)
        return Categorised(kept, decided_by, skipped, used)


def _count(number: int, word: str) -> str:
    return f"{number} {word}{'' if number == 1 else 's'}"


@dataclass
class RuleReport:
    """What the rules did to the rows that are drawn."""

    rules: Rules
    #: Drawn rows that a rule gave a category.
    categorised: int = 0
    #: Rows a ``skip`` rule dropped (inside the period, if there is one).
    skipped: int = 0
    #: Drawn rows that no rule matched, converted into the report currency.
    unmatched: List[Expense] = field(default_factory=list)
    #: Complete rules that matched no row in any file.
    unused: List[Rule] = field(default_factory=list)

    def summary(self) -> str:
        """``"48 rows categorised, 3 skipped, 9 matched no rule"``."""
        parts = [f"{_count(self.categorised, 'row')} categorised"]
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        parts.append(f"{len(self.unmatched)} matched no rule")
        return ", ".join(parts)


# --------------------------------------------------------------------------- #
# Reading rules
# --------------------------------------------------------------------------- #


def load_rules(source: Any = None) -> Rules:
    """Rules from a CSV or JSON file, or from Python.

    ``source`` is a path, a :class:`Rules`, a mapping ``{match: category}`` (or
    ``{match: (category, label)}``), or a list of :class:`Rule` objects, dicts
    with ``match``, ``category`` and ``label`` keys, or ``(match, category)`` and
    ``(match, category, label)`` tuples. ``None`` means no rules.

    :raises RulesError: for anything vme cannot use, naming the file and line.
    """
    if source is None:
        return Rules()
    if isinstance(source, Rules):
        return source
    if isinstance(source, (str, os.PathLike)):
        return _read_file(os.fspath(source))
    if isinstance(source, Mapping):
        return Rules([_from_value(match, value, f"rule {match!r}")
                      for match, value in source.items()])
    try:
        items = list(source)
    except TypeError:
        raise TypeError("rules must be a path to a rules file, a mapping like "
                        f"{{'lidl': 'Groceries'}} or a list of rules, not "
                        f"{type(source).__name__}") from None
    return Rules([_from_item(item, f"rule {number}") for number, item in enumerate(items, 1)])


def _from_value(match: Any, value: Any, where: str) -> Rule:
    """A rule from a mapping entry: ``"Groceries"``, ``("Groceries", "Lidl")`` or a dict."""
    if value is None or isinstance(value, str):
        return Rule(str(match), value or "", where=where)
    if isinstance(value, Mapping):
        return _from_mapping({**value, "match": match}, where)
    if isinstance(value, (list, tuple)) and 1 <= len(value) <= 2:
        return Rule(str(match), *(str(part or "") for part in value), where=where)
    raise RulesError(f"{where}: expected a category, (category, label) or a dict, "
                     f"not {value!r}")


def _from_item(item: Any, where: str) -> Rule:
    if isinstance(item, Rule):
        return item
    if isinstance(item, Mapping):
        return _from_mapping(item, where)
    if isinstance(item, (list, tuple)) and 1 <= len(item) <= 3:
        return Rule(*(str(part or "") for part in item), where=where)
    raise RulesError(f"{where}: expected a dict, a (match, category, label) tuple "
                     f"or a Rule, not {item!r}")


def _from_mapping(mapping: Mapping[str, Any], where: str) -> Rule:
    keys = {str(key).strip().casefold(): value for key, value in mapping.items()}
    unknown = sorted(key for key in keys if key not in COLUMNS)
    if unknown:
        raise RulesError(f"{where}: unknown key {unknown[0]!r}; a rule has "
                         + ", ".join(COLUMNS[:3]) + " (and comment)")
    return Rule(keys.get("match") or "", keys.get("category") or "",
                keys.get("label") or "", where=where)


def _read_file(path: str) -> Rules:
    from .io.base import LoaderError, read_text

    try:
        text = read_text(path)
    except LoaderError as exc:
        raise RulesError(str(exc)) from exc
    if os.path.splitext(path)[1].lower() == ".json":
        return _read_json(path, text)
    return _read_csv(path, text)


def _read_json(path: str, text: str) -> Rules:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RulesError(f"{path} line {exc.lineno}: not valid JSON: {exc.msg}") from exc
    if isinstance(data, Mapping):
        rules = [_from_value(match, value, f"{path}: rule {match!r}")
                 for match, value in data.items()]
    elif isinstance(data, list):
        rules = [_from_item(item, f"{path}: rule {number}")
                 for number, item in enumerate(data, 1)]
    else:
        raise RulesError(f"{path}: expected a list of rules, or an object mapping "
                         "each match to its category")
    return Rules(rules, source=path)


def _layout(text: str) -> Tuple[str, Optional[List[str]]]:
    """The separator and the column names of a CSV rules file.

    The header names the columns, so whichever of ``,`` ``;`` and tab it holds
    most is the separator -- sturdier than sniffing a handful of short rows.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        delimiter = max(",;\t", key=stripped.count) if any(c in stripped for c in ",;\t") \
            else ","
        header = next(csv.reader([stripped], delimiter=delimiter))
        return delimiter, [name.strip().casefold() for name in header]
    return ",", None


def _read_csv(path: str, text: str) -> Rules:
    delimiter, header = _layout(text)
    if header is None:
        raise RulesError(f"{path} is empty; a rules file starts with the line: "
                         "match,category,label")
    unknown = [name for name in header if name and name not in COLUMNS]
    if "match" not in header or unknown:
        found = f"unknown column {unknown[0]!r}" if unknown else "no match column"
        raise RulesError(f"{path}: {found}; the first line names the columns, "
                         "such as: match,category,label")

    rules: List[Rule] = []
    seen_header = False
    reader = csv.reader(_io.StringIO(text), delimiter=delimiter)
    for cells in reader:
        cells = [cell.strip() for cell in cells]
        if not any(cells) or cells[0].startswith("#"):
            continue
        if not seen_header:
            seen_header = True
            continue
        where = f"{path} line {reader.line_num}"
        if len(cells) > len(header) and any(cells[len(header):]):
            raise RulesError(f"{where}: {len(cells)} values but {len(header)} columns; "
                             "put a value that holds the separator in double quotes")
        values = dict(zip(header, cells, strict=False))
        rules.append(Rule(values.get("match", ""), values.get("category", ""),
                          values.get("label", ""), where=where))
    return Rules(rules, source=path)


# --------------------------------------------------------------------------- #
# Suggesting rules for the rows no rule matched
# --------------------------------------------------------------------------- #


@dataclass
class Suggestion:
    """Rows that no rule matched, grouped under the words that name their payee."""

    #: What a rule's match could say, such as ``"lidl sp. z o.o."``. Empty when the
    #: rows have no description to match.
    match: str
    #: A tidier name to offer in the label column.
    label: str
    rows: List[Expense] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((row.amount for row in self.rows), Decimal("0"))

    @property
    def is_income(self) -> bool:
        return all(row.kind == INCOME for row in self.rows)


def _description(row: Expense) -> str:
    return row.label or row.note


def _pieces(text: str) -> List[str]:
    """Runs of words with no digits in them, split at lone punctuation too.

    ``"CARD PAYMENT 02.09 LIDL SP. Z O.O. 4521"`` -> ``["CARD PAYMENT", "LIDL SP. Z O.O."]``:
    dates, card numbers and branch numbers change from row to row, the payee does not.
    """
    pieces: List[str] = []
    current: List[str] = []
    for word in text.split():
        if any(char.isdigit() for char in word) or not any(char.isalnum() for char in word):
            if current:
                pieces.append(" ".join(current))
                current = []
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _key(text: str) -> str:
    return fold(text).casefold()


def _tidy(piece: str) -> str:
    """``"LIDL SP. Z O.O."`` -> ``"Lidl Sp. Z O.o."``; text not in capitals is kept."""
    return string.capwords(piece.lower()) if piece.isupper() else piece


def suggest(rows: Iterable[Expense],
            among: Optional[Iterable[Expense]] = None) -> List[Suggestion]:
    """Group ``rows`` by payee, biggest total first.

    Each description is cut into runs of words without digits; the run that
    the fewest other descriptions share names the payee. In
    ``"CARD PAYMENT 02.09 LIDL SP. Z O.O. 4521"``, "card payment" is in every
    card row and "lidl sp. z o.o." only in Lidl's. ``among`` is every row
    there is -- the more descriptions vme sees, the better it tells words that
    name a payee from words every row has; it defaults to ``rows``.
    """
    rows = list(rows)
    shared: Counter = Counter()
    descriptions = {_key(_description(row)) for row in (rows if among is None else among)}
    descriptions |= {_key(_description(row)) for row in rows}
    for description in descriptions:
        shared.update({_key(piece) for piece in _pieces(description)})

    groups: Dict[str, Suggestion] = {}
    for row in rows:
        pieces = _pieces(_description(row))
        if pieces:
            # Fewest other descriptions first; then the longer, more specific run.
            piece = min(pieces, key=lambda p: (shared[_key(p)], -len(p)))
            key, match, label = _key(piece), piece.lower(), _tidy(piece)
        else:
            text = " ".join(_description(row).split())
            key, match, label = _key(text), text.lower(), text
        groups.setdefault(key, Suggestion(match, label)).rows.append(row)
    return sorted(groups.values(), key=lambda group: -group.total)  # stable: ties keep order


def write_rules(path: str, suggestions: Sequence[Suggestion], currency: str = "USD") -> int:
    """Add a rule with an empty category to the CSV at ``path`` for each suggestion.

    Creates the file, with a header, if it is missing. A suggestion whose rows a
    rule in the file already matches -- filled in or not -- is left out, so
    running it again adds only new payees. Returns how many rules were added.

    :raises RulesError: when ``path`` is not a CSV rules file vme can add to.
    """
    if os.path.splitext(path)[1].lower() == ".json":
        raise RulesError(f"{path}: rules are added to a CSV file; pick a .csv name")

    exists = os.path.exists(path)
    existing = Rules()
    delimiter, header, ending, text = ",", list(COLUMNS), "\n", ""
    if exists:
        try:
            with open(path, encoding="utf-8-sig", newline="") as handle:
                text = handle.read()
        except UnicodeDecodeError as exc:
            raise RulesError(f"{path} is not UTF-8; save it as UTF-8 (\"CSV UTF-8\" "
                             "in Excel) and run this again") from exc
        except OSError as exc:
            raise RulesError(f"cannot open {path}: {exc}") from exc
        if text.strip():
            existing = _read_csv(path, text)
            delimiter, found = _layout(text)
            header = found or header
            ending = "\r\n" if "\r\n" in text else "\n"

    def covered(suggestion: Suggestion) -> bool:
        return any(rule.matches(row) for rule in existing for row in suggestion.rows)

    new = [s for s in suggestions if s.match and not covered(s)]
    if not new:
        return 0

    buffer = _io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator=ending)
    if not text.strip():
        writer.writerow(header)
    for suggestion in new:
        note = (f"{_count(len(suggestion.rows), 'row')}, "
                f"{'+' if suggestion.is_income else ''}"
                f"{format_money(suggestion.total, currency, 0)}")
        values = {"match": suggestion.match, "category": "", "label": suggestion.label,
                  "comment": note}
        writer.writerow([values.get(name, "") for name in header])

    lead = "" if not text or text.endswith(("\n", "\r")) else ending
    try:
        if text.strip():
            with open(path, "a", encoding="utf-8", newline="") as handle:
                handle.write(lead + buffer.getvalue())
        else:  # a new file: the BOM lets Excel read the accents as UTF-8
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                handle.write(buffer.getvalue())
    except OSError as exc:
        raise RulesError(f"cannot write {path}: {exc.strerror or exc}") from exc
    return len(new)
