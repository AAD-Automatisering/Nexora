"""Screens hold on uncertain inputs and resume after source recovery."""

from asyncio import Event
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.zonentra.const import DOMAIN
from custom_components.zonentra.observations import cover_position
from tests.test_entry_layout import setup_central
from tests.test_shading_runtime import EQUIPMENT, SCREEN, entity
from tests.test_shading_runtime import office as screen_office
from tests.test_thermostat_runtime import later

BLOCK = "binary_sensor.wind_alarm"


async def office(hass):
    # These tests isolate source recovery and dispatch guards; timing is covered
    # by the shading runtime tests with the default delays.
    return await screen_office(
        hass, screen_open_delay_minutes=0, screen_shade_delay_minutes=0
    )


async def block_office(hass):
    central, zone = await office(hass)
    hass.config_entries.async_update_entry(
        central,
        options={
            **central.options,
            "building": {**central.options["building"], "screen_block_entity": BLOCK},
        },
    )
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    return central, zone


@pytest.mark.parametrize(
    ("state", "attributes"),
    [
        (None, {}),
        ("unavailable", {"current_position": 100}),
        ("unknown", {"current_position": 100}),
        ("open", {"current_position": 100, "restored": True}),
        ("open", {"current_position": 100, "assumed_state": True}),
    ],
)
async def test_cover_unavailable_holds_and_recovery_is_not_manual(
    hass, freezer, state, attributes
):
    moves = async_mock_service(hass, "cover", "set_cover_position")
    central, zone = await office(hass)
    runtime = central.runtime_data
    if state is None:
        hass.states.async_remove(SCREEN)
    else:
        hass.states.async_set(SCREEN, state, attributes)
    await hass.async_block_till_done()
    runtime.set_thermostat("west", screen_regulation=True)
    await hass.async_block_till_done()
    assert not moves
    assert runtime.screen_moves[EQUIPMENT].status == "cover_unavailable"
    assert EQUIPMENT not in runtime.screen_last_move
    assert not runtime.cover_tracker.pending
    sensor = entity(hass, "sensor", f"{zone.entry_id}_{EQUIPMENT}_screen")
    assert hass.states.get(sensor).attributes["current_position"] is None

    await later(hass, freezer, minutes=6)
    hass.states.async_set(SCREEN, "open", {"current_position": 100})
    await hass.async_block_till_done()
    assert [call.data["position"] for call in moves] == [0]
    assert EQUIPMENT not in runtime.screen_overrides
    assert EQUIPMENT in runtime.screen_last_move


@pytest.mark.parametrize(
    ("state", "attributes", "status"),
    [
        (None, {}, "block_unknown"),
        ("unknown", {}, "block_unknown"),
        ("unavailable", {}, "block_unknown"),
        ("on", {}, "blocked"),
        ("off", {"restored": True}, "block_unknown"),
        ("off", {"assumed_state": True}, "block_unknown"),
    ],
)
async def test_only_trustworthy_off_releases_configured_block(
    hass, freezer, state, attributes, status
):
    moves = async_mock_service(hass, "cover", "set_cover_position")
    central, _ = await block_office(hass)
    runtime = central.runtime_data
    if state is not None:
        hass.states.async_set(BLOCK, state, attributes)
    runtime.set_thermostat("west", screen_regulation=True)
    await hass.async_block_till_done()
    assert runtime.screen_moves[EQUIPMENT].status == status
    assert not moves
    assert not runtime.cover_tracker.pending
    assert EQUIPMENT not in runtime.screen_last_move
    await later(hass, freezer, minutes=6)
    hass.states.async_set(BLOCK, "off")
    await hass.async_block_till_done()
    assert [call.data["position"] for call in moves] == [0]


@pytest.mark.parametrize("change", ["cover", "block", "disable"])
async def test_screen_guard_rechecks_inputs_before_sending(hass, freezer, change):
    moves = async_mock_service(hass, "cover", "set_cover_position")
    central, _ = await block_office(hass)
    runtime = central.runtime_data
    hass.states.async_set(BLOCK, "off")
    await later(hass, freezer, minutes=6)
    ready = Event()
    original = runtime._call

    async def delayed(*args, **kwargs):
        await ready.wait()
        return await original(*args, **kwargs)

    with patch.object(runtime, "_call", delayed):
        runtime.set_thermostat("west", screen_regulation=True)
        if change == "cover":
            hass.states.async_set(SCREEN, "unavailable")
        elif change == "block":
            hass.states.async_set(BLOCK, "on")
        else:
            runtime.set_thermostat("west", screen_regulation=False)
        ready.set()
        await hass.async_block_till_done()
    assert not moves
    assert not runtime.cover_tracker.pending
    assert EQUIPMENT not in runtime.screen_last_move
    assert any(c["result"].startswith("blocked:") for c in runtime.command_log)


