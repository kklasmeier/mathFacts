"""Turn problems into the view data the sheet template draws (spec 5.2).

The template draws only what this module returns: no logic and no inline
styles. Font size and grid size are CSS classes, so the strict CSP still holds.
"""

from .pools import OPERATIONS, SYMBOL


def pt_class(font_pt):
    """Half-point steps map to pt-20 … pt-72 (10pt … 36pt)."""
    return f"pt-{int(round(font_pt * 2))}"


def _cell(problem, layout, answers):
    answer = problem.answer if answers else None
    if layout == "vertical":
        if problem.op == "div":
            return {"kind": "long", "divisor": problem.a, "dividend": problem.dividend,
                    "answer": answer}
        return {"kind": "vertical", "top": problem.a, "op": SYMBOL[problem.op],
                "bottom": problem.b, "answer": answer}
    if problem.op == "div":
        return {"kind": "horizontal", "left": problem.dividend, "op": SYMBOL["div"],
                "right": problem.a, "answer": answer}
    return {"kind": "horizontal", "left": problem.a, "op": SYMBOL[problem.op],
            "right": problem.b, "answer": answer}


def sheet_view(*, title, number, operation, orientation, cols, rows, problems,
               font_pt, page_direction, name_line, date_line, answers, tight=False,
               badges=None, banner_more=0, stage_name=""):
    footer = f"#{number:04d} · {OPERATIONS[operation]}"
    if stage_name:
        footer += f" · {stage_name}"
    # The answer key never shows badges, even when the worksheet page does.
    shown = [] if answers else list(badges or [])
    return {
        "title": title,
        "footer": footer,
        "name_line": name_line,
        "date_line": date_line,
        "page": page_direction,
        "pt_class": pt_class(font_pt),
        "cols_class": f"cols-{cols}",
        "rows_class": f"rows-{rows}",
        "answers": answers,
        "tight": tight,
        "badges": shown,
        "banner_more": 0 if answers else banner_more,
        "cells": [_cell(p, orientation, answers) for p in problems],
    }
