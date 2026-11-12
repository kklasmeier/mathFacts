"""Sheet builder: form values in, a validated config out, and a built sheet (spec 5.1, 5.2.1).

The preview and the saved sheet both come from build_sheet(config). Same config
and same seed always give the same problems, so the saved sheet matches the
preview the parent approved.
"""

import random
from dataclasses import dataclass, field

from .fit import SPACINGS, fit_sheet, suggest_landscape
from .pools import OPERATIONS, SYMBOL, build_pool, constrained_pool
from .slots import ORDERS, arrange
from .specs import OPERAND_LIMIT, SpecError, parse_spec

ORIENTATIONS = ("vertical", "horizontal")
PAGE_DIRECTIONS = ("portrait", "landscape")
MAX_COLS = 10
MAX_ROWS = 20
MAX_TITLE = 80

# (value, label) pairs for the builder's radio buttons and selects.
OPERATIONS_CHOICES = [(key, OPERATIONS[key], SYMBOL[key]) for key in ("add", "sub", "mul", "div")]
SPACING_CHOICES = [("roomy", "Roomy"), ("normal", "Normal"), ("compact", "Compact")]
ORDER_CHOICES = [
    ("sequential", "Sequential"),
    ("shuffled", "Shuffled"),
    ("random", "Random with repeats"),
]

TEXT_DEFAULTS = {
    "child": "",
    "operation": "mul",
    "a_spec": "1-9",
    "b_spec": "2",
    "orientation": "horizontal",
    "page_direction": "portrait",
    "cols": "5",
    "rows": "8",
    "order": "shuffled",
    "title": "",
    "spacing": "normal",
    "seed": "",
    "plan_stage_id": "",
}
BOOL_FIELDS = ("include_reverse", "allow_negatives", "name_line", "date_line", "answer_key", "badges_on")
BOOL_DEFAULTS = {"name_line": True, "date_line": True, "badges_on": True}


def new_seed():
    return random.SystemRandom().randrange(1, 2**31)


def defaults():
    values = dict(TEXT_DEFAULTS)
    values.update({key: False for key in BOOL_FIELDS})
    values.update(BOOL_DEFAULTS)
    values["seed"] = str(new_seed())
    return values


def values_from_form(form):
    """Read builder fields. A checkbox is on when its name is present in the form."""
    values = dict(TEXT_DEFAULTS)
    for key in TEXT_DEFAULTS:
        if key in form:
            values[key] = form.get(key, "")
    for key in BOOL_FIELDS:
        values[key] = key in form
    if not str(values.get("seed", "")).strip():
        values["seed"] = str(new_seed())
    return values


@dataclass
class SheetConfig:
    child_id: int
    operation: str
    a_spec: str
    b_spec: str
    include_reverse: bool
    allow_negatives: bool
    orientation: str
    page_direction: str
    cols: int
    rows: int
    order: str
    title: str
    name_line: bool
    date_line: bool
    answer_key: bool
    spacing: str
    seed: int
    plan_stage_id: int | None = None
    pair_rule: str = "any"
    pair_rule_limit: int | None = None
    review_pct: int = 0
    review_facts: tuple = ()
    badges_on: bool = True
    banner_items: tuple = ()
    banner_more: int = 0
    banner_ids: tuple = ()
    stage_name: str = ""


@dataclass
class SheetPlan:
    title: str
    problems: list
    fit: object
    summary: str
    notices: list = field(default_factory=list)
    auto_label: str = ""
    suggest_landscape: bool = False
    largest: object = None


def _whole_number(raw, low, high):
    text = str(raw).strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if low <= value <= high else None


