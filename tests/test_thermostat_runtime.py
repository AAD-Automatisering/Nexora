"""0.9.0 integration: Zonentra thermostat per zone and active room regulation."""

from datetime import timedelta

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.zonentra.const import DOMAIN
from tests.test_entry_layout import (
    CELSIUS,
    add_zone,
    set_states,
    setup_central,
    zone_options,
)

UNIT = "climate.west_ac"
EQUIPMENT = "hvac_west_ac"
ATTRIBUTES = {"temperature": 22, "target_temp_step": 0.5, "min_temp": 16}


async def mock_climate(hass):
    # The zone thermostat loads the climate integration: set it up first, so
    # its real services do not replace the mocks.
    assert await async_setup_component(hass, "climate", {})
    return {
        service: async_mock_service(hass, "climate", service)
        for service in ("set_hvac_mode", "turn_off", "set_temperature", "set_fan_mode")
    }


def calls(mocks):
    return [
        (
            call.service,
            call.data.get("hvac_mode")
            or call.data.get("temperature")
            or call.data.get("fan_mode"),
        )
        for service in ("set_hvac_mode", "turn_off", "set_temperature", "set_fan_mode")
        for call in mocks[service]
    ]


def clear(mocks):
    for service_calls in mocks.values():
        service_calls.clear()


def entity(hass, platform, unique_id):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)


async def unit(hass, state, **attributes):
    hass.states.async_set(UNIT, state, {**ATTRIBUTES, **attributes})
    await hass.async_block_till_done()


async def later(hass, freezer, **delta):
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def office(hass, freezer, mocks=None):
    """West zone, 21 °C (heating demand), stand preset pulse completed."""
    set_states(hass, "west", UNIT)
    central = await setup_central(hass)
    zone = await add_zone(hass, zone_options("west", UNIT))
    await unit(hass, "heat")  # The integration applies the preset pulse.
    await later(hass, freezer, seconds=4)
    await unit(hass, "off")
    if mocks:
        clear(mocks)
    return central, zone


def room_commands(runtime):
    return [
        entry
        for entry in runtime.command_log
        if entry["reason"] not in ("preset_pulse", "switch_running_unit")
    ]


