"""Builder, live preview, saved sheets, and print (spec 5.1 to 5.3, 7.4 "New sheet" and "Print").

The builder never saves on its own. Only "Generate and print" and "Save without
printing" store a sheet. Regenerate and the live preview only recompute.
"""

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from . import badges, builder, children, plans, ratings, sheets, sheetview
from . import clock
from .sessions import get_db

bp = Blueprint("sheets", __name__)


def _active_child_ids(db):
    return {c["id"] for c in children.list_children(db, g.account["id"])}


def _preview_view(plan, cfg, number):
    return sheetview.sheet_view(
        title=plan.title,
        number=number,
        operation=cfg.operation,
        orientation=cfg.orientation,
        cols=cfg.cols,
        rows=cfg.rows,
        problems=plan.problems,
        font_pt=plan.fit.font_pt,
        page_direction=cfg.page_direction,
        name_line=cfg.name_line,
        date_line=cfg.date_line,
        answers=False,
        tight=plan.fit.tight,
        badges=cfg.banner_items,
        banner_more=cfg.banner_more,
        stage_name=cfg.stage_name,
    )


def _sync_stage_fields(values, cfg):
    """Show the stage's facts, even if the form tried to change them."""
    if not cfg.plan_stage_id:
        values["plan_stage_id"] = ""
        return
    values["operation"] = cfg.operation
    values["a_spec"] = cfg.a_spec
    values["b_spec"] = cfg.b_spec
    values["plan_stage_id"] = str(cfg.plan_stage_id)


def _prepare(db, values, child_ids, saved_banner=None):
    """Parse, lock a plan stage's facts, and decide the badge banner."""
    cfg, errors = builder.parse(values, child_ids)
    if errors:
        return None, errors
    plans.lock_stage(db, g.account["id"], cfg)
    if saved_banner is not None:
        badges.use_saved_banner(cfg, saved_banner)
    else:
        badges.apply_pending(cfg, db)
    return cfg, {}


def _replace_row(db, replace_id):
    """The issued sheet being replaced, or None. A finished sheet is "completed"."""
    if not str(replace_id).isdigit():
        return None
    loaded = sheets.load_sheet(db, g.account["id"], int(replace_id))
    if loaded is None:
        return "missing"
    row, options, _problems = loaded
    if row["status"] != "issued":
        return "completed"
    return row, options


def _render_builder(kids, values, errors, plan, cfg, status=200, replace=""):
    number = g.account["next_sheet_number"]
    if str(replace).isdigit():
        found = _replace_row(get_db(), replace)
        if isinstance(found, tuple):
            number = found[0]["number"]
    view = _preview_view(plan, cfg, number) if plan and cfg else None
    return render_template(
        "builder.html",
        kids=kids,
        v=values,
        errors=errors,
        plan=plan,
        view=view,
        replace=replace,
        number=number,
        operations=builder.OPERATIONS_CHOICES,
        spacing_choices=builder.SPACING_CHOICES,
        order_choices=builder.ORDER_CHOICES,
    ), status


