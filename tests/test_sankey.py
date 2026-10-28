"""Turning rows into the Sankey graph, and laying that graph out."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vme.data_store import apply_sign_convention
from vme.models import AUTO, EXPENSE, INCOME, Expense
from vme.plotting import layout_graph
from vme.sankey import GraphOptions, build_graph
from vme.theme import get_theme


def spend(category, label, amount):
    return Expense(category=category, label=label, amount=Decimal(str(amount)),
                   currency="PLN", kind=EXPENSE)


def earn(label, amount):
    return Expense(category="Income", label=label, amount=Decimal(str(amount)),
                   currency="PLN", kind=INCOME)


class TestBuildGraph:
    def test_shape_with_income(self, rows):
        graph = build_graph(rows, currency="PLN")
        assert graph.depths == [0, 1, 2, 3]      # income, hub, categories, labels
        assert graph.node("hub").label == "Budget"
        assert {n.label for n in graph.nodes_at(0)} == {"Salary", "Freelance"}
        assert "Housing" in {n.label for n in graph.nodes_at(2)}

    def test_shape_without_income(self):
        graph = build_graph([spend("Food", "Lidl", 100), spend("Fuel", "Shell", 50)],
                            currency="PLN")
        assert graph.depths == [0, 1, 2]
        assert graph.node("hub").label == "Total spent"

    def test_totals_add_up(self, rows):
        graph = build_graph(rows, currency="PLN")
        assert graph.node("hub").value == Decimal("7000")
        assert graph.node("cat:Housing").value == Decimal("2200")

    def test_savings_branch(self, rows):
        graph = build_graph(rows, currency="PLN")
        assert graph.node("savings").value == Decimal("3500")

    def test_a_deficit_is_funded_from_savings(self):
        rows = [earn("Salary", 1000), spend("Rent", "Rent", 1500)]
        graph = build_graph(rows, currency="PLN")
        assert graph.node("in:deficit").value == Decimal("500")
        assert graph.node("savings") is None
        assert graph.node("hub").value == Decimal("1500")

    def test_savings_can_be_turned_off(self, rows):
        graph = build_graph(rows, currency="PLN",
                            options=GraphOptions(show_savings=False))
        assert graph.node("savings") is None

    def test_detail_column_can_be_dropped(self, rows):
        graph = build_graph(rows, currency="PLN", options=GraphOptions(detail=False))
        assert graph.depths == [0, 1, 2]

    def test_a_label_equal_to_its_category_adds_no_column(self):
        graph = build_graph([spend("Rent", "Rent", 100)], currency="PLN")
        assert graph.node("leaf:Rent/Rent") is None

    def test_top_categories_folds_the_rest(self):
        rows = [spend(f"Cat{i}", f"L{i}", 100 - i) for i in range(6)]
        graph = build_graph(rows, currency="PLN",
                            options=GraphOptions(top_categories=3, detail=False))
        labels = {n.label for n in graph.nodes_at(1)}
        assert "Other" in labels and len(labels) == 4

    def test_folding_conserves_the_total(self):
        rows = [spend(f"Cat{i}", f"L{i}", 100 - i) for i in range(6)]
        graph = build_graph(rows, currency="PLN",
                            options=GraphOptions(top_categories=3, detail=False))
        assert sum(n.value for n in graph.nodes_at(1)) == sum(r.amount for r in rows)

    def test_min_share_folds_small_categories(self):
        rows = [spend("Big", "a", 1000), spend("Tiny", "b", 5)]
        graph = build_graph(rows, currency="PLN",
                            options=GraphOptions(min_share=5, detail=False))
        assert {n.label for n in graph.nodes_at(1)} == {"Big", "Other"}

    def test_max_labels_folds_within_a_category(self):
        rows = [spend("Food", f"Shop {i}", 10 + i) for i in range(8)]
        graph = build_graph(rows, currency="PLN", options=GraphOptions(max_labels=3))
        leaves = graph.nodes_at(2)
        assert len(leaves) == 4 and "Other" in {n.label for n in leaves}

    def test_categories_keep_their_palette_slot(self, rows):
        theme = get_theme("light")
        graph = build_graph(rows, currency="PLN", theme=theme)
        housing = graph.node("cat:Housing")
        assert housing.color == theme.categorical[0]      # biggest category, slot 1

    def test_a_leaf_inherits_its_category_colour(self, rows):
        graph = build_graph(rows, currency="PLN")
        assert graph.node("leaf:Housing/Rent").color == graph.node("cat:Housing").color

    def test_income_can_be_grouped(self, rows):
        graph = build_graph(rows, currency="PLN", options=GraphOptions(group_income=True))
        assert {n.label for n in graph.nodes_at(0)} == {"Income"}

    def test_no_loose_nodes(self, rows):
        assert build_graph(rows, currency="PLN").loose_nodes() == []

    def test_empty_rows_make_an_empty_graph(self):
        assert not build_graph([], currency="PLN")


def with_own_other(gifts=300, misc=100):
    """Issue #7: the data has its own "Other" next to categories small enough to fold."""
    return [spend("Housing", "Rent", 1000), spend("Food", "Lidl", 500),
            spend("Other", "Gifts", gifts), spend("Other", "Misc", misc),
            spend("Fun", "Cinema", 50), spend("Pets", "Vet", 40)]


