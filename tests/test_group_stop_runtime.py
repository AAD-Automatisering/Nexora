"""The group stop switch must block every command for its indoor units."""

import pytest
from homeassistant.core import Context
from pytest_homeassistant_custom_component.common import async_mock_service

from tests.test_entry_layout import add_zone, set_states, zone_options
from tests.test_thermostat_runtime import (
    ATTRIBUTES,
    KNX,
    UNIT,
    clear,
    later,
    mock_climate,
    office,
)


@pytest.mark.parametrize("mode", ["heat_cool", "dry", "fan_only", "off"])
async def test_group_stop_blocks_room_on_off_and_direct_modes(hass, freezer, mode):
    mocks = await mock_climate(hass)
    central, _ = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    runtime.set_mode_active("outdoor_1", False)
    runtime.set_thermostat("west", regulation=True, hvac_mode=mode)
    if mode == "off":
        hass.states.async_set(
            UNIT, "heat", ATTRIBUTES, context=Context(parent_id="automation")
        )
    await later(hass, freezer, minutes=11)
    assert all(not calls for calls in mocks.values())
    assert runtime.room_controls["hvac_west_ac"].status == "group_disabled"
    assert runtime.thermostat("west").regulation is True

    if mode == "heat_cool":
        runtime.set_mode_active("outdoor_1", True)
        await hass.async_block_till_done()
        assert any(
            call.data.get("hvac_mode") == "heat" for call in mocks["set_hvac_mode"]
        )


async def test_group_stop_blocks_fan_and_setpoint_for_running_unit(hass, freezer):
    mocks = await mock_climate(hass)
    central, _ = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    runtime.set_mode_active("outdoor_1", False)
    runtime.set_thermostat("west", regulation=True, fan_mode="high")
    hass.states.async_set(
        UNIT,
        "heat",
        {**ATTRIBUTES, **KNX, "temperature": 16, "fan_mode": "25%"},
        context=Context(parent_id="automation"),
    )
    await later(hass, freezer, minutes=6)
    assert all(not calls for calls in mocks.values())
    assert runtime.setpoint_plans["hvac_west_ac"].status == "group_disabled"
    assert not runtime.setpoint_plans["hvac_west_ac"].send

    runtime.set_mode_active("outdoor_1", True)
    await hass.async_block_till_done()
    assert mocks["set_temperature"]
    assert mocks["set_fan_mode"]


async def test_group_stop_blocks_vane_and_reenabling_resumes_it(hass, freezer):
    mocks = await mock_climate(hass)
    vane = async_mock_service(hass, "select", "select_option")
    central, _ = await office(
        hass,
        freezer,
        mocks,
        vane_entity="select.west_vane",
        vane_heat_value="5",
        vane_cool_value="1",
    )
    runtime = central.runtime_data
    vane.clear()
    runtime.set_mode_active("outdoor_1", False)
    hass.states.async_set(UNIT, "heat", ATTRIBUTES)
    await hass.async_block_till_done()
    assert vane == []
    runtime.set_mode_active("outdoor_1", True)
    await hass.async_block_till_done()
    assert [call.data["option"] for call in vane] == ["5"]


async def test_group_stop_leaves_standalone_room_control_active(hass, freezer):
    mocks = await mock_climate(hass)
    central, _ = await office(hass, freezer, mocks)
    other = "climate.east_ac"
    set_states(hass, "east", other)
    await add_zone(hass, zone_options("east", other, group_id=None))
    runtime = central.runtime_data
    runtime.set_mode_active("outdoor_1", False)
    clear(mocks)
    runtime.set_thermostat("west", regulation=True)
    runtime.set_thermostat("east", regulation=True)
    await later(hass, freezer, minutes=4)
    assert [call.data["entity_id"] for call in mocks["set_hvac_mode"]] == [other]
    assert runtime.zone_demands["west"].demand == "heating_demand"


async def test_service_dispatch_rechecks_stop_for_a_previously_planned_command(
    hass, freezer
):
    from homeassistant.util import dt as dt_util

    from custom_components.zonentra.executor import ModeCommand

    mocks = await mock_climate(hass)
    central, _ = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    command = ModeCommand(
        "hvac_west_ac",
        UNIT,
        "set_temperature",
        None,
        0,
        "self_regulation",
        temperature=25,
    )
    entry = runtime._log(command, dt_util.utcnow(), "sending")
    runtime.set_mode_active("outdoor_1", False)
    assert not await runtime._call(
        "set_temperature", {"entity_id": UNIT, "temperature": 25}, entry
    )
    assert mocks["set_temperature"] == []
    assert entry["result"] == "blocked: group_disabled"


@pytest.mark.parametrize("failure", [False, True])
async def test_late_preset_response_cannot_restart_commands_after_stop(
    hass, freezer, failure
):
    import asyncio

    from homeassistant.exceptions import HomeAssistantError

    from tests.test_entry_layout import CELSIUS

    mocks = await mock_climate(hass)
    central, _ = await office(hass, freezer, mocks)
    runtime = central.runtime_data
    started, release = asyncio.Event(), asyncio.Event()
    attempts = []

    async def service(call):
        attempts.append(call)
        started.set()
        await release.wait()
        if failure:
            raise HomeAssistantError("offline")

    hass.services.async_register("climate", "set_hvac_mode", service)
    freezer.tick(3600)
    hass.states.async_set("sensor.west_temperature", "25", CELSIUS)
    await started.wait()
    try:
        runtime.set_mode_active("outdoor_1", False)
    finally:
        release.set()
    await hass.async_block_till_done()
    assert not runtime.preset_applications
    assert not runtime.pending_offs
    await later(hass, freezer, minutes=3)
    assert len(attempts) == 1
    assert all(not calls for calls in mocks.values())
