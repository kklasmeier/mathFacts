"""Auto-fit layout (spec 5.2.1).

The same function runs for the live preview, the saved sheet, and the print
page, so they always agree. Sizes are in inches and points. Text is measured in
em (1 em = the font size), using rough character widths. The print stylesheet
then sizes the grid from the computed font size.
"""

import math
from dataclasses import dataclass

from .pools import SYMBOL

# US Letter with a tight page margin, then a small inset inside the sheet so the
# problems are not flush with the paper edge. PAGE_IN is the area inside that inset
# (portrait width × height). The sheet box itself is OUTER_IN. Keep these in step
# with sheet.css and the print stylesheets.
PAGE_MARGIN_IN = 0.3
SHEET_PAD_IN = 0.15
OUTER_IN = {"portrait": (7.9, 10.4), "landscape": (10.4, 7.9)}  # letter minus the page margin
PAGE_IN = {"portrait": (7.6, 10.1), "landscape": (10.1, 7.6)}  # outer minus the sheet inset
TITLE_IN = 0.55  # title line
LINE_IN = 0.3  # name and date line, when shown
FOOTER_IN = 0.3  # sheet number and operation footer
BANNER_IN = 0.7  # badge banner row, reserved only when the sheet shows badges

MIN_PT = 10.0  # informational: under this, type is small, but the layout is still allowed
MAX_PT = 36.0
# The fitted size is used even under 10pt. FLOOR_PT is only a last stop so the
# stylesheet has a class for the size. It is not a legibility rule.
FLOOR_PT = 4.0
SPACING_SCALE = {"roomy": 0.85, "normal": 1.0, "compact": 1.10}
SPACINGS = tuple(SPACING_SCALE)

# Rough metrics, in em. Conservative, so the page fits with some room to spare.
CHAR_EM = 0.62  # average character width
BLANK_EM = 2.4  # answer blank in horizontal layout
DIGIT_EM = 0.56  # Arial digit width
SPACE_EM = 0.28  # Arial space width
OP_EM = 0.58  # Arial × ÷ = + − widths
LINE_EM = 1.2  # one line of text
PAD_EM = 0.6  # cell padding, normal spacing
PAD_TIGHT_EM = 0.3  # cell padding, compact spacing


@dataclass(frozen=True)
class Fit:
    font_pt: float
    cell_w_in: float
    cell_h_in: float
    legible: bool
    spacing: str
    page_direction: str
    raw_pt: float = 0.0  # size before the minimum and maximum clamp, for comparing layouts
    tight: bool = False  # writing space reduced to its floor to fit the page
    fits: bool = True  # everything fits on the page, even at the floor


def _text_em(text):
    """Width of a short expression in em, using typical Arial glyph widths."""
    total = 0.0
    for ch in text:
        if ch.isdigit():
            total += DIGIT_EM
        elif ch == " ":
            total += SPACE_EM
        else:
            total += OP_EM  # operators such as × ÷ = + −
    return total


def _measure(problems, layout):
    """Return (width_em, tall_height_em, compact_height_em) for the widest problems."""
    width = 1.0
    tall = 0.0
    compact = 0.0
    for p in problems:
        if layout == "vertical":
            if p.op == "div":
                # Long division: divisor ) dividend, with the answer line above.
                w = (len(str(p.a)) + len(str(p.dividend))) * CHAR_EM + 1.0
                h = 2 * LINE_EM + PAD_EM  # answer line + bracket line
                hc = 2 * LINE_EM + PAD_TIGHT_EM
            else:
                # Top number, operator and bottom number, rule, then answer space.
                bottom = len(str(p.b)) + 1  # +1 for the operator
                top = len(str(p.a))
                w = max(top, bottom) * CHAR_EM + 0.8
                h = 3 * LINE_EM + 0.1 + PAD_EM  # top, bottom, answer line, rule
                hc = 2 * LINE_EM + 0.1 + LINE_EM * 0.5 + PAD_TIGHT_EM  # half answer line
        else:
            left = p.dividend if p.op == "div" else p.a
            right = p.a if p.op == "div" else p.b
            text = f"{left} {SYMBOL[p.op]} {right} = "
            w = _text_em(text) + BLANK_EM + 0.3
            h = LINE_EM + PAD_EM
            hc = LINE_EM + PAD_TIGHT_EM
        width = max(width, w)
        tall = max(tall, h)
        compact = max(compact, hc)
    return width, tall, compact


def fit_sheet(problems, layout, page_direction, cols, rows, spacing="normal",
              name_line=True, date_line=True, banner=False):
    """Return the Fit for a page: the font size and cell size for this layout."""
    page_w, page_h = PAGE_IN[page_direction]
    head = TITLE_IN + (LINE_IN if (name_line or date_line) else 0.0)
    if banner:
        head += BANNER_IN
    grid_w = page_w
    grid_h = page_h - head - FOOTER_IN
    cell_w = grid_w / cols
    cell_h = grid_h / rows

    width_em, tall_em, compact_em = _measure(problems, layout)
    width_limit = cell_w * 72.0 / width_em
    fit_pt = min(width_limit, cell_h * 72.0 / tall_em)

    if spacing == "compact":
        # Compact trades writing space for type size. It may never overflow the
        # cell, so its cap uses the smaller height that compact padding allows.
        compact_cap = min(width_limit, cell_h * 72.0 / compact_em)
        raw = min(fit_pt * SPACING_SCALE["compact"], compact_cap)
    else:
        raw = fit_pt * SPACING_SCALE.get(spacing, 1.0)

    stepped = math.floor(raw * 2) / 2  # half-point steps, rounded down
    # Use the fitted size, including sizes under 10pt. A dense page gets smaller
    # type with the same writing space, rather than being held at 10pt.
    font_pt = min(MAX_PT, max(FLOOR_PT, stepped))

    return Fit(
        font_pt=font_pt,
        cell_w_in=round(cell_w, 3),
        cell_h_in=round(cell_h, 3),
        spacing=spacing,
        page_direction=page_direction,
        raw_pt=stepped,
        tight=False,
        fits=stepped + 1e-9 >= FLOOR_PT,
        legible=stepped + 1e-9 >= MIN_PT,
    )


def largest_legible(facts, layout, page_direction, spacing="normal",
                    name_line=True, date_line=True, max_cols=10, max_rows=20):
    """Biggest (cols, rows) that stays at or above the minimum size, or None."""
    best = None
    for cols in range(1, max_cols + 1):
        for rows in range(1, max_rows + 1):
            fit = fit_sheet(facts, layout, page_direction, cols, rows, spacing,
                            name_line, date_line)
            if not fit.legible:
                break  # more rows only make the font smaller
            if best is None or cols * rows > best[0] * best[1]:
                best = (cols, rows)
    return best


def suggest_landscape(problems, layout, cols, rows, spacing, name_line, date_line, portrait_fit,
                      banner=False):
    """Suggest landscape only when it is clearly better (spec 5.2.1 builder feedback)."""
    # Compare the fitted sizes, before the 5pt floor and the 36pt cap.
    if portrait_fit.raw_pt >= 14:
        return False
    landscape = fit_sheet(problems, layout, "landscape", cols, rows, spacing,
                          name_line, date_line, banner=banner)
    return landscape.raw_pt >= portrait_fit.raw_pt + 2
