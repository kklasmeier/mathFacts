"""Public health check and the signed-in home page."""

from flask import Blueprint, jsonify, render_template

bp = Blueprint("web", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.get("/")
def index():
    return render_template("home.html")
