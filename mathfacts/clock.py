"""The one place the app reads the time. Tests replace `now` to move time."""

import datetime
import time


def now() -> int:
    return int(time.time())


def local_date(epoch=None):
    """The calendar day for an epoch second, in the machine's timezone."""
    moment = datetime.datetime.fromtimestamp(now() if epoch is None else epoch)
    return moment.date()


def iso_date(epoch=None):
    return local_date(epoch).isoformat()


def parse_date(text):
    try:
        return datetime.date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def start_of_day(day):
    return int(datetime.datetime(day.year, day.month, day.day).timestamp())


def format_day(day):
    return f"{day.strftime('%b')} {day.day}"