async def test_failed_cover_call_retries_without_recording_success(hass, freezer):
    moves = async_mock_service(
        hass,
        "cover",
        "set_cover_position",
        raise_exception=HomeAssistantError("offline"),
    )
    central, _ = await office(hass)
    await later(hass, freezer, minutes=6)
    runtime = central.runtime_data
    runtime.set_thermostat("west", screen_regulation=True)
    await hass.async_block_till_done()
    assert len(moves) == 1
    assert EQUIPMENT not in runtime.screen_last_move
    assert not runtime.cover_tracker.pending
    assert runtime.screen_moves[EQUIPMENT].status == "retry"
    runtime.refresh()
    await hass.async_block_till_done()
    assert len(moves) == 1
    recovered = async_mock_service(hass, "cover", "set_cover_position")
    await later(hass, freezer, minutes=2)
    assert len(recovered) == 1
    assert EQUIPMENT in runtime.screen_last_move
    assert EQUIPMENT not in runtime.screen_retry_at


@pytest.mark.parametrize(
    ("state", "attributes"),
    [
        (None, {}),
        ("unavailable", {"azimuth": 180, "elevation": -5}),
        ("above_horizon", {"azimuth": "south", "elevation": 50}),
        ("above_horizon", {"azimuth": 180, "elevation": float("nan")}),
        ("above_horizon", {"azimuth": 180, "elevation": float("inf")}),
        ("above_horizon", {"azimuth": 180, "elevation": 100}),
    ],
)
async def test_invalid_sun_creates_repair_and_recovery_clears_it(
    hass, freezer, state, attributes
):
    moves = async_mock_service(hass, "cover", "set_cover_position")
    central, _ = await office(hass)
    await later(hass, freezer, minutes=6)
    if state is None:
        hass.states.async_remove("sun.sun")
    else:
        hass.states.async_set("sun.sun", state, attributes)
    runtime = central.runtime_data
    runtime.set_thermostat("west", screen_regulation=True)
    await hass.async_block_till_done()
    issue_id = f"sun_unavailable_{runtime.building.id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert runtime.screen_decisions[EQUIPMENT].reason == "sun_unknown"
    assert not moves
    hass.states.async_set("sun.sun", "above_horizon", {"azimuth": 180, "elevation": 50})
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert len(moves) == 1


async def test_no_sun_repair_without_screens(hass):
    central = await setup_central(hass)
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"sun_unavailable_{central.entry_id}"
        )
        is None
    )


async def test_screen_retry_survives_central_reload(hass, freezer):
    moves = async_mock_service(
        hass,
        "cover",
        "set_cover_position",
        raise_exception=HomeAssistantError("offline"),
    )
    central, _ = await office(hass)
    await later(hass, freezer, minutes=6)
    central.runtime_data.set_thermostat("west", screen_regulation=True)
    await hass.async_block_till_done()
    retry = central.runtime_data.screen_retry_at[EQUIPMENT]
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    assert central.runtime_data.screen_retry_at[EQUIPMENT] == retry
    assert len(moves) == 1
    recovered = async_mock_service(hass, "cover", "set_cover_position")
    await later(hass, freezer, minutes=2)
    assert len(recovered) == 1


async def test_pending_confirmation_after_outage_does_not_delay_recovery(hass, freezer):
    moves = async_mock_service(hass, "cover", "set_cover_position")
    central, _ = await office(hass)
    runtime = central.runtime_data
    await later(hass, freezer, minutes=6)
    runtime.cover_tracker.register(SCREEN, "0", dt_util.utcnow())
    hass.states.async_set(SCREEN, "unavailable")
    await hass.async_block_till_done()
    runtime.set_thermostat("west", screen_regulation=True)
    hass.states.async_set(SCREEN, "open", {"current_position": 100})
    await hass.async_block_till_done()
    assert [call.data["position"] for call in moves] == [0]
    assert EQUIPMENT not in runtime.screen_overrides


async def test_sun_repair_removed_on_unload(hass):
    central, _ = await office(hass)
    hass.states.async_remove("sun.sun")
    await hass.async_block_till_done()
    issue_id = f"sun_unavailable_{central.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert await hass.config_entries.async_unload(central.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


@pytest.mark.parametrize("position", [float("nan"), float("inf"), -1, 101, True])
def test_invalid_cover_position_is_not_used(position):
    from homeassistant.core import State

    assert (
        cover_position(State(SCREEN, "opening", {"current_position": position})) is None
    )
