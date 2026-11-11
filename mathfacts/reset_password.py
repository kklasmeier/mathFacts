"""Reset any account's password from the Pi, including the Administrator.

Run this from the app directory when the administrator is locked out:

    .venv/bin/python -m mathfacts.reset_password USERNAME

The new password is typed twice and is not shown. Sessions and remembered
sign-ins for that account are revoked. The account is not forced through the
temporary-password change, so this sign-in works immediately.

The app secret and database path come from instance/mathfacts.env and
MATHFACTS_DB, the same places gunicorn uses.
"""

import getpass
import os
import sys
from pathlib import Path


def _load_env():
    path = Path(__file__).resolve().parent.parent / "instance" / "mathfacts.env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main(argv):
    _load_env()
    if len(argv) < 2 or argv[1].startswith("-"):
        print("Usage: python -m mathfacts.reset_password USERNAME", file=sys.stderr)
        return 2
    username = argv[1]
    if "--password" in argv:
        password = argv[argv.index("--password") + 1]
    else:
        password = getpass.getpass("New password: ")
        again = getpass.getpass("Again: ")
        if password != again:
            print("The passwords do not match.", file=sys.stderr)
            return 1

    from . import create_app, security, settings
    from .db import connect

    app = create_app()
    problems = None
    with app.app_context():
        problems = security.password_problems(password, username)
        if problems:
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1
        db = connect(app.config["DATABASE"])
        try:
            row = settings.recover_password(db, username, password)
            if row is None:
                print(f"No account named {username}.", file=sys.stderr)
                return 1
            db.commit()
        finally:
            db.close()
    print(f"Password reset for {username}. They can sign in with it now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
