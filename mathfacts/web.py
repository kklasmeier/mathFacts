"""Routes for slice 0: a health check and a holding page.

Sign-in, sheets, and the rest arrive in later slices.
"""

from flask import Blueprint, Response, jsonify

bp = Blueprint("web", __name__)

HOLDING_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Math Facts</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; background: #faf7f2; color: #222; }
    main { max-width: 36rem; margin: 15vh auto; padding: 0 1.5rem; }
    h1 { font-weight: 600; }
  </style>
</head>
<body>
  <main>
    <h1>Math Facts</h1>
    <p>The site is starting up. Sign-in arrives in the next release.</p>
  </main>
</body>
</html>
"""


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.get("/")
def index():
    return Response(HOLDING_PAGE, mimetype="text/html")
