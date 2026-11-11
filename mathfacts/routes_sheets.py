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

from . import builder, children, sheets, sheetview
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
    )


def _render_builder(kids, values, errors, plan, cfg, status=200):
    view = _preview_view(plan, cfg, g.account["next_sheet_number"]) if plan and cfg else None
    return render_template(
        "builder.html",
        kids=kids,
        v=values,
        errors=errors,
        plan=plan,
        view=view,
        operations=builder.OPERATIONS_CHOICES,
        spacing_choices=builder.SPACING_CHOICES,
        order_choices=builder.ORDER_CHOICES,
    ), status


@bp.route("/builder", methods=["GET", "POST"])
def new_sheet():
    db = get_db()
    kids = children.list_children(db, g.account["id"])

    if request.method == "GET":
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
        cfg, _errors = builder.parse(values, _active_child_ids(db))
        plan = builder.build_sheet(cfg) if cfg else None
        return _render_builder(kids, values, {}, plan, cfg)

    values = builder.values_from_form(request.form)
    action = request.form.get("action", "save")
    if action not in ("save", "print", "regenerate", "refresh", "landscape"):
        abort(400)
    if action == "regenerate":
        values["seed"] = str(builder.new_seed())
    if action == "landscape":
        values["page_direction"] = "landscape"

    cfg, errors = builder.parse(values, _active_child_ids(db))
    if errors:
        return _render_builder(kids, values, errors, None, None, status=400)

    sheets.remember_layout(db, g.account["id"], cfg)
    plan = builder.build_sheet(cfg)
    if action in ("regenerate", "refresh", "landscape"):
        return _render_builder(kids, values, {}, plan, cfg)

    sheet_id, number = sheets.save_sheet(db, g.account["id"], cfg, plan)
    flash(f"Saved sheet #{number:04d}.")
    if action == "print":
        suffix = "?answers=1" if cfg.answer_key else ""
        return redirect(url_for("sheets.print_sheet", sheet_id=sheet_id) + suffix)
    return redirect(url_for("sheets.detail", sheet_id=sheet_id))


@bp.post("/api/worksheets/preview")
def preview():
    """Recompute the preview as the parent types. Saves nothing."""
    db = get_db()
    cfg, errors = builder.parse(builder.values_from_form(request.form), _active_child_ids(db))
    if errors:
        return jsonify(ok=False, errors=errors), 400
    sheets.remember_layout(db, g.account["id"], cfg)
    plan = builder.build_sheet(cfg)
    html = render_template(
        "_preview.html", view=_preview_view(plan, cfg, g.account["next_sheet_number"])
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
    )
    return render_template(
        "sheet_detail.html", sheet=row, options=options, child=child, view=view,
        operation_name=builder.OPERATIONS[row["operation"]], count=len(problems),
    )


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
