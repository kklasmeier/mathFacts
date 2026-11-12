"""Seeded system plans and the starter badge catalog (spec 5.6, 5.7).

System rows have no account. Copying a plan for a family never changes these
rows, and a later edit here never changes a copy that already exists.
"""

from . import clock

# (key, name, a_spec, b_spec, pair_rule, pair_limit, mixed)
# Layout for every seeded stage: horizontal, portrait, 5 across, 4 down, 20% review.

ADDITION = [
    ("add-0-1", "+0 and +1", "0-9", "0,1", "any", None, 0),
    ("add-2", "+2", "0-9", "2", "any", None, 0),
    ("add-3", "+3", "0-9", "3", "any", None, 0),
    ("add-sums-10", "Facts 0–10", "0-10", "0-10", "any", None, 0),
    ("add-4-5", "+4 and +5", "0-9", "4,5", "any", None, 0),
    ("add-doubles", "Doubles", "1-9", "1-9", "operands_equal", None, 0),
    ("add-6-7", "+6 and +7", "0-9", "6,7", "any", None, 0),
    ("add-8-9", "+8 and +9", "0-9", "8,9", "any", None, 0),
    ("add-mixed-5", "Facts 0–5 mixed", "0-5", "0-5", "any", None, 1),
    ("add-mixed-10", "Facts 0–10 mixed", "0-10", "0-10", "any", None, 1),
    ("add-mixed-12", "Facts 0–12 mixed", "0-12", "0-12", "any", None, 1),
]
SUBTRACTION = [
    ("sub-0-1", "−0 and −1", "0-9", "0,1", "any", None, 0),
    ("sub-2", "−2", "0-12", "2", "any", None, 0),
    ("sub-within-10", "Differences within 10", "0-10", "0-10", "any", None, 0),
    ("sub-3-5", "−3, −4, and −5", "0-12", "3,4,5", "any", None, 0),
    ("sub-6-7", "−6 and −7", "0-12", "6,7", "any", None, 0),
    ("sub-8-9", "−8 and −9", "0-12", "8,9", "any", None, 0),
    ("sub-within-20", "Within 20 mixed", "0-20", "0-20", "any", None, 1),
    ("sub-mixed-12", "Facts 0–12 mixed", "0-12", "0-12", "any", None, 1),
]
MULTIPLICATION = [
    ("mul-0-1", "×0 and ×1", "0-12", "0,1", "any", None, 0),
    ("mul-2", "×2", "0-12", "2", "any", None, 0),
    ("mul-5", "×5", "0-12", "5", "any", None, 0),
    ("mul-10", "×10", "0-12", "10", "any", None, 0),
    ("mul-3", "×3", "0-12", "3", "any", None, 0),
    ("mul-4", "×4", "0-12", "4", "any", None, 0),
    ("mul-mixed-5", "Mixed 0–5", "0-5", "0-5", "any", None, 1),
    ("mul-6", "×6", "0-12", "6", "any", None, 0),
    ("mul-7", "×7", "0-12", "7", "any", None, 0),
    ("mul-8", "×8", "0-12", "8", "any", None, 0),
    ("mul-9", "×9", "0-12", "9", "any", None, 0),
    ("mul-mixed-9", "Mixed 0–9", "0-9", "0-9", "any", None, 1),
    ("mul-11-12", "×11 and ×12", "0-12", "11,12", "any", None, 0),
    ("mul-mixed-12", "Mixed 0–12", "0-12", "0-12", "any", None, 1),
]
DIVISION = [
    ("div-1", "÷1", "1", "0-12", "any", None, 0),
    ("div-2", "÷2", "2", "0-12", "any", None, 0),
    ("div-5-10", "÷5 and ÷10", "5,10", "0-12", "any", None, 0),
    ("div-3", "÷3", "3", "0-12", "any", None, 0),
    ("div-4", "÷4", "4", "0-12", "any", None, 0),
    ("div-mixed-5", "Mixed divisors 1–5", "1-5", "0-12", "any", None, 1),
    ("div-6", "÷6", "6", "0-12", "any", None, 0),
    ("div-7", "÷7", "7", "0-12", "any", None, 0),
    ("div-8-9", "÷8 and ÷9", "8,9", "0-12", "any", None, 0),
    ("div-mixed-9", "Mixed divisors 1–9", "1-9", "0-12", "any", None, 1),
    ("div-mixed-12", "Divisors 1–12 mixed", "1-12", "0-12", "any", None, 1),
]

PLANS = (
    ("add", "Addition", ADDITION),
    ("sub", "Subtraction", SUBTRACTION),
    ("mul", "Multiplication", MULTIPLICATION),
    ("div", "Division", DIVISION),
)

