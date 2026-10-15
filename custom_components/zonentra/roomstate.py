"""Pure room state for the zone device (0.10), like Versatile Thermostat.

* window: an open window contact (after a delay) stops the room's demand and,
  with room regulation, switches its units off; a bypass ignores it;
* safety: whether the room temperature can be trusted for regulation;
* trend: an exponentially smoothed temperature (EMA) and its slope in °C/h;
* automatic fan speed: faster the further the room is from its target.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .observations import Reading

WINDOW_STATES = ("closed", "opening", "open", "bypass", "not_configured", "unknown")
EMA_SECONDS = 300.0  # Time constant of the smoothed temperature.
SLOPE_SECONDS = 900.0  # Time constant of the smoothed slope.
STALE_SAMPLE_SECONDS = 600.0  # Re-sample an unchanged value so the slope decays.
AUTO_FAN = "auto"
AUTO_FAN_STEP = 0.5  # °C of distance per fan speed step.


def window_state(
    contacts: tuple[Reading, ...], delay_seconds: float, bypass: bool, now: datetime
) -> tuple[str, datetime | None]:
    """(state, next check). An unknown contact counts as closed."""
    if not contacts:
        return "not_configured", None
    opened = [contact for contact in contacts if contact.value == "open"]
    if not opened:
        if all(contact.quality != "valid" for contact in contacts):
            return "unknown", None
        return "closed", None
    if bypass:
        return "bypass", None
    moments = [contact.changed_at for contact in opened if contact.changed_at]
    if not moments:
        return "open", None
    until = min(moments) + timedelta(seconds=delay_seconds)
    if now < until:
        return "opening", until
    return "open", None


def safety_state(temperature: Reading) -> tuple[str, str]:
    """(safe / sensor_fault, quality): no regulation on an untrusted sensor."""
    if temperature.quality == "valid":
        return "safe", temperature.quality
    return "sensor_fault", temperature.quality


@dataclass(frozen=True)
class Trend:
    ema: float
    slope: float | None  # °C per hour; None until a second sample
    at: datetime


def update_trend(
    trend: Trend | None, value: float, at: datetime, now: datetime
) -> Trend | None:
    """Feed one temperature sample; returns the trend (or None to keep it).

    ``at`` is when the value was last reported. A value that did not change
    for a while is sampled again at ``now``, so the slope returns to zero.
    """
    if trend is None:
        return Trend(value, None, at)
    if at <= trend.at:
        if (now - trend.at).total_seconds() < STALE_SAMPLE_SECONDS:
            return None
        at = now
    seconds = (at - trend.at).total_seconds()
    alpha = 1 - math.exp(-seconds / EMA_SECONDS)
    ema = trend.ema + alpha * (value - trend.ema)
    raw = (ema - trend.ema) / seconds * 3600
    if trend.slope is None:
        slope = raw
    else:
        beta = 1 - math.exp(-seconds / SLOPE_SECONDS)
        slope = trend.slope + beta * (raw - trend.slope)
    return Trend(round(ema, 3), round(slope, 3), at)


def auto_fan(
    speeds: tuple[str, ...],
    mode: str,
    room_temperature: float | None,
    heating_limit: float | None,
    cooling_limit: float | None,
    hysteresis: float,
    step_size: float = AUTO_FAN_STEP,
) -> str | None:
    """Fan speed for the automatic fan: one step per ``step_size`` °C (default
    0.5, a central setting) from the target.

    ``speeds`` are the unit's fan speeds from low to high, without off/auto.
    Without heating or cooling (dry, fan only, unknown) the lowest speed runs.
    """
    if not speeds:
        return None
    distance = 0.0
    if room_temperature is not None:
        if mode == "heat" and heating_limit is not None:
            distance = heating_limit + hysteresis - room_temperature
        elif mode == "cool" and cooling_limit is not None:
            distance = room_temperature - (cooling_limit - hysteresis)
    step = int(max(0.0, distance) / step_size)
    return speeds[min(len(speeds) - 1, step)]


def vane_command(
    entity_id: str, mode: str, cool_value: str | None, heat_value: str | None
) -> tuple[str, str, dict] | None:
    """(domain, service, data) to put a vane in its cooling / heating position."""
    value = cool_value if mode == "cool" else heat_value if mode == "heat" else None
    if not value:
        return None
    domain = entity_id.split(".", 1)[0]
    if domain in ("switch", "input_boolean"):
        # A vane with only auto/stop or swing/stop (KNX 1.001): on or off.
        state = value.strip().lower()
        if state not in ("on", "off"):
            return None
        return domain, f"turn_{state}", {"entity_id": entity_id}
    if domain in ("select", "input_select"):
        return domain, "select_option", {"entity_id": entity_id, "option": value}
    if domain in ("number", "input_number"):
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            return None
        return domain, "set_value", {"entity_id": entity_id, "value": number}
    return None


def vane_mode(modes: set[str]) -> str | None:
    """Heating or cooling position from the running units of a room."""
    if modes & {"cool", "dry"}:
        return "cool"
    if "heat" in modes:
        return "heat"
    return None


def fan_speeds(fan_modes: tuple[str, ...]) -> tuple[str, ...]:
    """The real speeds of a unit, low to high (its own off/auto excluded)."""
    return tuple(mode for mode in fan_modes if mode not in ("off", AUTO_FAN))
