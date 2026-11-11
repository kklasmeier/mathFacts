"""Children pages: list, add, edit, archive, restore, and delete (spec 5.12.1)."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import children, settings
from .sessions import get_db

bp = Blueprint("children", __name__)


def _child_or_404(db, child_id):
    child = children.get_child(db, g.account["id"], child_id)
    if child is None:
        abort(404)
    return child


@bp.get("/children")
def index():
    db = get_db()
    account_id = g.account["id"]
    return render_template(
        "children.html",
        active=children.list_children(db, account_id),
        archived=children.list_children(db, account_id, archived=True),
        total=children.count_children(db, account_id),
        limit=settings.max_children(db),
    )


@bp.route("/children/new", methods=["GET", "POST"])
def new():
    db = get_db()
    account_id = g.account["id"]
    limit = settings.max_children(db)
    if children.count_children(db, account_id) >= limit:
        flash(f"You can have up to {limit} children on one account.")
        return redirect(url_for("children.index"))

    if request.method == "GET":
        return render_template(
            "child_form.html", child=None, values={"name": "", "grade": "", "color": ""},
            errors={}, colors=children.COLORS,
        )

    values, errors = children.validate(
        request.form.get("name"), request.form.get("grade"), request.form.get("color")
    )
    if errors:
        return render_template(
            "child_form.html", child=None, values=_raw(request.form), errors=errors,
            colors=children.COLORS,
        ), 400

    children.create_child(db, account_id, values)
    flash(f"Added {values['name']}.")
    return redirect(url_for("children.index"))


@bp.route("/children/<int:child_id>/edit", methods=["GET", "POST"])
def edit(child_id):
    db = get_db()
    account_id = g.account["id"]
    child = _child_or_404(db, child_id)

    if request.method == "GET":
        return render_template(
            "child_form.html", child=child,
            values={"name": child["name"], "grade": child["grade"] or "",
                    "color": child["color"] or ""},
            errors={}, colors=children.COLORS,
        )

    values, errors = children.validate(
        request.form.get("name"), request.form.get("grade"), request.form.get("color")
    )
    if errors:
        return render_template(
            "child_form.html", child=child, values=_raw(request.form), errors=errors,
            colors=children.COLORS,
        ), 400

    children.update_child(db, account_id, child_id, values)
    flash(f"Saved {values['name']}.")
    return redirect(url_for("children.index"))


@bp.post("/children/<int:child_id>/archive")
def archive(child_id):
    db = get_db()
    child = _child_or_404(db, child_id)
    children.set_archived(db, g.account["id"], child_id, True)
    flash(f"{child['name']} is archived. Their sheets are kept.")
    return redirect(url_for("children.index"))


@bp.post("/children/<int:child_id>/restore")
def restore(child_id):
    db = get_db()
    child = _child_or_404(db, child_id)
    children.set_archived(db, g.account["id"], child_id, False)
    flash(f"{child['name']} is back in the child list.")
    return redirect(url_for("children.index"))


@bp.post("/children/<int:child_id>/delete")
def delete(child_id):
    db = get_db()
    child = _child_or_404(db, child_id)
    typed = (request.form.get("confirm_name") or "").strip().casefold()
    if typed != child["name"].strip().casefold():
        flash(f"To delete {child['name']}, type their name exactly as shown.")
        return redirect(url_for("children.edit", child_id=child_id))
    children.delete_child(db, g.account["id"], child_id)
    flash(f"Deleted {child['name']} and all of their sheets.")
    return redirect(url_for("children.index"))


def _raw(form):
    return {
        "name": form.get("name", ""),
        "grade": form.get("grade", ""),
        "color": form.get("color", ""),
    }
