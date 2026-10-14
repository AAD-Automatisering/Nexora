"""0.11.0 pure tests: screens on sunshine, sun position and room climate."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.zonentra.models import build_model
from custom_components.zonentra.shading import (
    ScreenDecision,
    SunMemory,
    decide_screen,
    plan_screen_move,
    sun_on_facade,
    sunny_state,
)

NOW = datetime(2026, 7, 1, 12, tzinfo=UTC)


# --- Sunshine from solar power ------------------------------------------------


def test_sunshine_needs_the_delay_and_clouds_need_longer():
    sunny, memory, check = sunny_state(1500, 1000, SunMemory(), NOW)
    assert (sunny, check) == (False, NOW + timedelta(minutes=5))
    sunny, memory, _ = sunny_state(1500, 1000, memory, NOW + timedelta(minutes=5))
    assert sunny is True
    # A short cloud: still sunny; 70 % of the threshold is the lower edge.
    sunny, memory, check = sunny_state(600, 1000, memory, NOW + timedelta(minutes=6))
    assert sunny is True and check == NOW + timedelta(minutes=21)
    sunny, memory, _ = sunny_state(800, 1000, memory, NOW + timedelta(minutes=7))
    assert sunny is True and memory.pending_since is None  # Back above 700 W.
    sunny, memory, _ = sunny_state(100, 1000, memory, NOW + timedelta(minutes=8))
    sunny, memory, _ = sunny_state(100, 1000, memory, NOW + timedelta(minutes=23))
    assert sunny is False


def test_unknown_power():
    assert sunny_state(None, 1000, SunMemory(True), NOW)[0] is None


# --- Sun on the facade --------------------------------------------------------


@pytest.mark.parametrize(
    ("azimuth", "elevation", "facade", "expected"),
    [
        (100, 30, "east", True),
        (180, 50, "south", True),
        (180, 50, "east", False),  # 90° beside the facade: grazing, no sun.
        (200, 50, "east", False),
        (260, 20, "south", True),
        (275, 20, "south", False),
        (90, 3, "east", False),  # Too low.
        (90, 30, None, None),
        (None, 30, "east", None),
    ],
)
def test_sun_on_facade(azimuth, elevation, facade, expected):
    assert sun_on_facade(azimuth, elevation, facade) is expected


# --- Decision -----------------------------------------------------------------


def decide(**kwargs):
    defaults = {
        "elevation": 40,
        "sunny": True,
        "on_facade": True,
        "demand": "neutral",
        "room_temperature": 22.5,
        "heating_limit": 21.0,
        "cooling_limit": 24.0,
        "shade_position": 0,
        "previous": None,
    }
    return decide_screen(**defaults | kwargs)


@pytest.mark.parametrize(
    ("kwargs", "target", "reason"),
    [
        ({"elevation": -5}, "open", "night"),
        ({"sunny": None}, "hold", "sun_unknown"),
        ({"on_facade": None}, "hold", "sun_unknown"),
        ({"sunny": False}, "open", "no_sun"),
        ({"on_facade": False}, "open", "sun_not_on_facade"),
        ({"demand": "heating_demand"}, "open", "solar_gain_heating"),
        ({"demand": "cooling_demand"}, "shade", "cooling"),
        ({"room_temperature": 23.2}, "shade", "room_warm"),  # Middle 22.5 + 0.5.
        ({"room_temperature": 22.5}, "open", "room_cool"),
        ({"room_temperature": None}, "hold", "room_temperature_unknown"),
    ],
)
def test_decision(kwargs, target, reason):
    decision = decide(**kwargs)
    assert (decision.target, decision.reason) == (target, reason)


def test_positions_and_hysteresis():
    assert decide(demand="cooling_demand", shade_position=20).position == 20
    assert decide(elevation=-1).position == 100
    assert decide(sunny=None).position is None
    # Once shaded it stays down until 0.5 °C below the middle.
    assert decide(room_temperature=22.2, previous="shade").target == "shade"
    assert decide(room_temperature=21.9, previous="shade").target == "open"


# --- Moving -------------------------------------------------------------------

SHADE = ScreenDecision("shade", 0, "cooling")


def move(decision=SHADE, current=100, last=None, **kwargs):
    defaults = {
        "enabled": True,
        "blocked": False,
        "override_until": None,
        "busy": False,
    }
    return plan_screen_move(decision, current, last, NOW, **defaults | kwargs)


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({}, "move"),
        ({"enabled": False}, "simulation"),
        ({"blocked": True}, "blocked"),
        ({"override_until": NOW + timedelta(minutes=5)}, "manual_override"),
        ({"current": 5}, "in_position"),
        ({"busy": True}, "waiting_for_confirmation"),
        ({"last": NOW - timedelta(minutes=5)}, "interval"),
        ({"last": NOW - timedelta(minutes=16)}, "move"),
        ({"override_until": NOW - timedelta(minutes=1)}, "move"),
        ({"decision": ScreenDecision("hold", None, "sun_unknown")}, "hold"),
    ],
)
def test_move(kwargs, status):
    assert move(**kwargs).status == status


def test_move_position_and_next_check():
    assert move().position == 0
    assert move(last=NOW - timedelta(minutes=5)).next_check == NOW + timedelta(
        minutes=10
    )


# --- Configuration ------------------------------------------------------------


def screens(**settings):
    return build_model(
        "b",
        "B",
        {
            "building": settings,
            "zones": [{"id": "r", "name": "R", "facade": "south"}],
            "equipment": [
                {
                    "id": "shade_r",
                    "name": "Screen",
                    "kind": "shading",
                    "entity_id": "cover.r_screen",
                    "zone_id": "r",
                }
            ],
        },
    )


def test_screen_settings_and_tracked_entities():
    model = screens(sun_power_entity="sensor.solar_power")
    assert model.zones[0].facade == "south"
    assert {"sun.sun", "sensor.solar_power", "cover.r_screen"} <= model.entity_ids
    assert "sun.sun" not in build_model("b", "B", {}).entity_ids  # Only with screens.


@pytest.mark.parametrize(
    "settings",
    [
        {"sun_power_entity": "binary_sensor.x"},
        {"screen_shade_position": 120},
        {"screen_override_minutes": 1},
        {"screen_block_entity": "sensor.wind"},
    ],
)
def test_invalid_screen_settings(settings):
    with pytest.raises(ValueError):
        screens(**settings)


def test_invalid_facade():
    with pytest.raises(ValueError, match="invalid_parameters"):
        build_model("b", "B", {"zones": [{"id": "r", "name": "R", "facade": "up"}]})
