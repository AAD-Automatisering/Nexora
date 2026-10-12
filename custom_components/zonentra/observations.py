"""Pure immutable readings and unit/age validation; no Home Assistant imports."""

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceState:
    state: str | None
    unit: str | None = None
    reported_at: datetime | None = None
    trustworthy: bool = True


@dataclass(frozen=True)
class Reading:
    value: float | str | None
    quality: str
    reported_at: datetime | None = None


def read(
    source: SourceState | None, kind: str, now: datetime, max_age: float = 0
) -> Reading:
    """Validate explicit units and freshness without guessing missing values."""
    if source is None:
        return Reading(None, "missing")
    if source.state in (None, "unknown", "unavailable"):
        return Reading(None, source.state or "unknown", source.reported_at)
    timestamp = source.reported_at
    if not source.trustworthy:
        return Reading(None, "unreliable", timestamp)
    if (
        timestamp is None
        or timestamp.tzinfo is None
        or (timestamp - now).total_seconds() > 5
    ):
        return Reading(None, "unreliable", timestamp)
    if max_age and (now - timestamp).total_seconds() >= max_age:
        return Reading(None, "stale", timestamp)
    if kind in ("occupancy", "contact"):
        value = {
            "on": "occupied" if kind == "occupancy" else "open",
            "off": "unoccupied" if kind == "occupancy" else "closed",
        }.get(source.state)
        return Reading(value, "valid" if value else "unreliable", timestamp)
    if kind == "mode":
        value = source.state if source.state in ("heat", "cool", "off") else None
        return Reading(value, "valid" if value else "unreliable", timestamp)
    try:
        value = float(source.state)
    except TypeError, ValueError:
        return Reading(None, "unreliable", timestamp)
    if not math.isfinite(value):
        return Reading(None, "unreliable", timestamp)
    unit = source.unit
    if kind in ("temperature", "limit"):
        if unit == "°F":
            value = (value - 32) * 5 / 9
        elif unit != "°C":
            return Reading(None, "unreliable", timestamp)
        low, high = (-50, 65) if kind == "temperature" else (5, 35)
    elif kind == "humidity":
        low, high = 0, 100
        if unit != "%":
            return Reading(None, "unreliable", timestamp)
    elif kind == "co2":
        low, high = 0, 10000
        if unit != "ppm":
            return Reading(None, "unreliable", timestamp)
    else:
        raise ValueError(f"Unknown reading kind: {kind}")
    return Reading(
        value if low <= value <= high else None,
        "valid" if low <= value <= high else "unreliable",
        timestamp,
    )


def configured_limit(value: float | None) -> Reading:
    """Static UI limits are in Celsius and do not expire."""
    return Reading(value, "valid" if value is not None else "missing")
