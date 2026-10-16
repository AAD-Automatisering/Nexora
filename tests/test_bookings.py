"""Pure calendar preparation, outdoor conditions and measured room rates."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.zonentra.bookings import (
    Booking,
    ThermalRates,
    learn_rate,
    outdoor_band,
    parse_bookings,
    plan_booking,
)

NOW = datetime(2026, 1, 15, 9, tzinfo=timezone.utc)
EVENT = Booking(NOW + timedelta(hours=1), NOW + timedelta(hours=2))


def plan(
    *,
    events=(EVENT,),
    now=NOW,
    temperature=20,
    heat=22,
    cool=24,
    rates=ThermalRates(),
    **kwargs,
):
    return plan_booking(
        events,
        now,
        temperature,
        heat,
        cool,
        0.3,
        rates,
        heating_rate=0.05,
        cooling_rate=0.05,
        buffer_minutes=10,
        max_minutes=180,
        outdoor=kwargs.pop("outdoor", 10),
        **kwargs,
    )


def test_temperature_gap_determines_advance_and_direction():
    heating = plan()
    assert heating.direction == "heating"
    assert heating.lead_minutes == pytest.approx(56)
    assert heating.status == "scheduled"
    assert plan(temperature=18).status == "preparing"
    assert plan(temperature=26).direction == "cooling"
    assert plan(temperature=23).lead_minutes == 10


def test_winter_heating_starts_before_spring_heating():
    winter = plan(outdoor=-5)
    spring = plan(outdoor=15)
    assert winter.prepare_at < spring.prepare_at
    assert winter.lead_minutes > spring.lead_minutes
    assert winter.status == "preparing"
    assert spring.status == "scheduled"


def test_hot_day_cooling_starts_earlier():
    assert (
        plan(temperature=26, outdoor=35).prepare_at
        < plan(temperature=26, outdoor=20).prepare_at
    )


def test_learned_rate_used_only_after_two_samples():
    one = plan(rates=ThermalRates(heating=0.1, heating_samples=1))
    two = plan(rates=ThermalRates(heating=0.1, heating_samples=2))
    assert not one.learned
    assert two.learned
    assert two.lead_minutes == pytest.approx(33)


def test_lead_is_bounded_and_missing_temperature_uses_maximum():
    assert plan(temperature=-10).lead_minutes == 180
    assert plan(temperature=None).lead_minutes == 180
    assert plan(heat=None).lead_minutes == 180
    assert plan(events=None).status == "unknown"
    assert plan(events=()).status == "idle"


def test_preparation_stays_active_after_reaching_comfort():
    first = plan(temperature=18)
    ready = plan(temperature=23, now=NOW + timedelta(minutes=20), previous=first)
    assert ready.active
    assert ready.status == "preparing"
    assert ready.prepare_at == first.prepare_at
    assert plan(events=(), previous=first).status == "idle"


def test_exact_preparation_start_meeting_and_end():
    first = plan()
    assert plan(now=first.prepare_at).status == "preparing"
    assert plan(now=EVENT.start).status == "meeting"
    assert plan(now=EVENT.end).status == "idle"
    assert plan(now=EVENT.start).next_check == EVENT.end


def event(start, end, **extra):
    return {"start": start.isoformat(), "end": end.isoformat(), **extra}


def test_calendar_parsing_timezone_overlap_and_private_content():
    entries = [
        event(
            EVENT.start,
            EVENT.end,
            summary="private subject",
            description="confidential",
        ),
        event(EVENT.start + timedelta(minutes=30), EVENT.end + timedelta(minutes=30)),
        event(EVENT.end + timedelta(minutes=30), EVENT.end + timedelta(hours=1)),
        {"start": "2026-01-15", "end": "2026-01-16", "summary": "all day"},
    ]
    parsed = parse_bookings(entries, ZoneInfo("Europe/Amsterdam"))
    assert parsed == (Booking(EVENT.start, EVENT.end + timedelta(hours=1)),)
    assert "private" not in repr(parsed)
    naive = parse_bookings(
        [{"start": "2026-01-15T10:00:00", "end": "2026-01-15T11:00:00"}],
        ZoneInfo("Europe/Amsterdam"),
    )
    assert naive[0].start.hour == 9


@pytest.mark.parametrize(
    "entries",
    [
        None,
        {},
        [None],
        [{}],
        [{"start": "bad", "end": "bad"}],
        [event(EVENT.end, EVENT.start)],
    ],
)
def test_invalid_response_is_unknown(entries):
    assert parse_bookings(entries, timezone.utc) is None


def test_calendar_timezone_summer_time_and_explicit_offsets():
    summer = parse_bookings(
        [{"start": "2026-07-15T10:00:00+02:00", "end": "2026-07-15T11:00:00+02:00"}],
        ZoneInfo("Europe/Amsterdam"),
    )
    assert summer[0].start.hour == 8


@pytest.mark.parametrize(
    ("outside", "band"),
    [
        (None, "unknown"),
        (-5, "freezing"),
        (5, "cold"),
        (15, "mild"),
        (25, "warm"),
        (35, "hot"),
    ],
)
def test_outdoor_conditions(outside, band):
    assert outdoor_band(outside) == band


def test_learning_separate_heat_and_cool_rates_and_ema():
    rates, sample = learn_rate(ThermalRates(), None, NOW, 18, "heating", -5)
    rates, sample = learn_rate(
        rates, sample, NOW + timedelta(minutes=10), 19, "heating", -5
    )
    assert rates.heating == 0.1
    assert rates.cooling is None
    rates, sample = learn_rate(
        rates, sample, NOW + timedelta(minutes=20), 19.5, "heating", -5
    )
    assert rates.heating == pytest.approx(0.0875)
    assert rates.heating_samples == 2
    rates, sample = learn_rate(
        rates, sample, NOW + timedelta(minutes=30), 25, "cooling", 30
    )
    rates, _ = learn_rate(
        rates, sample, NOW + timedelta(minutes=40), 24.5, "cooling", 30
    )
    assert rates.cooling == 0.05


def test_learning_restarts_when_outdoor_band_or_mode_changes():
    rates, sample = learn_rate(ThermalRates(), None, NOW, 18, "heating", -5)
    rates, _ = learn_rate(rates, sample, NOW + timedelta(minutes=10), 20, "heating", 15)
    assert rates.heating_samples == 0


@pytest.mark.parametrize(
    ("minutes", "temperature", "mode"),
    [
        (1, 19, "heating"),
        (40, 19, "heating"),
        (10, 17, "heating"),
        (10, 30, "heating"),
        (10, None, "heating"),
        (10, 19, "inactive"),
    ],
)
def test_learning_rejects_short_gaps_drift_invalid_and_inactive(
    minutes, temperature, mode
):
    rates, sample = learn_rate(ThermalRates(), None, NOW, 18, "heating", 10)
    changed, _ = learn_rate(
        rates, sample, NOW + timedelta(minutes=minutes), temperature, mode, 10
    )
    assert changed == rates


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"heating": float("nan"), "heating_samples": 3},
        {"heating": True, "heating_samples": 3},
        {"heating": 0.1, "heating_samples": -1},
    ],
)
def test_learning_restore_validates_data(data):
    assert ThermalRates.restore(data) == ThermalRates()


def test_learning_restore_preserves_profiles():
    assert ThermalRates.restore(
        {"heating": 0.03, "heating_samples": 5}
    ) == ThermalRates(heating=0.03, heating_samples=5)
