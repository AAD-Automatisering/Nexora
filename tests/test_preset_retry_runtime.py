"""Service failures must not turn planned group presets into applied presets."""

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.zonentra.executor import PRESET_RETRY_SECONDS
from tests.test_entry_layout import (
    CELSIUS,
    add_zone,
    set_states,
    setup_central,
    zone_options,
)
from tests.test_mode_control_runtime import UNIT, mock_climate, office
from tests.test_thermostat_runtime import later


async def failing_office(hass):
    await mock_climate(hass)
    failed = async_mock_service(
        hass, "climate", "set_hvac_mode", raise_exception=HomeAssistantError("offline")
    )
    central, zone = await office(hass)
    return central, zone, failed


async def test_failed_preset_retries_without_input_events_and_saves_only_success(
    hass, freezer, hass_storage
):
    central, _, failed = await failing_office(hass)
    runtime = central.runtime_data
    assert len(failed) == 1
    assert runtime.preset_memories.get("outdoor_1") is None
    assert runtime.pending_offs == []
    assert runtime.mode_controls["outdoor_1"].status == "preset_retry"
    stored = hass_storage.get(f"zonentra.{central.entry_id}.mode_control", {})
    assert stored.get("data", {}).get("groups", {}).get("outdoor_1") is None

    for _ in range(3):
        runtime.refresh()
    await later(hass, freezer, seconds=PRESET_RETRY_SECONDS - 1)
    assert len(failed) == 1

    successful = async_mock_service(hass, "climate", "set_hvac_mode")
    await later(hass, freezer, seconds=2)
    assert len(successful) == 1
    assert runtime.preset_memories["outdoor_1"].mode == "heat"
    assert not runtime.preset_applications
    assert len(runtime.pending_offs) == 1
    stored = hass_storage[f"zonentra.{central.entry_id}.mode_control"]
    assert stored["data"]["groups"]["outdoor_1"]["mode"] == "heat"


async def test_partial_failure_retries_only_failed_unit_after_reload(hass, freezer):
    await mock_climate(hass)
    attempts = []
    failing = True
    other = "climate.east_ac"

    async def service(call):
        attempts.append(call.data["entity_id"])
        if failing and call.data["entity_id"] == other:
            raise HomeAssistantError("offline")

    hass.services.async_register("climate", "set_hvac_mode", service)
    set_states(hass, "west", UNIT, other)
    central = await setup_central(hass)
    await add_zone(hass, zone_options("west", UNIT, other))
    assert attempts == [UNIT, other]
    application = central.runtime_data.preset_applications["outdoor_1"]
    assert set(application.commands) == {"hvac_east_ac"}
    assert "outdoor_1" not in central.runtime_data.preset_memories

    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    assert attempts == [UNIT, other]
    failing = False
    await later(hass, freezer, seconds=PRESET_RETRY_SECONDS + 1)
    assert attempts == [UNIT, other, other]
    assert central.runtime_data.preset_memories["outdoor_1"].mode == "heat"
    assert not central.runtime_data.preset_applications


@pytest.mark.parametrize("manual_mode", ["heat", "cool"])
async def test_retry_does_not_pulse_off_a_manually_started_unit(
    hass, freezer, manual_mode
):
    central, _, _ = await failing_office(hass)
    successful = async_mock_service(hass, "climate", "set_hvac_mode")
    turn_off = async_mock_service(hass, "climate", "turn_off")
    hass.states.async_set(UNIT, manual_mode, context=Context(user_id="review-user"))
    await hass.async_block_till_done()
    await later(hass, freezer, seconds=PRESET_RETRY_SECONDS + 1)
    assert len(successful) == (0 if manual_mode == "heat" else 1)
    assert central.runtime_data.preset_memories["outdoor_1"].mode == "heat"
    assert central.runtime_data.pending_offs == []
    await later(hass, freezer, seconds=4)
    assert turn_off == []


