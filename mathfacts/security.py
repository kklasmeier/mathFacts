"""Password hashing, tokens, and input rules (spec 5.11.2, 5.11.3)."""

import functools
import hashlib
import re
import secrets
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import current_app

MIN_PASSWORD = 10
MAX_PASSWORD = 128

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")

COMMON_FILE = Path(__file__).parent / "data" / "common_passwords.txt"


def _hasher():
    cfg = current_app.config
    return PasswordHasher(
        time_cost=cfg["ARGON2_TIME_COST"],
        memory_cost=cfg["ARGON2_MEMORY_COST"],
        parallelism=cfg["ARGON2_PARALLELISM"],
    )


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(stored_hash: str, password: str):
    """Return (matches, needs_rehash). Never raises on a wrong password."""
    hasher = _hasher()
    try:
        matches = hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False, False
    return matches, hasher.check_needs_rehash(stored_hash)


def burn_time(password: str) -> None:
    """Do roughly the same work as a real check, for unknown accounts."""
    hash_password(password)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


@functools.lru_cache(maxsize=1)
def common_passwords() -> frozenset:
    lines = COMMON_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip().lower()
        for line in lines
        if line.strip() and not line.startswith("#")
    )


def password_problems(password: str, username: str = "", email: str = "") -> list:
    problems = []
    if len(password) < MIN_PASSWORD:
        problems.append(f"Use at least {MIN_PASSWORD} characters. A phrase is fine.")
    if len(password) > MAX_PASSWORD:
        problems.append(f"Use {MAX_PASSWORD} characters or fewer.")
    lowered = password.lower()
    if lowered in common_passwords():
        problems.append("That password is too common. Try a longer phrase.")
    if (username and lowered == username.lower()) or (
        email and lowered == email.lower()
    ):
        problems.append("Your password cannot be your username or email.")
    return problems


def valid_email(value: str) -> bool:
    return len(value) <= 254 and bool(EMAIL_RE.match(value))


def valid_username(value: str) -> bool:
    return bool(USERNAME_RE.match(value))
