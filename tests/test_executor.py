"""0.7.0 pure tests: planning of the outdoor unit stand (active mode control)."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.zonentra.executor import (
    PresetMemory,
    next_correction_check,
    plan_mode_commands,
)
from custom_components.zonentra.indoor import observe_unit
from custom_components.zonentra.models import Equipment
from custom_components.zonentra.observations import ClimateAttributes, SourceState

NOW = datetime(2026, 10, 14, 14, tzinfo=UTC)
LONG_AGO = NOW - timedelta(hours=2)


def units(**modes):
    observed, entities, changed = [], {}, {}
    for name, value in modes.items():
        state, since = value if isinstance(value, tuple) else (value, LONG_AGO)
        item = Equipment(name, name, "hvac", f"climate.{name}", "zone", "group")
        source = (
            None
            if state is None
            else SourceState(
                state, None, NOW, changed_at=since, climate=ClimateAttributes()
            )
        )
        observed.append(observe_unit(item, source))
        entities[name] = item.entity_id
        changed[name] = since
    return tuple(observed), entities, changed


def plan(group_mode, memory=PresetMemory(), now=NOW, enabled=True, **modes):
    observed, entities, changed = units(**modes)
    return plan_mode_commands(
        "group",
        group_mode,
        observed,
        entities,
        changed,
        memory,
        900,
        now,
        enabled=enabled,
    )


def summary(control):
    return [
        (c.equipment_id, c.service, c.hvac_mode, c.delay_seconds, c.reason)
        for c in control.commands
    ]


def test_first_run_presets_every_unit():
    control, memory = plan("heat", a="off", b="off")
    assert control.status == "group_mode_applied"
    assert summary(control) == [
        ("a", "set_hvac_mode", "heat", 0, "preset_pulse"),
        ("a", "turn_off", None, 3, "preset_pulse"),
        ("b", "set_hvac_mode", "heat", 0, "preset_pulse"),
        ("b", "turn_off", None, 3, "preset_pulse"),
    ]
    assert (memory.mode, memory.changed_at) == ("heat", NOW)


def test_group_change_switches_running_units_and_presets_off_units():
    memory = PresetMemory("heat", LONG_AGO)
    control, memory = plan(
        "cool", memory, running="heat", idle="off", fan="fan_only", already="cool"
    )
    assert summary(control) == [
        ("running", "set_hvac_mode", "cool", 0, "switch_running_unit"),
        ("idle", "set_hvac_mode", "cool", 0, "preset_pulse"),
        ("idle", "turn_off", None, 3, "preset_pulse"),
    ]
    assert memory.mode == "cool"


def test_minimum_switch_interval_blocks_group_change():
    memory = PresetMemory("heat", NOW - timedelta(minutes=5))
    control, new_memory = plan("cool", memory, a="heat")
    assert control.status == "minimum_switch_interval"
    assert control.commands == ()
    assert control.blocked_until == NOW + timedelta(minutes=10)
    assert new_memory == memory


@pytest.mark.parametrize(
    ("mode", "status"), [("neutral", "neutral"), ("unknown", "no_group_mode")]
)
def test_no_mode_is_invented(mode, status):
    control, memory = plan(mode, PresetMemory("heat", LONG_AGO), a="off")
    assert control.status == status and control.commands == ()
    assert memory.mode == "heat"  # The last preset stays.


@pytest.mark.parametrize(
    ("enabled", "status"), [(False, "disabled"), (None, "waiting_for_switch_state")]
)
def test_switch_off_or_unknown_means_no_commands(enabled, status):
    control, memory = plan("heat", enabled=enabled, a="off")
    assert control.status == status and control.commands == ()
    assert memory == PresetMemory()


def test_unavailable_units_are_skipped():
    control, _ = plan("heat", a="off", b="unavailable", c=None)
    assert [c.equipment_id for c in control.commands] == ["a", "a"]


def test_wrong_mode_running_unit_is_corrected_after_delay():
    memory = PresetMemory("heat", LONG_AGO)
    fresh = (NOW - timedelta(seconds=10),)
    control, _ = plan("heat", memory, manual=("cool", fresh[0]))
    assert control.status == "in_sync" and control.commands == ()
    observed, _, changed = units(manual=("cool", fresh[0]))
    assert next_correction_check(observed, changed, memory, "heat", NOW) == fresh[
        0
    ] + timedelta(seconds=30)
    control, memory = plan("heat", memory, manual=("cool", NOW - timedelta(seconds=30)))
    assert summary(control) == [
        ("manual", "set_hvac_mode", "heat", 0, "correct_running_unit")
    ]
    # Not again within two minutes, even if the unit stays wrong.
    later = NOW + timedelta(seconds=60)
    control, memory = plan(
        "heat", memory, later, manual=("cool", NOW - timedelta(seconds=30))
    )
    assert control.commands == ()
    control, _ = plan(
        "heat",
        memory,
        NOW + timedelta(seconds=121),
        manual=("cool", NOW - timedelta(seconds=30)),
    )
    assert len(control.commands) == 1


@pytest.mark.parametrize(
    ("target", "mode"), [("heat", "fan_only"), ("cool", "dry"), ("cool", "fan_only")]
)
def test_compatible_running_modes_are_left_alone(target, mode):
    control, _ = plan(target, PresetMemory(target, LONG_AGO), a=mode)
    assert control.commands == ()


@pytest.mark.parametrize("mode", ["auto", "heat_cool", "dry"])
def test_ambiguous_modes_follow_heat_group(mode):
    control, _ = plan("heat", PresetMemory("heat", LONG_AGO), a=mode)
    assert summary(control) == [
        ("a", "set_hvac_mode", "heat", 0, "correct_running_unit")
    ]
