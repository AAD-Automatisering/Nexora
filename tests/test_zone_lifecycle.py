"""A disabled zone must leave the central building and stop issuing commands."""

from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState

from tests.test_entry_layout import CELSIUS, add_zone, set_states, zone_options
from tests.test_thermostat_runtime import (
    UNIT,
    clear,
    later,
    mock_climate,
    office,
)


async def test_disabling_zone_stops_control_and_reenabling_restores_it(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    runtime.set_thermostat("west", regulation=True)
    await later(hass, freezer, minutes=4)
    assert any(call.data.get("hvac_mode") == "heat" for call in mocks["set_hvac_mode"])

    assert await hass.config_entries.async_set_disabled_by(
        zone.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert zone.state is ConfigEntryState.NOT_LOADED
    assert "west" not in central.runtime_data.zone_demands
    assert UNIT not in central.runtime_data.building.entity_ids

    clear(mocks)
    hass.states.async_set("sensor.west_temperature", "20.5", CELSIUS)
    await later(hass, freezer, minutes=20)
    central.runtime_data.refresh()
    await hass.async_block_till_done()
    assert all(not commands for commands in mocks.values())

    assert await hass.config_entries.async_set_disabled_by(zone.entry_id, None)
    await hass.async_block_till_done()
    assert zone.state is ConfigEntryState.LOADED
    assert "west" in central.runtime_data.zone_demands
    assert central.runtime_data.thermostat("west").regulation is True
    assert any(call.data.get("hvac_mode") == "heat" for call in mocks["set_hvac_mode"])


async def test_disabling_zone_keeps_other_zones_and_cancels_its_pulse(hass, freezer):
    mocks = await mock_climate(hass)
    central, _ = await office(hass, freezer, mocks)
    other_unit = "climate.east_ac"
    set_states(hass, "east", other_unit)
    zone = await add_zone(hass, zone_options("east", other_unit))
    # Force a new group preset with both units off, including a delayed pulse-off.
    runtime = central.runtime_data
    runtime.preset_memories.clear()
    runtime.refresh()
    await later(hass, freezer, minutes=3)  # Both units must satisfy min-off.
    await hass.async_block_till_done()
    assert any(
        command.entity_id == other_unit for _, command, _ in runtime.pending_offs
    )
    hass.states.async_set(other_unit, "heat")
    await hass.async_block_till_done()

    assert await hass.config_entries.async_set_disabled_by(
        zone.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert set(central.runtime_data.zone_demands) == {"west"}
    assert all(
        command.entity_id != other_unit
        for _, command, _ in central.runtime_data.pending_offs
    )
    clear(mocks)
    await later(hass, freezer, seconds=5)
    assert not any(
        call.data["entity_id"] == other_unit
        for commands in mocks.values()
        for call in commands
    )
    hass.states.async_set("sensor.west_temperature", "25", CELSIUS)
    await hass.async_block_till_done()
    assert central.runtime_data.zone_demands["west"].demand == "cooling_demand"


async def test_zone_reload_keeps_central_runtime(hass, freezer):
    mocks = await mock_climate(hass)
    central, zone = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    runtime.set_thermostat("west", regulation=True)
    await hass.async_block_till_done()
    clear(mocks)
    assert await hass.config_entries.async_reload(zone.entry_id)
    await hass.async_block_till_done()
    assert zone.state is ConfigEntryState.LOADED
    assert central.runtime_data is runtime
    assert runtime.thermostat("west").regulation is True
    assert set(runtime.zone_demands) == {"west"}
    assert all(not commands for commands in mocks.values())