@bp.route("/builder", methods=["GET", "POST"])
def new_sheet():
    db = get_db()
    kids = children.list_children(db, g.account["id"])

    replace = ""
    if request.method == "GET":
        found = _replace_row(db, request.args.get("replace", ""))
        if found == "missing":
            abort(404)
        if found == "completed":
            flash("This sheet was finished, so its problems stay as they were. Duplicate it to make a new one.")
            return redirect(url_for("sheets.detail", sheet_id=int(request.args.get("replace"))))
        if found:
            row, options = found
            child = children.get_child(db, g.account["id"], row["child_id"])
            if child is None or child["archived"]:
                flash("Restore this child before changing the sheet.")
                return redirect(url_for("sheets.detail", sheet_id=row["id"]))
            values = sheets.form_values(row, options)
            replace = str(row["id"])
            saved_banner = options
        else:
            saved_banner = None
            stage_id = request.args.get("stage", "")
            child_arg = request.args.get("child", "")
            staged = None
            if stage_id.isdigit() and child_arg.isdigit():
                staged = plans.builder_values(
                    db, g.account["id"], int(child_arg), int(stage_id)
                )
            if staged:
                values = builder.defaults()
                values.update(staged)
                values["seed"] = str(builder.new_seed())
            else:
                values = builder.defaults()
                values.update(sheets.remembered_layout(db, g.account["id"]))
                preset = request.args.get("child", "")
                if preset.isdigit() and int(preset) in _active_child_ids(db):
                    values["child"] = preset
                elif kids:
                    values["child"] = str(kids[0]["id"])
            if not kids:
                flash("Add a child before making a sheet.")
                return redirect(url_for("children.new"))
        cfg, _errors = _prepare(db, values, _active_child_ids(db), saved_banner)
        if cfg:
            _sync_stage_fields(values, cfg)
        plan = builder.build_sheet(cfg) if cfg else None
        return _render_builder(kids, values, {}, plan, cfg, replace=replace)

    values = builder.values_from_form(request.form)
    replace = request.form.get("replace", "").strip()
    action = request.form.get("action", "save")
    if action not in ("save", "print", "regenerate", "refresh", "landscape"):
        abort(400)
    if action == "regenerate":
        values["seed"] = str(builder.new_seed())
    if action == "landscape":
        values["page_direction"] = "landscape"

    saved_banner = None
    if replace.isdigit():
        found = _replace_row(db, replace)
        if isinstance(found, tuple):
            saved_banner = found[1]
    cfg, errors = _prepare(db, values, _active_child_ids(db), saved_banner)
    if errors:
        return _render_builder(kids, values, errors, None, None, status=400, replace=replace)
    _sync_stage_fields(values, cfg)

    sheets.remember_layout(db, g.account["id"], cfg)
    plan = builder.build_sheet(cfg)
    if action in ("regenerate", "refresh", "landscape"):
        return _render_builder(kids, values, {}, plan, cfg, replace=replace)

    if replace.isdigit():
        outcome = sheets.replace_sheet(db, g.account["id"], int(replace), cfg, plan)
        if outcome is None:
            abort(404)
        if outcome == "completed":
            flash("This sheet was finished, so it was not changed.")
            return redirect(url_for("sheets.detail", sheet_id=int(replace)))
        flash(f"Updated sheet #{outcome:04d}.")
        sheet_id = int(replace)
    else:
        sheet_id, number = sheets.save_sheet(db, g.account["id"], cfg, plan)
        badges.mark_shown(db, cfg, sheet_id)
        flash(f"Saved sheet #{number:04d}.")
    if action == "print":
        suffix = "?answers=1" if cfg.answer_key else ""
        return redirect(url_for("sheets.print_sheet", sheet_id=sheet_id) + suffix)
    return redirect(url_for("sheets.detail", sheet_id=sheet_id))


@bp.post("/api/worksheets/preview")
def preview():
    """Recompute the preview as the parent types. Saves nothing."""
    db = get_db()
    values = builder.values_from_form(request.form)
    found = _replace_row(db, request.form.get("replace", ""))
    saved_banner = found[1] if isinstance(found, tuple) else None
    cfg, errors = _prepare(db, values, _active_child_ids(db), saved_banner)
    if errors:
        return jsonify(ok=False, errors=errors), 400
    sheets.remember_layout(db, g.account["id"], cfg)
    plan = builder.build_sheet(cfg)
    number = g.account["next_sheet_number"]
    found = _replace_row(db, request.form.get("replace", ""))
    if isinstance(found, tuple):
        number = found[0]["number"]
    html = render_template(
        "_preview.html", view=_preview_view(plan, cfg, number)
    )
    return jsonify(
        ok=True,
        html=html,
        summary=plan.summary,
        auto=plan.auto_label,
        notices=plan.notices,
        suggest_landscape=plan.suggest_landscape,
    )