def parse(values, child_ids):
    """Validate builder values. Returns (config, errors). `errors` maps field name to message."""
    errors = {}

    child_text = str(values.get("child", "")).strip()
    child_id = int(child_text) if child_text.isdigit() else None
    if child_id not in child_ids:
        child_id = None
        errors["child"] = "Choose one of your active children."

    operation = values.get("operation")
    if operation not in OPERATIONS:
        errors["operation"] = "Choose addition, subtraction, multiplication, or division."
        operation = "mul"

    limit = OPERAND_LIMIT[operation]
    a_values = b_values = None
    try:
        a_values = parse_spec(values.get("a_spec", ""), limit)
    except SpecError as problem:
        errors["a_spec"] = str(problem)
    try:
        b_values = parse_spec(values.get("b_spec", ""), limit)
    except SpecError as problem:
        errors["b_spec"] = str(problem)

    cols = _whole_number(values.get("cols"), 1, MAX_COLS)
    if cols is None:
        errors["cols"] = f"Across must be a whole number from 1 to {MAX_COLS}."
    rows = _whole_number(values.get("rows"), 1, MAX_ROWS)
    if rows is None:
        errors["rows"] = f"Down must be a whole number from 1 to {MAX_ROWS}."

    orientation = values.get("orientation")
    if orientation not in ORIENTATIONS:
        errors["orientation"] = "Choose vertical or horizontal problems."
    page_direction = values.get("page_direction")
    if page_direction not in PAGE_DIRECTIONS:
        errors["page_direction"] = "Choose portrait or landscape."
    order = values.get("order")
    if order not in ORDERS:
        errors["order"] = "Choose an order."
    spacing = values.get("spacing")
    if spacing not in SPACINGS:
        errors["spacing"] = "Choose roomy, normal, or compact."

    title = str(values.get("title", "")).strip()
    if len(title) > MAX_TITLE:
        errors["title"] = f"Use {MAX_TITLE} characters or fewer."

    seed_text = str(values.get("seed", "")).strip()
    seed = int(seed_text) if seed_text.lstrip("-").isdigit() else new_seed()
    stage_text = str(values.get("plan_stage_id", "")).strip()
    plan_stage_id = int(stage_text) if stage_text.isdigit() else None

    include_reverse = bool(values.get("include_reverse")) and operation in ("add", "mul")
    allow_negatives = bool(values.get("allow_negatives")) and operation == "sub"

    if not errors and a_values is not None and b_values is not None:
        pool = build_pool(operation, a_values, b_values, include_reverse, allow_negatives)
        if not pool.facts:
            errors["a_spec"] = (
                "No facts are left with these numbers. Check the operands, or turn on "
                "Allow negatives for subtraction."
            )

    if errors:
        return None, errors

    return SheetConfig(
        child_id=child_id,
        operation=operation,
        a_spec=values["a_spec"].strip(),
        b_spec=values["b_spec"].strip(),
        include_reverse=include_reverse,
        allow_negatives=allow_negatives,
        orientation=orientation,
        page_direction=page_direction,
        cols=cols,
        rows=rows,
        order=order,
        title=title,
        name_line=bool(values.get("name_line")),
        date_line=bool(values.get("date_line")),
        answer_key=bool(values.get("answer_key")),
        spacing=spacing,
        seed=seed,
        plan_stage_id=plan_stage_id,
        badges_on=bool(values.get("badges_on", True)),
    ), {}


def build_sheet(cfg):
    """Build the problems and layout for a config. Pure: same config, same result."""
    a_values = parse_spec(cfg.a_spec, OPERAND_LIMIT[cfg.operation])
    b_values = parse_spec(cfg.b_spec, OPERAND_LIMIT[cfg.operation])
    pool = constrained_pool(
        cfg.operation, a_values, b_values, cfg.include_reverse, cfg.allow_negatives,
        cfg.pair_rule, cfg.pair_rule_limit,
    )

    review = list(cfg.review_facts)
    arr = arrange(
        pool.facts, cfg.rows, cfg.cols, cfg.order, random.Random(cfg.seed),
        review=review, review_pct=cfg.review_pct if review else 0,
    )
    show_banner = bool(cfg.banner_items or cfg.banner_more)
    fit = fit_sheet(arr.cells, cfg.orientation, cfg.page_direction, cfg.cols, cfg.rows,
                    cfg.spacing, cfg.name_line, cfg.date_line, banner=show_banner)

    notices = []
    if pool.dropped_zero:
        notices.append(f"{pool.dropped_zero} division facts with divisor 0 were dropped.")
    if pool.dropped_negative:
        notices.append(
            f"{pool.dropped_negative} subtraction facts with a smaller first number were "
            "dropped. Turn on Allow negatives to keep them."
        )
    if review and cfg.review_pct:
        review_n = int(round(arr.slots * cfg.review_pct / 100))
        review_n = max(0, min(arr.slots, review_n))
        if review_n:
            notices.append(f"{review_n} spaces are review from earlier stages.")
    if arr.all_same:
        notices.append("Every problem on this page is the same fact.")
    elif arr.repeats:
        notices.append(
            f"{arr.pool_size} facts will repeat about {arr.slots // arr.pool_size}× each."
        )
    elif arr.pool_size > arr.slots:
        notices.append(f"Picked {arr.slots} of {arr.pool_size} facts at random.")
    if not arr.separated and not arr.all_same:
        notices.append(
            "Some repeats could not be separated on this page. Try a different order "
            "or fewer problems."
        )

    if not fit.fits:
        notices.append(
            "Even at the smallest size these problems will not fit. Use fewer columns or rows."
        )

    suggest = cfg.page_direction == "portrait" and suggest_landscape(
        arr.cells, cfg.orientation, cfg.cols, cfg.rows, cfg.spacing,
        cfg.name_line, cfg.date_line, fit, banner=show_banner,
    )

    title = cfg.title or f"{OPERATIONS[cfg.operation]}: {cfg.a_spec} {SYMBOL[cfg.operation]} {cfg.b_spec}"
    return SheetPlan(
        title=title,
        problems=arr.cells,
        fit=fit,
        summary=f"{arr.pool_size} unique facts, {arr.slots} spaces.",
        notices=notices,
        auto_label=f"Auto size: {fit.font_pt:g}pt",
        suggest_landscape=suggest,
    )