async def test_failed_preset_stops_retrying_when_group_disabled(hass, freezer):
    central, _, failed = await failing_office(hass)
    central.runtime_data.set_mode_active("outdoor_1", False)
    await later(hass, freezer, seconds=PRESET_RETRY_SECONDS * 2)
    assert len(failed) == 1
    assert not central.runtime_data.preset_applications
    assert central.runtime_data.mode_controls["outdoor_1"].status == "disabled"


async def test_failed_preset_uses_new_group_target_instead_of_stale_retry(
    hass, freezer
):
    central, _, _ = await failing_office(hass)
    successful = async_mock_service(hass, "climate", "set_hvac_mode")
    hass.states.async_set("sensor.west_temperature", "25", CELSIUS)
    await hass.async_block_till_done()
    assert [call.data["hvac_mode"] for call in successful] == ["cool"]
    assert central.runtime_data.preset_memories["outdoor_1"].mode == "cool"
    await later(hass, freezer, seconds=PRESET_RETRY_SECONDS + 1)
    assert len(successful) == 1


async def test_failed_pulse_off_retries_without_repeating_pulse_on(hass, freezer):
    set_mode, _ = await mock_climate(hass)
    central, _ = await office(hass)
    hass.states.async_set(UNIT, "heat")
    await hass.async_block_till_done()
    failed = async_mock_service(
        hass, "climate", "turn_off", raise_exception=HomeAssistantError("offline")
    )
    await later(hass, freezer, seconds=4)
    assert len(failed) == 1
    assert len(central.runtime_data.pending_offs) == 1
    successful = async_mock_service(hass, "climate", "turn_off")
    await later(hass, freezer, seconds=PRESET_RETRY_SECONDS - 1)
    assert successful == []
    await later(hass, freezer, seconds=2)
    assert len(successful) == 1
    assert len(set_mode) == 1
    assert not central.runtime_data.pending_offs


@pytest.mark.parametrize("failure", [False, True])
async def test_preset_response_during_reload_setup_is_not_lost(
    hass, freezer, monkeypatch, failure
):
    import asyncio

    from homeassistant.helpers.storage import Store

    await mock_climate(hass)
    central, _ = await office(hass)
    runtime = central.runtime_data
    started, release_service = asyncio.Event(), asyncio.Event()
    loading, release_load = asyncio.Event(), asyncio.Event()
    response_processed = asyncio.Event()
    attempts = []

    async def service(call):
        attempts.append(call.data["hvac_mode"])
        started.set()
        await release_service.wait()
        if failure:
            raise HomeAssistantError("offline")

    original_result = runtime._preset_result

    def result(*args):
        original_result(*args)
        response_processed.set()

    original_load = Store.async_load

    async def load(store):
        data = await original_load(store)
        if store.key == f"zonentra.{central.entry_id}.mode_control":
            loading.set()
            await release_load.wait()
        return data

    monkeypatch.setattr(runtime, "_preset_result", result)
    monkeypatch.setattr(Store, "async_load", load)
    hass.services.async_register("climate", "set_hvac_mode", service)
    freezer.tick(3600)
    hass.states.async_set("sensor.west_temperature", "25", CELSIUS)
    await started.wait()
    reload_task = hass.async_create_task(
        hass.config_entries.async_reload(central.entry_id)
    )
    try:
        await loading.wait()
        release_service.set()
        await response_processed.wait()
    finally:
        release_service.set()
        release_load.set()
    assert await reload_task
    await hass.async_block_till_done()
    assert attempts == ["cool"]
    current = central.runtime_data
    if failure:
        assert current.preset_memories["outdoor_1"].mode == "heat"
        assert not current.preset_applications["outdoor_1"].in_flight
        await later(hass, freezer, seconds=PRESET_RETRY_SECONDS + 1)
        assert attempts == ["cool", "cool"]
    else:
        assert current.preset_memories["outdoor_1"].mode == "cool"
        assert not current.preset_applications
        assert len(current.pending_offs) == 1
