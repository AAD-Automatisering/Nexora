"""Pure screen (exterior sun shading) logic (0.11). Climate weighs most.

Per screen, in order:

1. night (sun below the horizon): up;
2. sun unknown: hold;
3. no sun (solar power below the threshold, with delays against clouds) or
   the sun not on the screen's facade: up (daylight);
4. sun on the facade: the room decides. Heating demand: up (free solar
   heat); cooling demand: down;
5. (0.12, energy first, with a forecast) an empty room (eco or away band):
   down on a warm or neutral day (no heat to cool away later), up on a cold day (free heat);
6. an occupied room on a warm day: down already (before the room warms up);
   on a cold day: up (solar heat saves gas);
7. otherwise down when the room is in the warm half of its band, up in the
   cold half (with hysteresis).

Wind/rain alarms stay with KNX; a block entity stops all commands. A person
moving a screen (Home Assistant or room controller) is respected for the
manual override time. HA cover positions: 100 = open (up), 0 = closed (down).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

FACADES = {
    "north": 0,
    "northeast": 45,
    "east": 90,
    "southeast": 135,
    "south": 180,
    "southwest": 225,
    "west": 270,
    "northwest": 315,
}
FACADE_ANGLE = 80.0  # Sun at most this far beside the facade normal.
MIN_ELEVATION = 5.0  # Low sun is blocked by surroundings.
SUNNY_DELAY_SECONDS = 300.0  # Bright this long before "sunny".
CLOUDY_DELAY_SECONDS = 900.0  # Dim this long before "not sunny".
CLOUDY_FACTOR = 0.7  # "Dim" = below 70 % of the threshold (hysteresis).
MOVE_INTERVAL_SECONDS = 900.0  # At most one move per screen per 15 min.
MIN_STEP = 10  # Ignore position differences below 10 %.
OPEN_POSITION = 100
WARM_HYSTERESIS = 0.5  # °C around the middle of the band.


@dataclass(frozen=True)
class SunMemory:
    sunny: bool = False
    pending_since: datetime | None = None


def sunny_state(
    power: float | None, threshold: float, memory: SunMemory, now: datetime
) -> tuple[bool | None, SunMemory, datetime | None]:
    """(sunny or None if unknown, memory, next check) from solar power."""
    if power is None:
        return None, memory, None
    if memory.sunny:
        changing = power < threshold * CLOUDY_FACTOR
        delay = CLOUDY_DELAY_SECONDS
    else:
        changing = power >= threshold
        delay = SUNNY_DELAY_SECONDS
    if not changing:
        return memory.sunny, SunMemory(memory.sunny), None
    since = memory.pending_since or now
    until = since + timedelta(seconds=delay)
    if now >= until:
        return not memory.sunny, SunMemory(not memory.sunny), None
    return memory.sunny, SunMemory(memory.sunny, since), until


def sun_on_facade(
    azimuth: float | None, elevation: float | None, facade: str | None
) -> bool | None:
    """Whether the sun shines on a facade; None when it cannot be told."""
    if azimuth is None or elevation is None or facade not in FACADES:
        return None
    if elevation < MIN_ELEVATION:
        return False
    difference = abs((azimuth - FACADES[facade] + 180) % 360 - 180)
    return difference <= FACADE_ANGLE


@dataclass(frozen=True)
class ScreenDecision:
    target: str  # open / shade / hold
    position: int | None
    reason: str


def decide_screen(
    *,
    elevation: float | None,
    sunny: bool | None,
    on_facade: bool | None,
    demand: str,
    room_temperature: float | None,
    heating_limit: float | None,
    cooling_limit: float | None,
    shade_position: int,
    previous: str | None,
    day: str = "unknown",
    occupied: bool = True,
) -> ScreenDecision:
    def result(target, reason):
        position = {"open": OPEN_POSITION, "shade": shade_position}.get(target)
        return ScreenDecision(target, position, reason)

    if elevation is not None and elevation < 0:
        return result("open", "night")
    if sunny is None or on_facade is None:
        return result("hold", "sun_unknown")
    if not sunny:
        return result("open", "no_sun")
    if not on_facade:
        return result("open", "sun_not_on_facade")
    if demand == "heating_demand":
        return result("open", "solar_gain_heating")
    if demand == "cooling_demand":
        return result("shade", "cooling")
    if not occupied and day != "unknown":
        if day == "cold":
            return result("open", "empty_room_solar_gain")
        return result("shade", "empty_room_keep_cool")
    if day == "warm":
        return result("shade", "warm_day_forecast")
    if day == "cold":
        return result("open", "cold_day_forecast")
    if room_temperature is None or heating_limit is None or cooling_limit is None:
        return result("hold", "room_temperature_unknown")
    middle = (heating_limit + cooling_limit) / 2
    if previous == "shade":
        warm = room_temperature >= middle - WARM_HYSTERESIS
    else:
        warm = room_temperature >= middle + WARM_HYSTERESIS
    return result("shade", "room_warm") if warm else result("open", "room_cool")


@dataclass(frozen=True)
class ScreenMove:
    status: str
    position: int | None = None
    next_check: datetime | None = None


def plan_screen_move(
    decision: ScreenDecision,
    current: int | None,
    last_move_at: datetime | None,
    now: datetime,
    *,
    enabled: bool,
    blocked: bool,
    override_until: datetime | None,
    busy: bool,
) -> ScreenMove:
    """Whether to move a screen now (only with screen regulation on)."""
    if decision.position is None:
        return ScreenMove("hold")
    if not enabled:
        return ScreenMove("simulation")
    if blocked:
        return ScreenMove("blocked")
    if override_until is not None and now < override_until:
        return ScreenMove("manual_override", next_check=override_until)
    if current is not None and abs(current - decision.position) < MIN_STEP:
        return ScreenMove("in_position")
    if busy:
        return ScreenMove("waiting_for_confirmation")
    if last_move_at is not None:
        allowed = last_move_at + timedelta(seconds=MOVE_INTERVAL_SECONDS)
        if now < allowed:
            return ScreenMove("interval", next_check=allowed)
    return ScreenMove("move", decision.position)
