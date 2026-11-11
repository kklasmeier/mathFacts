import pytest

from mathfacts.specs import SpecError, parse_spec


def test_single_number():
    assert parse_spec("2", 12) == [2]


def test_range_and_list_are_sorted_and_unique():
    assert parse_spec("5, 1-3, 2", 12) == [1, 2, 3, 5]


def test_range_bounds_are_inclusive():
    assert parse_spec("0-3", 12) == [0, 1, 2, 3]


def test_spaces_around_dashes_are_allowed():
    assert parse_spec(" 1 - 4 ", 12) == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "Enter at least one number"),
        ("   ", "Enter at least one number"),
        ("2,,3", "extra comma"),
        ("2,", "extra comma"),
        ("abc", "is not a number or a range"),
        ("1-", "is not a number or a range"),
        ("3-1", "runs backwards"),
    ],
)
def test_bad_specs_explain_the_problem(text, message):
    with pytest.raises(SpecError, match=message):
        parse_spec(text, 12)


def test_values_above_the_limit_are_refused():
    with pytest.raises(SpecError, match="up to 12"):
        parse_spec("1-13", 12)


def test_limit_is_inclusive():
    assert parse_spec("12", 12) == [12]