# (key, name, description, icon, category, rule_type, tier)
BADGES = [
    ("first_sheet", "First Sheet", "Finish your first sheet.", "★", "effort", "count", 1),
    ("sheets_5", "Sheet Collector 5", "Finish 5 sheets.", "★", "effort", "count", 5),
    ("sheets_10", "Sheet Collector 10", "Finish 10 sheets.", "★", "effort", "count", 10),
    ("sheets_25", "Sheet Collector 25", "Finish 25 sheets.", "★", "effort", "count", 25),
    ("sheets_50", "Sheet Collector 50", "Finish 50 sheets.", "★", "effort", "count", 50),
    ("sheets_100", "Sheet Collector 100", "Finish 100 sheets.", "★", "effort", "count", 100),
    ("busy_week", "Busy Week", "Finish 3 sheets in one week.", "●", "effort", "busy_week", 3),
    ("streak_2", "Steady Practicer 2", "Practice for 2 weeks in a row.", "●", "effort", "streak", 2),
    ("streak_4", "Steady Practicer 4", "Practice for 4 weeks in a row.", "●", "effort", "streak", 4),
    ("streak_8", "Steady Practicer 8", "Practice for 8 weeks in a row.", "●", "effort", "streak", 8),
    ("great_job", "Great Job!", "Earn Excellent on a sheet.", "★", "achievement", "excellent", 1),
    ("shining_5", "Shining Star 5", "Earn Excellent on 5 sheets.", "★", "achievement", "excellent", 5),
    ("shining_10", "Shining Star 10", "Earn Excellent on 10 sheets.", "★", "achievement", "excellent", 10),
    ("shining_25", "Shining Star 25", "Earn Excellent on 25 sheets.", "★", "achievement", "excellent", 25),
    ("solid_work", "Solid Work", "Earn Good or better on 5 sheets in a row.", "★", "achievement", "solid", 5),
    ("mix_master", "Mix Master", "Earn Good or better on a mixed review stage.", "★", "achievement", "mix", 3),
    ("champion_add", "Addition Champion", "Finish every stage of an addition plan.", "▲", "achievement", "champion", None),
    ("champion_sub", "Subtraction Champion", "Finish every stage of a subtraction plan.", "▲", "achievement", "champion", None),
    ("champion_mul", "Multiplication Champion", "Finish every stage of a multiplication plan.", "▲", "achievement", "champion", None),
    ("champion_div", "Division Champion", "Finish every stage of a division plan.", "▲", "achievement", "champion", None),
    ("comeback", "Comeback Kid", "Score higher than the sheet before.", "◆", "growth", "comeback", None),
    ("personal_best", "Personal Best", "Set a new best average over 5 sheets.", "◆", "growth", "best", None),
    ("less_help", "Less Help", "Need less support than the previous sheet in a stage.", "◆", "growth", "less_help", None),
    ("own_add", "On My Own · Addition", "Finish an addition sheet on your own.", "◆", "growth", "own", None),
    ("own_sub", "On My Own · Subtraction", "Finish a subtraction sheet on your own.", "◆", "growth", "own", None),
    ("own_mul", "On My Own · Multiplication", "Finish a multiplication sheet on your own.", "◆", "growth", "own", None),
    ("own_div", "On My Own · Division", "Finish a division sheet on your own.", "◆", "growth", "own", None),
    ("quick_thinker", "Quick Thinker", "A faster pace than the previous sheet in that operation.", "◆", "growth", "pace", None),
]

CHAMPION_KEYS = {"add": "champion_add", "sub": "champion_sub", "mul": "champion_mul", "div": "champion_div"}
OWN_KEYS = {"add": "own_add", "sub": "own_sub", "mul": "own_mul", "div": "own_div"}
DEFAULT_COLS = 5
DEFAULT_ROWS = 4
DEFAULT_REVIEW = 20


def seed(db):
    """Insert system plans and badges once. Existing family copies are left alone."""
    if db.execute("SELECT COUNT(*) FROM plans WHERE is_system = 1").fetchone()[0] == 0:
        now = clock.now()
        for operation, name, stages in PLANS:
            cursor = db.execute(
                """
                INSERT INTO plans (account_id, operation, name, is_system, created_at)
                VALUES (NULL, ?, ?, 1, ?)
                """,
                (operation, name, now),
            )
            plan_id = cursor.lastrowid
            for position, stage in enumerate(stages, start=1):
                _insert_stage(db, plan_id, position, stage, operation)
    if db.execute("SELECT COUNT(*) FROM badges WHERE account_id IS NULL").fetchone()[0] == 0:
        now = clock.now()
        for key, name, description, icon, category, rule, tier in BADGES:
            db.execute(
                """
                INSERT INTO badges (
                    account_id, key, name, description, icon, category, rule_type, tier, created_at
                ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (key, name, description, icon, category, rule, tier, now),
            )
        for _operation, _name, stages in PLANS:
            for stage in stages:
                _stage_badge(db, None, stage[0], stage[1], now)


def _insert_stage(db, plan_id, position, stage, operation):
    key, name, a_spec, b_spec, rule, limit, mixed = stage
    db.execute(
        """
        INSERT INTO plan_stages (
            plan_id, position, stage_key, name, operation, a_spec, b_spec, include_reverse,
            pair_rule, pair_rule_limit, default_orientation, default_page_direction,
            default_cols, default_rows, review_mix_pct, mixed,
            adv_x, adv_y, adv_min_performance, min_sheets
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'horizontal', 'portrait', ?, ?, ?, ?, 2, 3, 3, 3)
        """,
        (plan_id, position, key, name, operation, a_spec, b_spec, rule, limit,
         DEFAULT_COLS, DEFAULT_ROWS, DEFAULT_REVIEW, mixed),
    )


def _stage_badge(db, account_id, stage_key, stage_name, now):
    db.execute(
        """
        INSERT INTO badges (
            account_id, key, name, description, icon, category, rule_type, tier, created_at
        ) VALUES (?, ?, ?, ?, '★', 'achievement', 'stage', NULL, ?)
        """,
        (
            account_id, f"stage_complete:{stage_key}", f"{stage_name} Complete",
            f"Move past {stage_name}.", now,
        ),
    )
