"""`--wait-on-limit`: sleep until the Claude subscription's usage limit resets, then carry on in the same process."""

import re
import time
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click

# When the reset time can't be read from the message (e.g. "resets Oct 3", "resets Mon", none at all).
BACKOFF_S = 15 * 60
# Slept past the reset time, so the first call after it isn't refused on a clock that is a little behind.
MARGIN_S = 60
# A reset time of day that passed this recently is the limit about to clear (the message rounds it), not
# tomorrow's: it waits the back-off instead.
JUST_PASSED = timedelta(hours=1)

# "resets 9:50pm (Pacific/Honolulu)", "resets 3:40am (UTC)", "resets 3pm": a time of day, with its zone when
# Claude Code names one (the machine's local time otherwise). A date or weekday ("resets Oct 3") isn't parsed.
RESET = re.compile(
    r"\bresets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b\.?(?:\s*\(([^)]+)\))?", re.IGNORECASE
)


def _now() -> datetime:
    return datetime.now().astimezone()


def reset_time(message: str, now: datetime) -> datetime | None:
    """When a usage-limit message says the limit resets, as the next such time after `now` (aware), or None.

    Instants are compared in UTC: aware datetimes in one zone subtract by wall clock, which is off by the
    shift across a DST change. A wall time that happens twice (fall back) is taken as the later one, so the
    wait never ends before the reset."""
    m = RESET.search(message)
    if not m:
        return None
    hour, minute = int(m[1]), int(m[2] or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if m[3].lower() == "p" else 0)
    zone = None
    if m[4]:
        try:
            zone = ZoneInfo(m[4].strip())
        except (ZoneInfoNotFoundError, ValueError):
            return None

    def at(day) -> datetime:
        """That wall time on `day`, in the named zone or else local time (with its DST rules)."""
        wall = datetime.combine(day, dt_time(hour, minute, fold=1))
        return wall.replace(tzinfo=zone) if zone else wall.astimezone()

    reset = at(now.astimezone(zone).date())
    if reset.astimezone(UTC) <= now.astimezone(UTC):
        if now.astimezone(UTC) - reset.astimezone(UTC) < JUST_PASSED:
            return None
        # The same wall time tomorrow (not 24 hours on: a DST change in between moves it).
        reset = at(reset.date() + timedelta(days=1))
    return reset


class LimitWaiter:
    """Waits out usage limits, `max_wait_s` in all. `wait` returns False (without sleeping) when the next wait
    would go past that."""

    def __init__(self, max_wait_s: float, backoff_s: float = BACKOFF_S):
        self.left = max_wait_s
        self.backoff_s = backoff_s

    def wait(self, message: str) -> bool:
        now = _now()
        reset = reset_time(message, now)
        seconds = (
            (reset.astimezone(UTC) - now.astimezone(UTC)).total_seconds() + MARGIN_S
            if reset
            else self.backoff_s
        )
        until = (now.astimezone(UTC) + timedelta(seconds=seconds)).astimezone(now.tzinfo)
        if seconds > self.left:
            click.echo(
                f"Usage limit: waiting until {until:%Y-%m-%d %H:%M %Z} would pass --max-wait "
                f"({self.left / 60:.0f} min left); stopping.",
                err=True,
            )
            return False
        self.left -= seconds
        why = f"it resets {reset:%H:%M %Z}" if reset else "no reset time in the message: fixed back-off"
        click.echo(
            f"Usage limit ({message[:200]}): waiting {seconds / 60:.0f} min, until {until:%Y-%m-%d %H:%M %Z} "
            f"({why}), then resuming. Ctrl-C to stop; `--resume` continues later.",
            err=True,
        )
        time.sleep(seconds)
        return True
