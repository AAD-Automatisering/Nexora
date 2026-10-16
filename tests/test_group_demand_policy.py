"""One-sided room requests remain authoritative through their hysteresis cycle."""

from datetime import timedelta

import pytest

from custom_components.zonentra.control import resolve_group_mode
from custom_components.zonentra.demand import calculate_demand, collect_zone
from custom_components.zonentra.engine import GroupMemory, evaluate
from custom_components.zonentra.observations import SourceState
from tests.test_entry_layout import (
    CELSIUS,
    add_zone,
    set_states,
    setup_central,
    zone_options,
)
from tests.test_intelligence import NOW, scenario
from tests.test_thermostat_runtime import UNIT, clear, later, mock_climate, unit


@pytest.mark.parametrize(
    "temperature,previous,target",
    [
        (20.6, "neutral", "heat"),
        (24.4, "neutral", "cool"),
        (21.1, "heating_demand", "heat"),
        (23.9, "cooling_demand", "cool"),
    ],
)
def test_one_sided_request_ignores_both_score_gates_even_when_score_is_zero(
    temperature, previous, target
):
    building, sources = scenario(
        (temperature,), mode="off", min_demand_score=5, score_deadband=5
    )
    zone = building.zones[0]
    demand = calculate_demand(
        zone, collect_zone(building, zone, sources, NOW), previous
    )
    memory = {"group": GroupMemory("off", NOW - timedelta(hours=1))}
    decision = evaluate(building, {zone.id: demand}, sources, memory, NOW)[0]
    assert decision.desired_mode == decision.proposed_mode == target
    assert getattr(
        decision, "heating_requested" if target == "heat" else "cooling_requested"
    )
    assert resolve_group_mode(decision, building.groups[0], None)[0] == target


def test_two_opposing_weak_requests_keep_current_mode_but_do_not_start_without_one():
    building, sources = scenario((20.65, 24.35), mode="heat")
    demands = {
        z.id: calculate_demand(z, collect_zone(building, z, sources, NOW))
        for z in building.zones
    }
    memories = {"group": GroupMemory("heat", NOW - timedelta(hours=1))}
    decision = evaluate(building, demands, sources, memories, NOW)[0]
    assert decision.desired_mode == "heat"
    sources["sensor.mode"] = SourceState("off", None, NOW)
    decision = evaluate(building, demands, sources, memories, NOW)[0]
    assert decision.desired_mode == "off"
    assert resolve_group_mode(decision, building.groups[0], "cool")[0] == "cool"
    assert resolve_group_mode(decision, building.groups[0], None)[0] == "neutral"


def test_unilateral_request_does_not_bypass_missing_data_or_switch_interval():
    building, sources = scenario((20.6,), mode="cool")
    zone = building.zones[0]
    demands = {
        zone.id: calculate_demand(zone, collect_zone(building, zone, sources, NOW))
    }
    memories = {"group": GroupMemory("cool", NOW)}
    decision = evaluate(building, demands, sources, memories, NOW)[0]
    assert decision.desired_mode == "heat"
    assert decision.proposed_mode == "cool"
    assert decision.blocked_reason == "minimum_switch_interval"
    sources["climate.unit_0"] = SourceState("unavailable", None, NOW)
    decision = evaluate(building, demands, sources, memories, NOW)[0]
    assert decision.desired_mode == "unknown"
    assert resolve_group_mode(decision, building.groups[0], "heat")[0] == "unknown"


def test_conflict_recovery_uses_requested_direction_even_with_zero_score():
    building, sources = scenario((21.1, 23), mode=None)
    zone = building.zones[0]
    demands = {
        z.id: calculate_demand(
            z,
            collect_zone(building, z, sources, NOW),
            "heating_demand" if z == zone else "neutral",
        )
        for z in building.zones
    }
    sources["climate.unit_0"] = SourceState("heat", None, NOW)
    sources["climate.unit_1"] = SourceState("cool", None, NOW)
    decision = evaluate(
        building, demands, sources, {"group": GroupMemory("unknown", NOW)}, NOW
    )[0]
    assert decision.reason == "observed_group_conflict"
    assert decision.heating_score == 0
    assert resolve_group_mode(decision, building.groups[0], None)[0] == "heat"


@pytest.mark.parametrize(
    "temperature,middle,end,mode,action",
    [
        ("21.6", "22.1", "22.3", "heat", "heating"),
        ("24.4", "23.9", "23.7", "cool", "cooling"),
    ],
)
async def test_actual_room_starts_at_score_point_four_and_finishes_hysteresis(
    hass, freezer, temperature, middle, end, mode, action
):
    mocks = await mock_climate(hass)
    set_states(hass, "west", UNIT, temperature=temperature)
    central = await setup_central(hass)
    await add_zone(hass, zone_options("west", UNIT))
    runtime = central.runtime_data
    await unit(hass, mode, hvac_action=action)
    await later(hass, freezer, seconds=4)
    await unit(hass, "off", hvac_action="off")
    clear(mocks)
    runtime.set_thermostat("west", regulation=True)
    await hass.async_block_till_done()
    assert not mocks["set_hvac_mode"]  # Freshly stopped: minimum off-time applies.
    await later(hass, freezer, seconds=181)
    assert [c.data["hvac_mode"] for c in mocks["set_hvac_mode"]] == [mode]
    await unit(hass, mode, hvac_action=action)
    hass.states.async_set("sensor.west_temperature", middle, CELSIUS)
    await hass.async_block_till_done()
    demand = runtime.zone_demands["west"]
    assert demand.heating_score == demand.cooling_score == 0
    assert runtime.coordinations["outdoor_1"].group_mode == mode
    assert not mocks["turn_off"]
    hass.states.async_set("sensor.west_temperature", end, CELSIUS)
    await hass.async_block_till_done()
    assert runtime.zone_demands["west"].demand == "neutral"
    assert not mocks["turn_off"]  # Minimum on-time still applies.
    await later(hass, freezer, seconds=601)
    assert len(mocks["turn_off"]) == 1


async def test_closed_runtime_ignores_late_queued_refresh(hass):
    central = await setup_central(hass)
    runtime = central.runtime_data
    runtime.close()
    before = runtime.evaluated_at
    runtime.refresh()
    assert runtime.evaluated_at == before
    assert runtime._cancel_deadline is None