@bp.get("/worksheets/<int:sheet_id>")
def detail(sheet_id):
    db = get_db()
    loaded = sheets.load_sheet(db, g.account["id"], sheet_id)
    if loaded is None:
        abort(404)
    row, options, problems = loaded
    child = children.get_child(db, g.account["id"], row["child_id"])
    view = sheetview.sheet_view(
        title=row["title"],
        number=row["number"],
        operation=row["operation"],
        orientation=row["orientation"],
        cols=row["cols"],
        rows=row["rows"],
        problems=problems,
        font_pt=options["font_pt"],
        page_direction=options["page_direction"],
        name_line=options["name_line"],
        date_line=options["date_line"],
        answers=False,
        tight=options["tight"],
        badges=options.get("banner") or [],
        banner_more=options.get("banner_more") or 0,
        stage_name=options.get("stage_name") or "",
    )
    rating = ratings.get_rating(db, sheet_id)
    return render_template(
        "sheet_detail.html", sheet=row, options=options, child=child, view=view,
        operation_name=builder.OPERATIONS[row["operation"]], count=len(problems),
        rating=rating,
        performance_label=ratings.performance_label(rating["performance"]) if rating else "",
        support_label=ratings.support_label(rating["support"]) if rating else "",
        pace_label=ratings.pace_label(rating["pace"]) if rating else "",
        aid_label=ratings.aid_label(rating["aid_type"]) if rating else "",
        completed_on=(
            clock.format_day(clock.parse_date(rating["completed_at"]))
            if rating and clock.parse_date(rating["completed_at"]) else ""
        ),
    )


def _sheet_ids():
    return [int(value) for value in request.form.getlist("sheet_id") if str(value).isdigit()]


def _current_child_id(db, kids):
    """The child the list opens on: the last one used, or the first active child."""
    chosen = request.args.get("child")
    if chosen is None:
        chosen = sheets.get_pref(db, g.account["id"], "last_child_id")
    if chosen == "all":
        return None, "all"
    if chosen and str(chosen).isdigit() and any(c["id"] == int(chosen) for c in kids):
        sheets.set_pref(db, g.account["id"], "last_child_id", str(int(chosen)))
        return int(chosen), str(int(chosen))
    if kids:
        sheets.set_pref(db, g.account["id"], "last_child_id", str(kids[0]["id"]))
        return kids[0]["id"], str(kids[0]["id"])
    return None, "all"


