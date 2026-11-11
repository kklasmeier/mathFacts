"""Settings for the Math Facts app.

Values come from environment variables so secrets and paths stay on the Pi,
not in the repository. Timing and limits follow spec 5.11.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DAY = 24 * 60 * 60


class Config:
    # Shown on the administrator status page. Follows the spec revision.
    APP_VERSION = "1.19"
    # Required outside tests. Set in instance/mathfacts.env on the Pi.
    SECRET_KEY = os.environ.get("SECRET_KEY", "")

    # SQLite file. Lives under instance/, which is never committed.
    DATABASE = os.environ.get(
        "MATHFACTS_DB", str(BASE_DIR / "instance" / "mathfacts.db")
    )

    # Off in Phase 1 (plain HTTP on the home network). Turned on in Phase 2.
    COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

    # Sessions and remembered devices (5.11.3)
    SESSION_IDLE_SECONDS = 12 * 60 * 60
    REMEMBER_SECONDS = 365 * DAY
    DEVICE_COOKIE_SECONDS = 2 * 365 * DAY
    THEME_COOKIE_SECONDS = 365 * DAY
    ROTATION_GRACE_SECONDS = 60

    # Limits (5.11.2, 5.11.3)
    SIGNIN_FAILURE_LIMIT = 5          # per username or email
    SIGNIN_IP_FAILURE_LIMIT = 20      # per network address (shared households)
    SIGNIN_WINDOW_SECONDS = 15 * 60
    REGISTER_LIMIT = 5
    REGISTER_WINDOW_SECONDS = 60 * 60

    # Password hashing (argon2id). Measured on the Pi 4/5 class device:
    # 3 passes at 32 MiB is about 340 ms per check, inside the 200-500 ms target.
    # 64 MiB was about 700 ms, which is too slow on a phone-driven sign-in.
    ARGON2_TIME_COST = 3
    ARGON2_MEMORY_COST = 32 * 1024
    ARGON2_PARALLELISM = 1
