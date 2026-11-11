"""Entry point for gunicorn: `gunicorn wsgi:app`."""

from mathfacts import create_app

app = create_app()
