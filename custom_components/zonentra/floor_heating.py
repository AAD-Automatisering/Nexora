"""Observe inadequate room warming without increasing gas heating."""

from dataclasses import dataclass
from datetime import datetime, timedelta

WATCH_MINUTES = 60
MINIMUM_RISE = 0.3
MINIMUM_DEFICIT = 1.0


@dataclass(frozen=True)
class HeatingWatch:
    since: datetime
    temperature: float
    reported_at: datetime | None
    target: float


@dataclass(frozen=True)
class HeatingProgress:
    status: str
    memory: HeatingWatch | None = None
    next_check: datetime | None = None
    rise: float | None = None


def heating_progress(previous, now, *, temperature, target, reported_at, watching):
    """Signal only with continuous reported heating and a newer room report.

    This is a room comfort observation, not an efficiency/fault measurement.
    Gas targets and HVAC commands are never changed by this signal.
    """
    if not watching:
        return HeatingProgress("idle")
    if temperature is None or target is None:
        return HeatingProgress("unknown")
    if target - temperature < MINIMUM_DEFICIT:
        return HeatingProgress("adequate")
    memory = (
        previous
        if previous and previous.target == target
        else HeatingWatch(now, temperature, reported_at, target)
    )
    deadline = memory.since + timedelta(minutes=WATCH_MINUTES)
    rise = round(temperature - memory.temperature, 3)
    if now < deadline:
        return HeatingProgress("monitoring", memory, deadline, rise)
    if (
        reported_at is None
        or reported_at <= memory.since
        or (memory.reported_at is not None and reported_at <= memory.reported_at)
    ):
        return HeatingProgress("unknown", memory, rise=rise)
    if rise < MINIMUM_RISE:
        return HeatingProgress("insufficient", memory, rise=rise)
    return HeatingProgress(
        "monitoring",
        HeatingWatch(now, temperature, reported_at, target),
        now + timedelta(minutes=WATCH_MINUTES),
        rise,
    )
