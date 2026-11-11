"""The one place the app reads the time. Tests replace `now` to move time."""

import time


def now() -> int:
    return int(time.time())
