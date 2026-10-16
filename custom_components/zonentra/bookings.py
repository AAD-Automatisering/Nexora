"""Pure booking windows and empirical room heating/cooling estimates."""

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone, tzinfo

MIN_SAMPLE_MINUTES = 5
MAX_SAMPLE_MINUTES = 30
MIN_RATE = 0.005  # °C/min; slower/no progress does not yield a usable sample.
MAX_RATE = 0.5
RATE_ALPHA = 0.25
MIN_LEARNED_SAMPLES = 2


def outdoor_band(temperature):
    if temperature is None:
        return "unknown"
    return (
        "freezing"
        if temperature < 0
        else "cold"
        if temperature < 10
        else "mild"
        if temperature < 20
        else "warm"
        if temperature < 30
        else "hot"
    )


def estimated_rate(mode, rates, default, outdoor):
    learned = getattr(rates, mode)
    if learned is not None and getattr(rates, f"{mode}_samples") >= MIN_LEARNED_SAMPLES:
        return learned, True
    # A conservative starting estimate until this outdoor band has samples.
    # This is a bounded heuristic, not a heat-loss or heat-pump capacity model.
    penalty = (
        max(0, 10 - outdoor)
        if mode == "heating" and outdoor is not None
        else max(0, outdoor - 25)
        if outdoor is not None
        else 10
    )
    return default / (1 + 0.03 * penalty), False


@dataclass(frozen=True, order=True)
class Booking:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class ThermalRates:
    heating: float | None = None
    cooling: float | None = None
    heating_samples: int = 0
    cooling_samples: int = 0

    @classmethod
    def restore(cls, data):
        if not isinstance(data, dict):
            return cls()
        values = {}
        for mode in ("heating", "cooling"):
            rate, count = data.get(mode), data.get(f"{mode}_samples")
            if (
                isinstance(rate, (int, float))
                and not isinstance(rate, bool)
                and math.isfinite(rate)
                and MIN_RATE <= rate <= MAX_RATE
                and isinstance(count, int)
                and not isinstance(count, bool)
                and count > 0
            ):
                values[mode], values[f"{mode}_samples"] = rate, count
        return cls(**values)


@dataclass(frozen=True)
class ThermalSample:
    at: datetime
    temperature: float
    mode: str
    outdoor_band: str


def learn_rate(rates, sample, now, temperature, mode, outdoor=None):
    """Learn only from sustained heating/cooling, not passive temperature drift."""
    if (
        temperature is None
        or not math.isfinite(temperature)
        or mode not in ("heating", "cooling")
    ):
        return rates, None
    current = ThermalSample(now, temperature, mode, outdoor_band(outdoor))
    if (
        sample is None
        or sample.mode != mode
        or sample.outdoor_band != current.outdoor_band
        or now <= sample.at
    ):
        return rates, current
    minutes = (now - sample.at).total_seconds() / 60
    if minutes < MIN_SAMPLE_MINUTES:
        return rates, sample
    if minutes > MAX_SAMPLE_MINUTES:
        return rates, current
    change = temperature - sample.temperature
    if change == 0:
        return rates, sample
    rate = (change if mode == "heating" else -change) / minutes
    if not MIN_RATE <= rate <= MAX_RATE:
        return rates, current
    previous = getattr(rates, mode)
    learned = (
        rate if previous is None else previous * (1 - RATE_ALPHA) + rate * RATE_ALPHA
    )
    return replace(
        rates,
        **{mode: learned, f"{mode}_samples": getattr(rates, f"{mode}_samples") + 1},
    ), current


def parse_bookings(events, local_timezone: tzinfo):
    """Keep times only. All-day entries are not timed room reservations."""
    if not isinstance(events, list):
        return None
    result = []
    for event in events:
        if not isinstance(event, dict):
            return None
        start, end = event.get("start"), event.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            return None
        # HA uses ISO dates for all-day entries and ISO datetimes for meetings.
        if len(start) == 10 and len(end) == 10:
            continue
        try:
            start, end = datetime.fromisoformat(start), datetime.fromisoformat(end)
        except ValueError:
            return None
        start = start.replace(tzinfo=local_timezone) if start.tzinfo is None else start
        end = end.replace(tzinfo=local_timezone) if end.tzinfo is None else end
        if end <= start:
            return None
        result.append(
            Booking(start.astimezone(timezone.utc), end.astimezone(timezone.utc))
        )
    # Merge overlapping/back-to-back meetings, so comfort is continuous.
    merged = []
    for event in sorted(set(result)):
        if merged and event.start <= merged[-1].end:
            merged[-1] = Booking(merged[-1].start, max(merged[-1].end, event.end))
        else:
            merged.append(event)
    return tuple(merged)


@dataclass(frozen=True)
class BookingPlan:
    status: str  # not_configured / unknown / idle / scheduled / preparing / meeting
    start: datetime | None = None
    end: datetime | None = None
    prepare_at: datetime | None = None
    lead_minutes: float = 0
    direction: str | None = None
    rate: float | None = None
    learned: bool = False
    next_check: datetime | None = None

    @property
    def active(self):
        return self.status in ("preparing", "meeting")


def plan_booking(
    events,
    now,
    temperature,
    heat,
    cool,
    hysteresis,
    rates,
    *,
    heating_rate,
    cooling_rate,
    buffer_minutes,
    max_minutes,
    previous=None,
    outdoor=None,
):
    """Select the next booking and its bounded adaptive preparation window."""
    if events is None:
        return BookingPlan("unknown")
    event = next((event for event in events if event.end > now), None)
    if event is None:
        return BookingPlan("idle")
    lead, direction, rate, learned = 0, None, None, False
    if temperature is None or heat is None or cool is None:
        # With missing room input, reserve the full horizon; existing sensor
        # validation still prevents unsafe HVAC commands.
        lead = max_minutes
    else:
        if temperature < heat:
            direction = "heating"
            rate, learned = estimated_rate("heating", rates, heating_rate, outdoor)
            distance = heat + hysteresis - temperature
        elif temperature > cool:
            direction = "cooling"
            rate, learned = estimated_rate("cooling", rates, cooling_rate, outdoor)
            distance = temperature - (cool - hysteresis)
        else:
            distance = 0
        lead = min(max_minutes, buffer_minutes + (distance / rate if rate else 0))
    prepare_at = event.start - timedelta(minutes=lead)
    # Once preparation starts, reaching the target must not end comfort early.
    if previous and previous.active and previous.start == event.start:
        prepare_at = max(
            event.start - timedelta(minutes=max_minutes),
            min(previous.prepare_at, prepare_at),
        )
    lead = (event.start - prepare_at).total_seconds() / 60
    status = (
        "meeting"
        if now >= event.start
        else "preparing"
        if now >= prepare_at
        else "scheduled"
    )
    return BookingPlan(
        status,
        event.start,
        event.end,
        prepare_at,
        lead,
        direction,
        rate,
        learned,
        event.end
        if status == "meeting"
        else event.start
        if status == "preparing"
        else prepare_at,
    )