async def test_zone_device_gets_thermostat_settings_and_band(hass, freezer):
    # Real climate services: the thermostat is operated like any climate entity.
    central, zone = await office(hass, freezer)
    climate_id = entity(hass, "climate", f"{zone.entry_id}_thermostat")
    thermostat = hass.states.get(climate_id)
    assert thermostat.state == "heat_cool"
    assert thermostat.attributes["target_temp_low"] == 22  # Central comfort band.
    assert thermostat.attributes["target_temp_high"] == 24
    assert thermostat.attributes["current_temperature"] == 21
    assert thermostat.attributes["preset_mode"] == "comfort"
    assert thermostat.attributes["active_band"] == "comfort"
    assert thermostat.attributes["room_regulation"] is False
    assert thermostat.attributes["hvac_action"] == "idle"
    switch_id = entity(hass, "switch", f"{zone.entry_id}_room_regulation")
    assert hass.states.get(switch_id).state == "off"  # Off by default.
    low_id = entity(hass, "number", f"{zone.entry_id}_comfort_heating_limit")
    assert float(hass.states.get(low_id).state) == 22
    band_id = entity(hass, "sensor", f"{zone.entry_id}_active_band")
    assert hass.states.get(band_id).state == "comfort"

    # The room's own band replaces the configured comfort limits.
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": climate_id, "target_temp_low": 20, "target_temp_high": 25},
        blocking=True,
    )
    await hass.async_block_till_done()
    runtime = central.runtime_data
    assert runtime.zone_demands["west"].demand == "neutral"  # 21 °C in 20-25.
    assert float(hass.states.get(low_id).state) == 20
    assert hass.states.get(climate_id).attributes["comfort_source"] == "thermostat"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": low_id, "value": 21.5}, blocking=True
    )
    assert runtime.thermostat("west").heating_limit == 21.5
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": low_id, "value": 24.8}, blocking=True
        )

    # A fixed preset; building absence would still win.
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": climate_id, "preset_mode": "eco"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(band_id).state == "eco"
    assert runtime.zone_snapshots["west"].heating_limit.value == 19

    # Off: the room asks for nothing (and does not steer the outdoor unit).
    await hass.services.async_call(
        "climate", "turn_off", {"entity_id": climate_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(climate_id).state == "off"
    assert runtime.zone_demands["west"].reason == "thermostat_off"

    # The thermostat survives a central reload (for example a zone change).
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    restored = central.runtime_data.thermostat("west")
    assert (restored.hvac_mode, restored.preset, restored.heating_limit) == (
        "off",
        "eco",
        21.5,
    )
    assert room_commands(central.runtime_data) == []  # Room regulation is off.


async def test_thermostat_is_stored(hass, freezer, hass_storage):
    central, _ = await office(hass, freezer)
    central.runtime_data.set_thermostat("west", preset="eco")
    await hass.async_block_till_done()
    stored = hass_storage[f"{DOMAIN}.{central.entry_id}.thermostats"]["data"]
    assert stored["zones"]["west"]["preset"] == "eco"
    assert stored["zones"]["west"]["regulation"] is False


async def test_room_regulation_switches_steers_and_respects_people(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": entity(hass, "switch", f"{zone.entry_id}_room_regulation")},
        blocking=True,
    )
    await hass.async_block_till_done()
    # The pulse just switched the unit off: restart protection first.
    assert runtime.room_controls[EQUIPMENT].status == "blocked"
    assert calls(mocks) == []
    await later(hass, freezer, minutes=4)
    assert calls(mocks) == [("set_hvac_mode", "heat")]  # Room demand, outdoor mode.
    assert runtime.command_log[-1]["reason"] == "room_demand"
    clear(mocks)
    await unit(hass, "heat")  # Ours: no manual override.
    assert EQUIPMENT not in runtime.overrides
    # Self-regulating setpoint: 22.3 base + 1.3 room error -> 23.5 (step 0.5).
    assert calls(mocks) == [("set_temperature", 23.5)]
    clear(mocks)
    await unit(hass, "heat", temperature=23.5)  # Ours, confirmed.
    assert runtime.last_transitions[EQUIPMENT][0] == "zonentra_setpoint"
    control = hass.states.get(
        entity(hass, "sensor", f"{zone.entry_id}_{EQUIPMENT}_control")
    )
    assert control.attributes["simulation"] is False
    assert control.attributes["room_regulation_status"] == "hold"
    assert control.attributes["setpoint_status"] == "in_sync"

    # The unit or gateway changes its own setpoint (room controllers only
    # switch on and off): no override, Zonentra steers it back.
    await later(hass, freezer, minutes=2)
    await unit(hass, "heat", temperature=26)
    assert runtime.last_transitions[EQUIPMENT][0] == "device_setpoint"
    assert EQUIPMENT not in runtime.overrides
    await later(hass, freezer, minutes=4)
    assert calls(mocks) == [("set_temperature", 23.5)]
    clear(mocks)

    # A person changes the setpoint in Home Assistant: respected.
    hass.states.async_set(
        UNIT, "heat", {**ATTRIBUTES, "temperature": 25}, context=Context(user_id="u")
    )
    await hass.async_block_till_done()
    assert runtime.last_transitions[EQUIPMENT][0] == "manual_setpoint"
    assert runtime.setpoint_plans[EQUIPMENT].status == "manual_override"

    # A person switches the unit off: it stays off for the override time.
    await unit(hass, "off", temperature=25)
    assert runtime.overrides[EQUIPMENT].mode_at_start == "off"
    await later(hass, freezer, minutes=10)
    assert calls(mocks) == []
    assert runtime.unit_intents[EQUIPMENT].reason == "manual_override_off"
    # After the override the room is regulated again.
    await later(hass, freezer, minutes=21)
    assert calls(mocks) == [("set_hvac_mode", "heat")]


async def test_thermostat_off_switches_a_regulated_room_off(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    runtime.set_thermostat("west", regulation=True)
    await later(hass, freezer, minutes=4)
    await unit(hass, "heat")
    clear(mocks)
    # (The climate services are mocked here, so use the runtime directly.)
    runtime.set_thermostat("west", hvac_mode="off")
    await hass.async_block_till_done()
    assert calls(mocks) == []  # Minimum run time first (comfort).
    await later(hass, freezer, minutes=11)
    assert ("turn_off", None) in calls(mocks)


async def test_regulated_room_keeps_its_unit_on_after_a_stand_change(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    runtime.set_thermostat("west", regulation=True)
    await hass.async_block_till_done()
    # The room gets hot: after the minimum switch interval the stand goes cool.
    freezer.tick(timedelta(minutes=16))
    hass.states.async_set("sensor.west_temperature", "26", CELSIUS)
    await hass.async_block_till_done()
    assert ("set_hvac_mode", "cool") in calls(mocks)
    await unit(hass, "cool")  # Preset pulse applied (ours).
    clear(mocks)
    await later(hass, freezer, seconds=4)
    # The pulse would switch it off again, but the room needs cooling.
    assert ("turn_off", None) not in calls(mocks)
    assert any(
        entry["result"] == "skipped_room_demand" for entry in runtime.command_log
    )


async def test_standard_heat_and_cool_modes(hass, freezer):
    # Real climate services: the thermostat is operated like any climate entity.
    central, zone = await office(hass, freezer)
    runtime = central.runtime_data
    climate_id = entity(hass, "climate", f"{zone.entry_id}_thermostat")
    assert hass.states.get(climate_id).attributes["hvac_modes"] == [
        "heat_cool",
        "heat",
        "cool",
        "off",
    ]
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": climate_id, "hvac_mode": "heat"},
        blocking=True,
    )
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": climate_id, "temperature": 21.5},
        blocking=True,
    )
    await hass.async_block_till_done()
    thermostat = hass.states.get(climate_id)
    assert thermostat.state == "heat"
    assert thermostat.attributes["temperature"] == 21.5  # Single target.
    assert runtime.thermostat("west").heating_limit == 21.5
    assert runtime.thermostat("west").cooling_limit == 24  # Unchanged.
    # A heat-only room never asks for cooling, so it never pulls the group.
    hass.states.async_set("sensor.west_temperature", "26", CELSIUS)
    await hass.async_block_till_done()
    assert runtime.zone_demands["west"].reason == "thermostat_heat_only"
    assert runtime.group_decisions["outdoor_1"].desired_mode != "cool"
    # Cool mode: the target is the cooling limit; now the room asks for cooling.
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": climate_id, "hvac_mode": "cool"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(climate_id).attributes["temperature"] == 24
    assert runtime.zone_demands["west"].demand == "cooling_demand"


# A typical KNX/Intesis indoor unit (generic test values).
KNX = {
    "hvac_modes": ["auto", "cool", "dry", "fan_only", "heat", "off"],
    "fan_modes": ["off", "25%", "50%", "75%", "100%"],
    "fan_mode": "50%",
}


async def test_thermostat_offers_the_units_options(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    await unit(hass, "off", **KNX)
    climate_id = entity(hass, "climate", f"{zone.entry_id}_thermostat")
    thermostat = hass.states.get(climate_id)
    # The units call the both-ways mode "auto": so does the thermostat.
    assert thermostat.state == "auto"
    assert thermostat.attributes["hvac_modes"] == [
        "auto",
        "heat",
        "cool",
        "dry",
        "fan_only",
        "off",
    ]
    # Plus Zonentra's automatic fan (0.10), as the units have none of their own.
    assert thermostat.attributes["fan_modes"] == ["auto", *KNX["fan_modes"]]
    assert thermostat.attributes["fan_mode"] == "50%"
    assert runtime.thermostat("west").hvac_mode == "heat_cool"  # Stored as such.

    # Fan only with room regulation: after restart protection the unit runs
    # fan_only, then gets the thermostat's fan speed.
    runtime.set_thermostat(
        "west", hvac_mode="fan_only", fan_mode="75%", regulation=True
    )
    await hass.async_block_till_done()
    assert runtime.zone_demands["west"].reason == "thermostat_fan_only"
    assert runtime.room_controls[EQUIPMENT].status == "minimum_off_time"
    assert calls(mocks) == []
    await later(hass, freezer, minutes=4)
    assert calls(mocks) == [("set_hvac_mode", "fan_only")]
    clear(mocks)
    await unit(hass, "fan_only", **KNX)  # Ours.
    assert EQUIPMENT not in runtime.overrides
    assert calls(mocks) == [("set_fan_mode", "75%")]
    clear(mocks)
    await unit(hass, "fan_only", **(KNX | {"fan_mode": "75%"}))
    assert hass.states.get(climate_id).state == "fan_only"
    assert hass.states.get(climate_id).attributes["hvac_action"] == "fan"
    # Someone changes the fan at the room controller: not fought.
    await unit(hass, "fan_only", **(KNX | {"fan_mode": "25%"}))
    assert calls(mocks) == []
