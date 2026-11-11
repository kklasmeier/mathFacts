"""Settings for the Math Facts app.

Values come from environment variables so secrets and paths stay on the Pi,
not in the repository.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    # Required outside tests. Set in instance/mathfacts.env on the Pi.
    SECRET_KEY = os.environ.get("SECRET_KEY", "")

    # SQLite file. Lives under instance/, which is never committed.
    DATABASE = os.environ.get(
        "MATHFACTS_DB", str(BASE_DIR / "instance" / "mathfacts.db")
    )

    # Off in Phase 1 (plain HTTP on the home network). Turned on in Phase 2.
    COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