def outflow(graph, key):
    return sum((link.value for link in graph.links if link.source == key), Decimal("0"))


class TestACategoryCalledOther:
    def test_it_takes_in_the_folded_categories_and_keeps_its_labels(self):
        graph = build_graph(with_own_other(), currency="PLN",
                            options=GraphOptions(top_categories=3))
        other = graph.node("cat:Other")
        assert other.value == Decimal("490")
        assert outflow(graph, "cat:Other") == Decimal("490")
        leaves = {n.label: n.value for n in graph.nodes_at(2) if n.key.startswith("leaf:Other/")}
        assert leaves == {"Gifts": 300, "Misc": 100, "Fun": 50, "Pets": 40}

    def test_one_small_enough_to_fold_keeps_its_labels_too(self):
        graph = build_graph(with_own_other(gifts=30, misc=10), currency="PLN",
                            options=GraphOptions(top_categories=2))
        assert graph.node("cat:Other").value == Decimal("130")
        assert outflow(graph, "cat:Other") == Decimal("130")
        assert graph.node("leaf:Other/Gifts").value == Decimal("30")

    def test_there_is_only_one_other_node(self):
        graph = build_graph(with_own_other(), currency="PLN",
                            options=GraphOptions(top_categories=3))
        assert [n.label for n in graph.nodes_at(1)].count("Other") == 1

    def test_holding_folded_categories_makes_it_grey_down_to_its_labels(self):
        theme = get_theme("light")
        graph = build_graph(with_own_other(), currency="PLN", theme=theme,
                            options=GraphOptions(top_categories=3))
        assert graph.node("cat:Other").color == theme.other
        assert {n.color for n in graph.nodes if n.key.startswith("leaf:Other/")} == {theme.other}

    def test_the_bucket_does_not_use_up_a_palette_slot(self):
        theme = get_theme("light")
        rows = [spend("Housing", "Rent", 1000), spend("Other", "Gifts", 300),
                spend("Food", "Lidl", 200), spend("Fun", "Cinema", 50)]
        graph = build_graph(rows, currency="PLN", theme=theme,
                            options=GraphOptions(top_categories=3))
        assert graph.node("cat:Food").color == theme.categorical[1]

    def test_with_nothing_folded_it_is_an_ordinary_category(self):
        theme = get_theme("light")
        graph = build_graph(with_own_other(), currency="PLN", theme=theme)
        other = graph.node("cat:Other")
        assert other.value == Decimal("400") and other.color in theme.categorical
        assert graph.node("leaf:Other/Fun") is None

    def test_a_label_called_other_merges_with_the_folded_labels(self):
        rows = [spend("Food", "Other", 5)] + [spend("Food", f"Shop {i}", 10 + i)
                                              for i in range(6)]
        graph = build_graph(rows, currency="PLN", options=GraphOptions(max_labels=3))
        others = [n for n in graph.nodes_at(2) if n.label == "Other"]
        assert len(others) == 1 and outflow(graph, "cat:Food") == graph.node("cat:Food").value

    @pytest.mark.parametrize("options", [
        dict(), dict(top_categories=1), dict(top_categories=2), dict(top_categories=3),
        dict(min_share=5), dict(min_share=20), dict(top_categories=3, max_labels=1),
    ])
    def test_every_category_passes_on_exactly_what_it_holds(self, options):
        rows = with_own_other() + [spend("Food", f"Shop {i}", 5) for i in range(8)]
        graph = build_graph(rows, currency="PLN", options=GraphOptions(**options))
        categories = graph.nodes_at(1)
        assert sum(n.value for n in categories) == sum(r.amount for r in rows)
        for node in categories:
            sent = outflow(graph, node.key)
            assert sent in (0, node.value), node.key   # 0: no detail column of its own