@bp.get("/worksheets")
def index():
    db = get_db()
    account_id = g.account["id"]
    kids = children.list_children(db, account_id) + children.list_children(
        db, account_id, archived=True
    )
    cleanup = request.args.get("cleanup") == "1"
    child_id, child_value = (None, "all") if cleanup else _current_child_id(db, kids)
    operation = request.args.get("operation", "")
    if operation not in builder.OPERATIONS:
        operation = ""
    status = request.args.get("status", "")
    if status not in ("issued", "completed"):
        status = ""
    support = request.args.get("support", "")
    if support not in {str(value) for value, _label in ratings.SUPPORT}:
        support = ""
    date_from = clock.parse_date(request.args.get("date_from", ""))
    date_to = clock.parse_date(request.args.get("date_to", ""))
    page = request.args.get("page", "1")
    page = int(page) if page.isdigit() and int(page) > 0 else 1
    issued_before = None
    if cleanup:
        issued_before = clock.now() - sheets.UNFINISHED_DAYS * 86400
        status = "issued"
    rows, total = sheets.list_sheets(
        db, account_id,
        child_id=child_id,
        operation=operation or None,
        status=status or None,
        support=int(support) if support else None,
        search=request.args.get("q", ""),
        date_from=date_from,
        date_to=date_to,
        issued_before=issued_before,
        page=page,
    )
    pages = max(1, (total + sheets.PAGE_SIZE - 1) // sheets.PAGE_SIZE)
    kept = request.args.to_dict()
    kept.pop("cleanup", None)
    kept.pop("page", None)
    cancel_url = url_for("sheets.index", **kept)
    cleanup_url = url_for("sheets.index", **{**kept, "cleanup": "1"})

    def page_link(number):
        args = request.args.to_dict()
        args["page"] = number
        return url_for("sheets.index", **args)

    return render_template(
        "sheet_list.html",
        rows=rows,
        kids=kids,
        total=total,
        page=page,
        pages=pages,
        cleanup=cleanup,
        filters={
            "q": request.args.get("q", ""),
            "child": child_value,
            "operation": operation,
            "status": status,
            "support": support,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
        },
        operations=builder.OPERATIONS,
        support_choices=ratings.SUPPORT,
        performance_label=ratings.performance_label,
        support_label=ratings.support_label,
        format_day=clock.format_day,
        local_date=clock.local_date,
        parse_date=clock.parse_date,
        symbols=builder.SYMBOL,
        previous=page_link(page - 1) if page > 1 else None,
        next_url=page_link(page + 1) if page < pages else None,
        cancel_url=cancel_url,
        cleanup_url=cleanup_url,
        unfinished_days=sheets.UNFINISHED_DAYS,
    )


@bp.route("/worksheets/delete", methods=["GET", "POST"])
def delete_selected():
    db = get_db()
    if request.method == "GET":
        raw = request.args.get("ids", "")
        ids = [int(part) for part in raw.split(",") if part.isdigit()]
    else:
        ids = _sheet_ids()
    rows = sheets.owned_sheets(db, g.account["id"], ids)
    if not rows:
        flash("Select at least one sheet.")
        return redirect(url_for("sheets.index"))
    confirmed = request.method == "POST" and request.form.get("confirm") == "yes"
    if not confirmed:
        return render_template(
            "delete_sheets.html",
            rows=rows,
            completed=any(row["status"] == "completed" for row in rows),
        )
    sheets.delete_sheets(db, g.account["id"], [row["id"] for row in rows])
    count = len(rows)
    flash(f"Deleted {count} sheet." if count == 1 else f"Deleted {count} sheets.")
    return redirect(url_for("sheets.index"))


@bp.route("/worksheets/<int:sheet_id>/rate", methods=["GET", "POST"])
def rate(sheet_id):
    db = get_db()
    loaded = sheets.load_sheet(db, g.account["id"], sheet_id)
    if loaded is None:
        abort(404)
    row, _options, _problems = loaded
    child = children.get_child(db, g.account["id"], row["child_id"])
    rating = ratings.get_rating(db, sheet_id)
    today = clock.iso_date()
    if request.method == "GET":
        if rating:
            values = {
                "performance": str(rating["performance"]),
                "support": str(rating["support"]),
                "pace": "" if rating["pace"] is None else str(rating["pace"]),
                "aid_type": rating["aid_type"] or "",
                "completed_on": rating["completed_at"],
                "notes": rating["notes"] or "",
            }
        else:
            values = {
                "performance": "", "support": "3", "pace": "", "aid_type": "",
                "completed_on": today, "notes": "",
            }
        return render_template(
            "rate_sheet.html", sheet=row, child=child, values=values, errors={},
            performance=ratings.PERFORMANCE, support=ratings.SUPPORT, pace=ratings.PACE,
            aids=ratings.AIDS,
        )

    clean, errors = ratings.validate(request.form, today)
    if errors:
        posted = {key: request.form.get(key, "") for key in (
            "performance", "support", "pace", "aid_type", "completed_on", "notes"
        )}
        return render_template(
            "rate_sheet.html", sheet=row, child=child, values=posted, errors=errors,
            performance=ratings.PERFORMANCE, support=ratings.SUPPORT, pace=ratings.PACE,
            aids=ratings.AIDS,
        ), 400
    ratings.save_rating(db, sheet_id, clean)
    plans.refresh_child(db, row["child_id"], clear_snooze=True)
    for result in plans.graduate_ready(db, g.account["id"], row["child_id"]):
        if result == "finished":
            flash("That was the last stage. The plan is complete.")
        else:
            flash(f"Moved on to {result}.")
    earned = badges.evaluate(db, row["child_id"], g.account["id"])
    flash(f"Saved the rating for sheet #{row['number']:04d}.")
    if earned:
        flash("New badge earned! " + ", ".join(earned) + ".")
    if row["plan_stage_id"]:
        for progress in plans.child_plans(db, g.account["id"], row["child_id"]):
            plans.ensure_open_sheet(db, g.account["id"], row["child_id"], progress["plan_id"])
        return redirect(url_for("web.index", child=row["child_id"]))
    return redirect(url_for("sheets.detail", sheet_id=sheet_id))


@bp.post("/worksheets/<int:sheet_id>/regenerate")
def regenerate(sheet_id):
    db = get_db()
    loaded = sheets.load_sheet(db, g.account["id"], sheet_id)
    if loaded is None:
        abort(404)
    row, options, _problems = loaded
    if row["status"] != "issued":
        flash("This sheet was finished, so its problems stay as they were. Duplicate it to make a new one.")
        return redirect(url_for("sheets.detail", sheet_id=sheet_id))
    values = sheets.form_values(row, options)
    values["seed"] = str(builder.new_seed())
    cfg, errors = _prepare(db, values, {row["child_id"]}, options)
    if errors:
        abort(400)
    plan = builder.build_sheet(cfg)
    number = sheets.replace_sheet(db, g.account["id"], sheet_id, cfg, plan)
    flash(f"Regenerated sheet #{number:04d}.")
    return redirect(url_for("sheets.print_sheet", sheet_id=sheet_id))


@bp.post("/worksheets/<int:sheet_id>/duplicate")
def duplicate(sheet_id):
    db = get_db()
    loaded = sheets.load_sheet(db, g.account["id"], sheet_id)
    if loaded is None:
        abort(404)
    row, options, _problems = loaded
    values = sheets.form_values(row, options)
    values["seed"] = str(builder.new_seed())
    values["badges_on"] = True
    cfg, errors = _prepare(db, values, {row["child_id"]})
    if errors:
        abort(400)
    plan = builder.build_sheet(cfg)
    new_id, number = sheets.save_sheet(db, g.account["id"], cfg, plan)
    badges.mark_shown(db, cfg, new_id)
    flash(f"Duplicated as sheet #{number:04d}.")
    return redirect(url_for("sheets.print_sheet", sheet_id=new_id))


@bp.get("/worksheets/<int:sheet_id>/print")
def print_sheet(sheet_id):
    db = get_db()
    loaded = sheets.load_sheet(db, g.account["id"], sheet_id)
    if loaded is None:
        abort(404)
    row, options, problems = loaded
    answers = request.args.get("answers") == "1"

    def view(with_answers):
        return sheetview.sheet_view(
            title=row["title"],
            number=row["number"],
            operation=row["operation"],
            orientation=row["orientation"],
            cols=row["cols"],
            rows=row["rows"],
            problems=problems,
            font_pt=options["font_pt"],
            page_direction=options["page_direction"],
            name_line=options["name_line"],
            date_line=options["date_line"],
            answers=with_answers,
            tight=options["tight"],
            badges=options.get("banner") or [],
            banner_more=options.get("banner_more") or 0,
            stage_name=options.get("stage_name") or "",
        )

    pages = [view(False)]
    if answers:
        pages.append(view(True))
    return render_template(
        "print.html",
        pages=pages,
        orientation=options["page_direction"],
        sheet=row,
    )
