import pytest

from mathfacts.fit import (
    FLOOR_PT,
    MAX_PT,
    MIN_PT,
    PAGE_IN,
    _measure,
    fit_sheet,
    largest_legible,
    suggest_landscape,
)
from mathfacts.pools import build_pool
from mathfacts.specs import parse_spec


def facts(a, b, op="mul"):
    return build_pool(op, parse_spec(a, 20), parse_spec(b, 20)).facts


TABLE = facts("1-12", "1-12")  # 144 facts, the hardest common case
SMALL = facts("1-9", "2")  # 9 short facts


def test_more_columns_never_make_type_bigger():
    sizes = [
        fit_sheet(TABLE, "vertical", "portrait", cols, 8).font_pt for cols in range(1, 11)
    ]
    assert sizes == sorted(sizes, reverse=True)


def test_more_rows_never_make_type_bigger():
    sizes = [
        fit_sheet(TABLE, "vertical", "portrait", 5, rows).font_pt for rows in range(1, 21)
    ]
    assert sizes == sorted(sizes, reverse=True)


def test_font_stays_between_the_floor_and_the_maximum():
    for cols in (1, 3, 10):
        for rows in (1, 8, 20):
            for layout in ("vertical", "horizontal"):
                fit = fit_sheet(SMALL, layout, "landscape", cols, rows)
                assert FLOOR_PT <= fit.font_pt <= MAX_PT


def test_crowded_page_uses_the_fitted_size_below_10pt():
    # A dense page is allowed. The type gets smaller instead of being held at 10pt.
    for layout in ("vertical", "horizontal"):
        fit = fit_sheet(TABLE, layout, "portrait", 10, 20)
        assert fit.legible is False
        assert fit.tight is False
        assert fit.fits is True
        assert FLOOR_PT <= fit.font_pt < MIN_PT


def test_every_allowed_layout_fits_the_page():
    # Spec 5.2.1: the printed sheet fits one Letter page for any allowed size.
    for layout in ("vertical", "horizontal"):
        for page in ("portrait", "landscape"):
            for spacing in ("roomy", "normal", "compact"):
                for cols in range(1, 11):
                    for rows in range(1, 21):
                        fit = fit_sheet(TABLE, layout, page, cols, rows, spacing)
                        assert fit.fits, (layout, page, spacing, cols, rows)


def test_spacing_orders_the_font_sizes():
    roomy = fit_sheet(SMALL, "horizontal", "portrait", 4, 6, "roomy").font_pt
    normal = fit_sheet(SMALL, "horizontal", "portrait", 4, 6, "normal").font_pt
    compact = fit_sheet(SMALL, "horizontal", "portrait", 4, 6, "compact").font_pt
    assert roomy <= normal <= compact


def test_compact_never_overflows_a_legible_cell():
    for page in ("portrait", "landscape"):
        page_w, page_h = PAGE_IN[page]
        for layout in ("vertical", "horizontal"):
            width_em, _tall_em, compact_em = _measure(TABLE, layout)
            for cols in range(1, 11):
                for rows in range(1, 21):
                    fit = fit_sheet(TABLE, layout, page, cols, rows, "compact")
                    if not fit.legible:
                        continue
                    # Use exact cell sizes here, not the rounded values on Fit.
                    cell_w = page_w / cols
                    cell_h = (page_h - 0.85 - 0.3) / rows
                    assert fit.font_pt * width_em <= cell_w * 72 + 1e-6
                    assert fit.font_pt * compact_em <= cell_h * 72 + 1e-6


def test_ten_by_twenty_vertical_twelve_table_prints_smaller_than_10pt():
    fit = fit_sheet(TABLE, "vertical", "portrait", 10, 20)
    assert fit.legible is False
    assert fit.fits is True
    assert fit.font_pt < MIN_PT


def test_small_pages_of_short_facts_fit_comfortably():
    fit = fit_sheet(SMALL, "horizontal", "portrait", 2, 4)
    assert fit.legible is True
    assert fit.font_pt >= 14


def test_largest_legible_layout_is_itself_legible():
    best = largest_legible(TABLE, "vertical", "portrait")
    assert best is not None
    cols, rows = best
    assert fit_sheet(TABLE, "vertical", "portrait", cols, rows).legible


def test_cells_are_reported_in_inches():
    fit = fit_sheet(SMALL, "horizontal", "portrait", 5, 8)
    page_w, page_h = PAGE_IN["portrait"]
    assert fit.cell_w_in == round(page_w / 5, 3)
    # Content height, minus title, name/date line and footer, split across 8 rows.
    assert fit.cell_h_in == pytest.approx((page_h - 0.55 - 0.3 - 0.3) / 8, abs=0.001)


def test_landscape_is_suggested_when_it_is_clearly_better():
    # Wide horizontal problems on 8 columns: landscape gives each cell more width.
    portrait = fit_sheet(TABLE, "horizontal", "portrait", 8, 2)
    assert portrait.font_pt < 14
    assert suggest_landscape(TABLE, "horizontal", 8, 2, "normal", True, True, portrait) is True


def test_landscape_is_not_suggested_when_portrait_is_already_big():
    portrait = fit_sheet(SMALL, "horizontal", "portrait", 2, 4)
    assert suggest_landscape(SMALL, "horizontal", 2, 4, "normal", True, True, portrait) is False
