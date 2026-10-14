"""0.8.0 pure tests: building presence and zone motion (like Versatile Thermostat)."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.zonentra.demand import calculate_demand, collect_zone
from custom_components.zonentra.models import build_model
from custom_components.zonentra.observations import SourceState
from custom_components.zonentra.presence import (
    MotionMemory,
    motion_state,
    occupancy,
    read_presence,
)

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)


def state(value, ago=timedelta(hours=1), trusted=True):
    return SourceState(value, None, NOW, trusted, NOW - ago)


@pytest.mark.parametrize(
    ("entity_id", "value", "expected"),
    [
        ("binary_sensor.office_occupied", "on", "present"),
        ("binary_sensor.office_occupied", "off", "absent"),
        ("input_boolean.office_open", "on", "present"),
        ("alarm_control_panel.office", "disarmed", "present"),
        ("alarm_control_panel.office", "armed_away", "absent"),
        ("alarm_control_panel.office", "armed_night", "absent"),
        ("alarm_control_panel.office", "pending", "unknown"),
        ("person.employee", "home", "present"),
        ("person.employee", "not_home", "absent"),
        ("person.employee", "Shop", "absent"),
        ("group.staff", "home", "present"),
        ("group.staff", "on", "present"),
        ("group.staff", "not_home", "absent"),
        ("zone.office", "3", "present"),
        ("zone.office", "0", "absent"),
        ("binary_sensor.office_occupied", "unavailable", "unknown"),
    ],
)
def test_presence_sources(entity_id, value, expected):
    assert read_presence(entity_id, state(value)) == expected


def test_presence_not_configured_missing_or_untrusted():
    assert read_presence(None, None) == "not_configured"
    assert read_presence("binary_sensor.x", None) == "unknown"
    assert read_presence("binary_sensor.x", state("on", trusted=False)) == "unknown"


def motion(value, ago, memory=MotionMemory(), now=NOW):
    return motion_state("binary_sensor.motion", state(value, ago), memory, 30, 30, now)


def test_motion_must_last_the_detection_delay():
    result, memory, check = motion("on", timedelta(seconds=10))
    assert (result, memory.confirmed) == ("inactive", False)
    assert check == NOW + timedelta(seconds=20)
    result, memory, check = motion("on", timedelta(seconds=30))
    assert (result, memory.confirmed, check) == ("active", True, None)


def test_motion_stays_active_for_the_off_delay():
    confirmed = MotionMemory(True)
    result, memory, check = motion("off", timedelta(minutes=10), confirmed)
    assert (result, memory.confirmed) == ("active", True)
    assert check == NOW + timedelta(minutes=20)
    result, memory, check = motion("off", timedelta(minutes=30), confirmed)
    assert (result, memory.confirmed, check) == ("inactive", False, None)
    # A short passage that never got confirmed does not count afterwards.
    result, _, _ = motion("off", timedelta(minutes=1))
    assert result == "inactive"


@pytest.mark.parametrize(
    ("entity", "source", "expected"),
    [
        (None, None, "not_configured"),
        ("binary_sensor.motion", None, "unknown"),
        ("binary_sensor.motion", state("unavailable"), "unknown"),
    ],
)
def test_motion_without_usable_sensor(entity, source, expected):
    assert motion_state(entity, source, MotionMemory(), 30, 30, NOW)[0] == expected


@pytest.mark.parametrize(
    ("presence", "motion_value", "mode", "reason"),
    [
        ("absent", "active", "away", "building_absent"),
        ("absent", "not_configured", "away", "building_absent"),
        ("present", "inactive", "eco", "no_motion"),
        ("present", "active", "comfort", "motion"),
        ("present", "not_configured", "comfort", "present"),
        ("unknown", "inactive", "eco", "no_motion"),
        ("unknown", "unknown", "comfort", "motion_sensor_unknown"),
        ("not_configured", "not_configured", "comfort", "default"),
    ],
)
def test_presence_wins_over_motion(presence, motion_value, mode, reason):
    result = occupancy(presence, motion_value)
    assert (result.mode, result.reason) == (mode, reason)


def building(**settings):
    return build_model(
        "building",
        "Building",
        {
            "building": {
                "heating_limit": 21,
                "cooling_limit": 24,
                "hysteresis": 0.3,
                **settings,
            },
            "zones": [
                {
                    "id": "office",
                    "name": "Office",
                    "temperature_entity": "sensor.office",
                    "use_building_limits": True,
                    "use_building_parameters": True,
                }
            ],
            "groups": [],
            "equipment": [],
        },
    )


@pytest.mark.parametrize(
    ("band", "limits", "demand"),
    [
        ("comfort", (21, 24), "heating_demand"),
        ("eco", (19, 26), "neutral"),
        ("away", (16, 30), "neutral"),
    ],
)
def test_band_replaces_the_limits(band, limits, demand):
    model = building()
    zone = model.zones[0]
    sources = {"sensor.office": SourceState("20", "°C", NOW)}
    snapshot = collect_zone(model, zone, sources, NOW, band=band)
    assert (snapshot.heating_limit.value, snapshot.cooling_limit.value) == limits
    assert calculate_demand(zone, snapshot).demand == demand


def test_bands_are_configurable_and_validated():
    model = building(eco_heating_limit=18, eco_cooling_limit=27)
    assert (model.settings.eco_heating_limit, model.settings.eco_cooling_limit) == (
        18,
        27,
    )
    with pytest.raises(ValueError, match="invalid_limits"):
        building(away_heating_limit=25, away_cooling_limit=25)
    with pytest.raises(ValueError, match="invalid_entity"):
        building(presence_entity="light.office")
    with pytest.raises(ValueError, match="invalid_parameters"):
        building(motion_off_delay_minutes=0)
    assert building(presence_entity="alarm_control_panel.office").settings
