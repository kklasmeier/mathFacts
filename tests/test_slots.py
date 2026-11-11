import random
from collections import Counter

import pytest

from mathfacts.pools import Problem, build_pool
from mathfacts.slots import ORDERS, arrange, neighbours
from mathfacts.specs import parse_spec


def facts_for(op, a, b, **options):
    return build_pool(op, parse_spec(a, 20), parse_spec(b, 20), **options).facts


def clashes(cells, rows, cols):
    """Return the indexes of cells that share a side with an identical fact."""
    bad = []
    for i, fact in enumerate(cells):
        if any(cells[j] == fact for j in neighbours(i, rows, cols)):
            bad.append(i)
    return bad


# --- Pool rules (spec 5.1) -------------------------------------------------

def test_reverse_order_adds_the_other_way_round():
    facts = build_pool("mul", [2], [3, 4], include_reverse=True).facts
    assert {(p.a, p.b) for p in facts} == {(2, 3), (3, 2), (2, 4), (4, 2)}


def test_reverse_order_does_not_duplicate_equal_facts():
    facts = build_pool("add", [3], [3], include_reverse=True).facts
    assert [(p.a, p.b) for p in facts] == [(3, 3)]


def test_subtraction_drops_negatives_unless_allowed():
    dropped = build_pool("sub", [2], [5])
    assert dropped.facts == [] and dropped.dropped_negative == 1
    kept = build_pool("sub", [2], [5], allow_negatives=True)
    assert [(p.a, p.b) for p in kept.facts] == [(2, 5)]


def test_division_drops_zero_divisors_and_keeps_the_rest():
    pool = build_pool("div", [0, 2], [3])
    assert pool.dropped_zero == 1
    assert pool.facts == [Problem("div", 2, 3)]
    assert pool.facts[0].dividend == 6
    assert pool.facts[0].answer == 3


def test_pool_is_sorted_a_then_b():
    facts = facts_for("add", "3,1", "2")
    assert [(p.a, p.b) for p in facts] == [(1, 2), (3, 2)]


# --- Repeats and counts ----------------------------------------------------

def test_eleven_facts_on_ten_by_ten_repeat_nine_or_ten_times():
    facts = facts_for("mul", "0-10", "2")
    assert len(facts) == 11
    for order in ("sequential", "shuffled", "random"):
        arr = arrange(facts, 10, 10, order, random.Random(7))
        counts = Counter(arr.cells)
        assert len(arr.cells) == 100
        assert set(counts) == set(facts)
        assert min(counts.values()) >= 9 and max(counts.values()) <= 10, order


def test_repeats_flag_is_set_when_pool_is_smaller_than_page():
    facts = facts_for("mul", "1-3", "2")
    assert arrange(facts, 5, 5, "shuffled", random.Random(1)).repeats is True
    assert arrange(facts, 1, 2, "shuffled", random.Random(1)).repeats is False


def test_one_fact_on_the_page_is_flagged_all_same():
    facts = facts_for("add", "3", "3")
    arr = arrange(facts, 4, 5, "shuffled", random.Random(3))
    assert arr.all_same is True
    assert set(arr.cells) == set(facts)


# --- No shared sides (spec 5.1 slot filler) --------------------------------

CASES = [
    # (label, op, a, b, rows, cols)
    ("1x1", "add", "2", "2", 1, 1),
    ("1x20 column", "mul", "1-9", "2", 20, 1),
    ("2x2 two facts", "mul", "2", "3,4", 2, 2),
    ("3 facts 2x2", "add", "1-3", "2", 2, 2),
    ("10x20 two facts", "mul", "2", "3,4", 20, 10),
    ("10x20 eleven facts", "mul", "0-10", "2", 20, 10),
    ("10x10 eleven facts", "mul", "0-10", "2", 10, 10),
    ("12x12 full table", "mul", "1-12", "1-12", 12, 12),
    ("10x20 full table", "mul", "1-12", "1-12", 20, 10),
    ("8x5 nine facts", "mul", "1-9", "2", 5, 8),
]


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("label, op, a, b, rows, cols", CASES)
def test_no_two_neighbours_share_a_fact(label, op, a, b, rows, cols, order):
    facts = facts_for(op, a, b)
    for seed in range(8):
        arr = arrange(facts, rows, cols, order, random.Random(seed))
        assert arr.separated, f"{label} {order} seed {seed}"
        assert clashes(arr.cells, rows, cols) == [], f"{label} {order} seed {seed}"


def test_same_seed_gives_the_same_page():
    facts = facts_for("mul", "1-12", "1-12")
    first = arrange(facts, 10, 10, "shuffled", random.Random(99)).cells
    second = arrange(facts, 10, 10, "shuffled", random.Random(99)).cells
    assert first == second


def test_different_seeds_give_different_pages():
    facts = facts_for("mul", "1-12", "1-12")
    first = arrange(facts, 10, 10, "shuffled", random.Random(1)).cells
    second = arrange(facts, 10, 10, "shuffled", random.Random(2)).cells
    assert first != second


def test_sequential_order_is_unchanged_by_the_seed_when_nothing_clashes():
    # 9 facts on 5 across: no cell shares a side with the same fact, so the
    # cyclic A-then-B order is kept for every seed (regenerate does not change it).
    facts = facts_for("mul", "1-9", "2")
    orders = {
        tuple(arrange(facts, 8, 5, "sequential", random.Random(seed)).cells)
        for seed in range(5)
    }
    assert len(orders) == 1


def test_neighbours_are_side_adjacent_only():
    assert sorted(neighbours(0, 3, 3)) == [1, 3]
    assert sorted(neighbours(4, 3, 3)) == [1, 3, 5, 7]
    assert neighbours(0, 1, 1) == []
