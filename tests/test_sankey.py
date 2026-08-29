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
