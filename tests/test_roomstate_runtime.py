"""0.10.0 integration: room-state sensors, open window and automatic fan."""

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.zonentra.const import DOMAIN
from tests.test_entry_layout import (
    CELSIUS,
    add_zone,
    set_states,
    setup_central,
    zone_options,
)
from tests.test_thermostat_runtime import (
    EQUIPMENT,
    KNX,
    UNIT,
    calls,
    clear,
    later,
    mock_climate,
    unit,
)

WINDOW = "binary_sensor.west_window"


def entity(hass, platform, unique_id):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)


async def office(hass, freezer, mocks):
    set_states(hass, "west", UNIT)
    hass.states.async_set(WINDOW, "off")
    central = await setup_central(hass)
    zone = await add_zone(hass, zone_options("west", UNIT, contact_entities=[WINDOW]))
    await unit(hass, "heat", **KNX)  # The integration applies the preset pulse.
    await later(hass, freezer, seconds=4)
    await unit(hass, "off", **KNX)
    clear(mocks)
    return central, zone


def state(hass, zone, key, platform="sensor"):
    return hass.states.get(entity(hass, platform, f"{zone.entry_id}_{key}"))


async def test_room_state_sensors(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    assert state(hass, zone, "presence").state == "not_configured"
    assert state(hass, zone, "safety").state == "safe"
    assert state(hass, zone, "window").state == "closed"
    assert float(state(hass, zone, "ema_temperature").state) == 21
    assert state(hass, zone, "temperature_slope").state == "unknown"  # One sample.
    assert state(hass, zone, "regulated_setpoint").attributes["status"] == (
        "unit_not_running"
    )
    assert state(hass, zone, "window_bypass", "switch").state == "off"
    # The room sensor fails: unsafe, and no regulation on it.
    hass.states.async_set("sensor.west_temperature", "unavailable")
    await hass.async_block_till_done()
    assert state(hass, zone, "safety").state == "sensor_fault"
    # It recovers warmer: the trend rises.
    await later(hass, freezer, minutes=10)
    hass.states.async_set("sensor.west_temperature", "22", CELSIUS)
    await hass.async_block_till_done()
    assert state(hass, zone, "safety").state == "safe"
    assert float(state(hass, zone, "temperature_slope").state) > 0


async def test_open_window_stops_the_room(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    runtime.set_thermostat("west", regulation=True)
    await later(hass, freezer, minutes=4)
    await unit(hass, "heat", **KNX)  # Switched on by Zonentra for the demand.
    clear(mocks)
    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    assert state(hass, zone, "window").state == "opening"
    assert calls(mocks) == []
    await later(hass, freezer, seconds=31)
    assert state(hass, zone, "window").state == "open"
    assert runtime.zone_demands["west"].reason == "window_open"
    # Off at once, even within the minimum run time.
    assert calls(mocks) == [("turn_off", None)]
    await unit(hass, "off", **KNX)
    clear(mocks)
    # Bypass: the window is ignored and the room is regulated again.
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": entity(hass, "switch", f"{zone.entry_id}_window_bypass")},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert state(hass, zone, "window").state == "bypass"
    await later(hass, freezer, minutes=4)
    assert calls(mocks) == [("set_hvac_mode", "heat")]


async def test_automatic_fan(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    thermostat = hass.states.get(entity(hass, "climate", f"{zone.entry_id}_thermostat"))
    # The units have no auto fan of their own: Zonentra adds one.
    assert thermostat.attributes["fan_modes"][0] == "auto"
    runtime.set_thermostat("west", regulation=True, fan_mode="auto")
    await later(hass, freezer, minutes=4)
    await unit(hass, "heat", **KNX)
    # 21 °C, target 22.3: 1.3 °C away -> third speed.
    assert ("set_fan_mode", "75%") in calls(mocks)
    assert state(hass, zone, "auto_fan").state == "75%"
    assert EQUIPMENT not in runtime.overrides


async def test_vane_follows_cooling_and_heating(hass, freezer):
    mocks = await mock_climate(hass)
    vane = async_mock_service(hass, "select", "select_option")
    set_states(hass, "west", UNIT)
    hass.states.async_set("select.west_vane", "3")
    central = await setup_central(hass)
    await add_zone(
        hass,
        zone_options(
            "west",
            UNIT,
            vane_entity="select.west_vane",
            vane_cool_value="1",
            vane_heat_value="5",
        ),
    )
    # The preset pulse switches the unit to heat for a moment: vane down.
    await unit(hass, "heat", **KNX)
    assert [call.data["option"] for call in vane] == ["5"]
    await unit(hass, "heat", **(KNX | {"fan_mode": "75%"}))
    assert len(vane) == 1  # Once per start or mode change.
    await later(hass, freezer, seconds=4)
    await unit(hass, "off", **KNX)
    await unit(hass, "cool", **KNX)  # Someone starts it cooling: vane up.
    assert [call.data["option"] for call in vane] == ["5", "1"]
    log = central.runtime_data.command_log[-1]
    assert (log["service"], log["value"], log["reason"]) == (
        "select_option",
        "1",
        "vane_cool",
    )
    clear(mocks)


async def test_limits_are_set_on_the_devices_not_in_the_wizard(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    # The central wizard no longer asks for fixed limits.
    flow = await hass.config_entries.options.async_init(central.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "general"}
    )
    schema = flow["data_schema"].schema
    assert "heating_limit" not in schema and "eco_heating_limit" not in schema
    assert "heating_limit_entity" in schema
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"hysteresis": 0.3}
    )
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "finish"}
    )
    await hass.async_block_till_done()
    central = hass.config_entries.async_get_entry(central.entry_id)
    assert central.options["building"]["heating_limit"] == 22  # Kept.
    runtime = central.runtime_data

    # Central device: the building's eco band, applied without a reload.
    eco_id = entity(hass, "number", f"{central.entry_id}_eco_heating_limit")
    assert float(hass.states.get(eco_id).state) == 19
    await hass.services.async_call(
        "number", "set_value", {"entity_id": eco_id, "value": 18}, blocking=True
    )
    await hass.async_block_till_done()
    assert central.options["building"]["eco_heating_limit"] == 18
    assert central.runtime_data is runtime  # No reload.
    assert runtime.building.settings.eco_heating_limit == 18
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": eco_id, "value": 26}, blocking=True
        )

    # Zone device: its own eco limit wins, the rest follows the central device.
    zone_eco = entity(hass, "number", f"{zone.entry_id}_eco_heating_limit")
    assert float(hass.states.get(zone_eco).state) == 18
    assert hass.states.get(zone_eco).attributes["source"] == "central"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": zone_eco, "value": 20}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(zone_eco).attributes["source"] == "zone"
    runtime.set_thermostat("west", preset="eco")
    snapshot = runtime.zone_snapshots["west"]
    assert (snapshot.heating_limit.value, snapshot.cooling_limit.value) == (20, 26)
    # Button: back to the central limits.
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity(hass, "button", f"{zone.entry_id}_use_central_limits")},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert runtime.zone_snapshots["west"].heating_limit.value == 18
    assert hass.states.get(zone_eco).attributes["source"] == "central"
