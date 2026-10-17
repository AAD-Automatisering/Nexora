"""Current precipitation and a continuous dry hold for exterior screens."""

from dataclasses import dataclass
from datetime import datetime, timedelta

WET_CONDITIONS = frozenset(
    {"rainy", "pouring", "lightning-rainy", "lightning", "hail", "snowy", "snowy-rainy"}
)
DRY_CONDITIONS = frozenset(
    {"clear-night", "cloudy", "fog", "partlycloudy", "sunny", "windy", "windy-variant"}
)


def current_rain(value, domain):
    """No forecast, probability or accumulated precipitation is rain-now proof."""
    if domain == "binary_sensor":
        return {"on": True, "off": False}.get(value)
    if domain == "weather":
        if value in WET_CONDITIONS:
            return True
        if value in DRY_CONDITIONS:
            return False
    return None


@dataclass(frozen=True)
class RainMemory:
    wet: bool = False
    dry_since: datetime | None = None


@dataclass(frozen=True)
class RainProtection:
    status: str
    memory: RainMemory
    open_required: bool = False
    block_closing: bool = False
    next_check: datetime | None = None


def rain_protection(raining, memory, now, dry_minutes):
    """Missing reports never clear a wet latch or count towards dry stability."""
    if raining is True:
        return RainProtection("rain", RainMemory(True), True, True)
    if raining is None:
        return RainProtection("unknown", RainMemory(memory.wet), memory.wet, True)
    if not memory.wet:
        return RainProtection("dry", RainMemory())
    since = memory.dry_since or now
    until = since + timedelta(minutes=dry_minutes)
    if now < until:
        return RainProtection("drying", RainMemory(True, since), True, True, until)
    return RainProtection("dry", RainMemory())