class TestLayout:
    def test_every_node_is_placed(self, rows):
        graph = build_graph(rows, currency="PLN")
        layout = layout_graph(graph)
        assert len(layout.placements) == len(graph.nodes)

    def test_columns_do_not_overflow_the_span(self, rows):
        layout = layout_graph(build_graph(rows, currency="PLN"))
        for depth in layout.columns:
            bottom = max(p.bottom for p in layout.column(depth))
            assert bottom <= layout.span + 1e-6

    def test_nodes_in_a_column_never_overlap(self, rows):
        layout = layout_graph(build_graph(rows, currency="PLN"))
        for depth in layout.columns:
            stack = layout.column(depth)
            for upper, lower in zip(stack, stack[1:]):
                assert upper.bottom <= lower.top + 1e-9

    def test_ribbons_match_their_links(self, rows):
        graph = build_graph(rows, currency="PLN")
        layout = layout_graph(graph)
        assert len(layout.ribbons) == len(graph.links)
        for ribbon in layout.ribbons:
            assert ribbon.height == pytest.approx(ribbon.link.float_value)

    def test_a_ribbon_stays_inside_both_of_its_nodes(self, rows):
        layout = layout_graph(build_graph(rows, currency="PLN"))
        for ribbon in layout.ribbons:
            source = layout.placements[ribbon.link.source]
            target = layout.placements[ribbon.link.target]
            assert source.top - 1e-6 <= ribbon.source_top
            assert ribbon.source_top + ribbon.height <= source.bottom + 1e-6
            assert target.top - 1e-6 <= ribbon.target_top
            assert ribbon.target_top + ribbon.height <= target.bottom + 1e-6

    def test_an_explicit_gap_is_used(self, rows):
        graph = build_graph(rows, currency="PLN")
        tight = layout_graph(graph, gap_fraction=0.0)
        loose = layout_graph(graph, gap=tight.span * 0.05)
        assert loose.span > tight.span

    def test_savings_sinks_to_the_bottom(self, rows):
        layout = layout_graph(build_graph(rows, currency="PLN"))
        column = layout.column(2)
        assert column[-1].node.kind == "savings"


def test_sign_convention_then_graph_round_trip():
    # AUTO is what a loader emits when the file did not state a direction
    raw = [Expense(category="Income", label="Pay", amount=Decimal("1000"),
                   currency="PLN", kind=AUTO),
           Expense(category="Food", label="Lidl", amount=Decimal("-120"),
                   currency="PLN", kind=AUTO)]
    graph = build_graph(apply_sign_convention(raw), currency="PLN")
    assert graph.node("hub").value == Decimal("1000")
    assert graph.node("cat:Food").value == Decimal("120")


def test_a_directly_built_expense_defaults_to_spending():
    # the library is for expenses; income has to say so
    assert Expense(category="Income", label="Pay", amount=Decimal("1")).is_expense
