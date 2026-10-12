"""0.4.0 pure tests: indoor unit observation and outdoor-group mode detection."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.zonentra.demand import calculate_demand, collect_zone
from custom_components.zonentra.engine import GroupMemory, evaluate
from custom_components.zonentra.indoor import (
    compare_modes,
    detect_group_mode,
    observe_group,
    observe_unit,
)
from custom_components.zonentra.models import Equipment, build_model
from custom_components.zonentra.observations import ClimateAttributes, SourceState

NOW = datetime(2026, 10, 12, 14, tzinfo=UTC)
MISSING = object()


def climate(state, action=MISSING, **attributes):
    """A climate entity; action=MISSING omits hvac_action entirely."""
    return SourceState(
        state,
        None,
        NOW,
        climate=ClimateAttributes(
            None if action is MISSING else action,
            attributes.get("current", 21),
            attributes.get("target", 26),
            attributes.get("fan", "50%"),
            "°C",
            NOW,
        ),
        trustworthy=attributes.get("trustworthy", True),
    )


def building(units=1, mode_entity=None):
    zones = [
        {
            "id": f"room_{i}",
            "name": f"Room {i}",
            "temperature_entity": f"sensor.room_{i}",
            "group_id": "outdoor_1",
            "heating_limit": 22,
            "cooling_limit": 24,
        }
        for i in range(units)
    ]
    return build_model(
        "building",
        "Building",
        {
            "zones": zones,
            "groups": [
                {"id": "outdoor_1", "name": "Outdoor 1", "mode_entity": mode_entity}
            ],
            "equipment": [
                {
                    "id": f"unit_{i}",
                    "name": f"Unit {i}",
                    "kind": "hvac",
                    "entity_id": f"climate.unit_{i}",
                    "zone_id": f"room_{i}",
                }
                for i in range(units)
            ],
        },
    )


def observe(*states):
    model = building(len(states))
    sources = {f"climate.unit_{i}": state for i, state in enumerate(states) if state}
    return observe_group(model, model.groups[0], sources)


def group(*states):
    return observe(*states)[1]


# 1-6: single indoor unit.
@pytest.mark.parametrize(
    ("state", "action", "consensus", "activity", "derived", "reason"),
    [
        ("off", "off", "off", "inactive", "inactive", "all_units_off"),
        ("heat", MISSING, "heat", "unknown", "heat", "heat_selected"),
        ("cool", MISSING, "cool", "unknown", "cool", "cool_selected"),
        ("heat", "idle", "heat", "inactive", "heat", "heat_selected"),
        (
            "heat",
            "heating",
            "heat",
            "heating",
            "heat",
            "heat_selected_heating_reported",
        ),
        (
            "cool",
            "cooling",
            "cool",
            "cooling",
            "cool",
            "cool_selected_cooling_reported",
        ),
    ],
)
def test_single_unit(state, action, consensus, activity, derived, reason):
    units, observation = observe(climate(state, action))
    assert units[0].selected_mode == state
    assert units[0].mismatch is False  # heat + idle is normal, not a conflict.
    assert observation.selected_consensus == consensus
    assert observation.reported_activity == activity
    assert observation.derived_mode == derived
    assert observation.reason == reason
    assert observation.conflict is False
    assert observation.member_units == observation.available_units == 1


def test_unit_attributes_are_read_not_guessed():
    unit = observe_unit(
        Equipment("u", "Unit", "hvac", "climate.u", "room", "outdoor_1"),
        climate("heat", "idle", current="21.5", target=None, fan="auto"),
    )
    assert (unit.selected_mode, unit.reported_action) == ("heat", "idle")
    assert unit.current_temperature == 21.5
    assert unit.target_temperature is None
    assert unit.fan_mode == "auto"
    assert unit.availability == "available"
    assert unit.quality == "complete"
    assert unit.observed_at == NOW.isoformat()


# 7, 8, 10: several units agree.
@pytest.mark.parametrize(
    ("state", "action", "derived"),
    [
        ("heat", "heating", "heat"),
        ("cool", "cooling", "cool"),
        ("off", "off", "inactive"),
    ],
)
def test_multiple_units_agree(state, action, derived):
    observation = group(*(climate(state, action) for _ in range(3)))
    assert observation.derived_mode == derived
    assert observation.modes_agree and observation.actions_agree
    assert observation.quality == "consistent"
    assert observation.completeness == "complete"
    assert observation.selected_modes == ((state, 3),)


def test_units_off_next_to_heating_units_are_normal():
    observation = group(climate("heat", "heating"), climate("off", "off"))
    assert observation.derived_mode == "heat"
    assert observation.conflict is False


# 9: selected heat and cool in one group.
def test_mixed_selected_heat_and_cool_is_conflict():
    observation = group(climate("heat", "idle"), climate("cool", "idle"))
    assert observation.selected_consensus == "mixed"
    assert observation.derived_mode == "mixed"
    assert observation.conflicts == ("selected_heat_and_cool",)
    assert observation.quality == "conflict"
    assert not observation.modes_agree


# 11, 17: unavailable unit and partially observed group.
def test_unavailable_unit_lowers_completeness():
    observation = group(climate("heat", "heating"), climate("unavailable"))
    assert observation.member_units == 2
    assert observation.available_units == 1
    assert observation.derived_mode == "heat"  # From what is visible only.
    assert observation.completeness == "partial"
    assert observation.quality == "partial"
    assert "indoor_units_unavailable" in observation.notes


@pytest.mark.parametrize(
    ("source", "availability"),
    [
        (None, "missing"),
        (SourceState("unknown"), "unknown"),
        (SourceState("unavailable"), "unavailable"),
        (climate("heat", "heating", trustworthy=False), "untrusted"),
    ],
)
def test_unusable_single_unit(source, availability):
    units, observation = observe(source)
    assert units[0].availability == availability
    assert units[0].selected_mode == "unknown"
    assert observation.derived_mode == "unknown"
    assert observation.reason == "no_available_indoor_units"
    assert observation.completeness == observation.quality == "none"


# 12: missing hvac_action.
def test_missing_hvac_action_is_unknown_activity():
    units, observation = observe(climate("heat"), climate("heat", "heating"))
    assert units[0].reported_action == "missing"
    assert units[0].quality == "no_action"
    assert observation.usable_actions == 1
    assert observation.reported_activity == "heating"
    assert "hvac_action_missing" in observation.notes
    assert observation.quality == "selected_only"
    observation = group(climate("cool"))
    assert observation.reported_activity == "unknown"
    assert observation.derived_mode == "cool"  # Selected mode, not activity.


# 13: auto, dry and fan_only are classified separately.
@pytest.mark.parametrize(
    ("state", "action", "consensus", "derived", "reason"),
    [
        ("auto", "idle", "unknown", "unknown", "auto_mode_unclassified"),
        ("heat_cool", MISSING, "unknown", "unknown", "auto_mode_unclassified"),
        ("auto", "heating", "unknown", "heat", "ambiguous_mode_heating_reported"),
        ("dry", "drying", "unknown", "unknown", "dry_mode_selected"),
        ("dry", "cooling", "unknown", "cool", "ambiguous_mode_cooling_reported"),
        ("fan_only", "fan", "off", "inactive", "no_heat_or_cool_selected"),
        ("eco", "idle", "unknown", "unknown", "unsupported_mode_selected"),
    ],
)
def test_ambiguous_modes(state, action, consensus, derived, reason):
    observation = group(climate(state, action))
    assert observation.selected_consensus == consensus
    assert observation.derived_mode == derived
    assert observation.reason == reason
    assert observation.conflict is False


def test_dry_is_not_treated_as_cool():
    observation = group(climate("cool", "cooling"), climate("dry", "drying"))
    assert observation.selected_consensus == "cool"
    assert "dry_mode_selected" in observation.notes
    assert not observation.modes_agree


# 14: selected mode contradicts reported action.
@pytest.mark.parametrize(
    ("state", "action"),
    [
        ("heat", "cooling"),
        ("cool", "heating"),
        ("off", "heating"),
        ("fan_only", "cooling"),
    ],
)
def test_selected_mode_action_mismatch(state, action):
    units, observation = observe(climate(state, action))
    assert units[0].mismatch is True
    assert observation.derived_mode == "mixed"
    assert "selected_mode_action_mismatch" in observation.conflicts
    assert observation.quality == "conflict"


# 15: contradictory reported actions.
def test_reported_heating_and_cooling_is_conflict():
    observation = group(climate("auto", "heating"), climate("auto", "cooling"))
    assert observation.reported_activity == "mixed"
    assert observation.derived_mode == "mixed"
    assert observation.conflicts == ("reported_heating_and_cooling",)
    assert not observation.actions_agree


# 16: no linked indoor units.
def test_no_indoor_units():
    observation = detect_group_mode("outdoor_1", ())
    assert observation.member_units == 0
    assert observation.derived_mode == "unknown"
    assert observation.reason == "no_indoor_units"
    assert compare_modes("heat", observation) == "no_indoor_units"


# Desired (demand) versus derived (indoor units).
@pytest.mark.parametrize(
    ("desired", "states", "expected"),
    [
        ("heat", [("off", "off")], "heat_requested_units_inactive"),
        ("cool", [("fan_only", "fan")], "cool_requested_units_inactive"),
        ("heat", [("cool", "cooling")], "mode_mismatch_observed"),
        ("heat", [("heat", "idle")], "observed_matches_desired"),
        ("off", [("off", "off")], "observed_matches_desired"),
        ("off", [("cool", "cooling")], "units_active_without_demand"),
        ("unknown", [("heat", "heating")], "desired_mode_unknown"),
        ("heat", [("heat", "idle"), ("cool", "idle")], "indoor_units_conflict"),
        ("heat", [("auto", "idle")], "indoor_observation_unknown"),
    ],
)
def test_compare_desired_with_derived(desired, states, expected):
    observation = group(*(climate(state, action) for state, action in states))
    assert compare_modes(desired, observation) == expected


# 23, 24: demand scores and the existing physical-mode guard are untouched.
def decide(model, sources):
    demands = {
        zone.id: calculate_demand(zone, collect_zone(model, zone, sources, NOW))
        for zone in model.zones
    }
    memories = {"outdoor_1": GroupMemory("unknown", NOW - timedelta(hours=1))}
    return demands, evaluate(model, demands, sources, memories, NOW)[0]


@pytest.mark.parametrize(
    "indoor",
    [
        climate("off", "off"),
        climate("heat", "heating"),
        climate("heat", "idle"),
        climate("cool", "cooling"),
        climate("auto"),
    ],
)
def test_indoor_observation_never_changes_demand_or_physical_mode(indoor):
    model = building(1)
    sources = {"sensor.room_0": SourceState("21", "°C", NOW), "climate.unit_0": indoor}
    demands, decision = decide(model, sources)
    assert demands["room_0"].demand == "heating_demand"
    assert demands["room_0"].heating_score == 1
    assert decision.desired_mode == "heat"
    # No trusted mode feedback: indoor units never fill the physical mode in.
    assert decision.current_mode == "unknown"
    assert decision.mode_quality == "missing"
    assert decision.proposed_mode == "unknown"
    assert decision.blocked_reason == "current_mode_unknown"
    assert not decision.mode_change_proposed


def test_physical_mode_comes_only_from_configured_feedback():
    model = building(1, mode_entity="sensor.outdoor_mode")
    sources = {
        "sensor.room_0": SourceState("21", "°C", NOW),
        "climate.unit_0": climate("heat", "heating"),
        "sensor.outdoor_mode": SourceState("off", None, NOW),
    }
    _, decision = decide(model, sources)
    assert decision.current_mode == "off"  # Trusted feedback, not the indoor unit.
    _, observation = observe_group(model, model.groups[0], sources)
    assert observation.derived_mode == "heat"
