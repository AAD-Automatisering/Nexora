"""0.11.0 integration: screens follow sunshine, sun position and room climate."""

from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.zonentra.const import DOMAIN
from tests.test_entry_layout import CELSIUS, add_zone, setup_central, zone_options
from tests.test_thermostat_runtime import later

SCREEN = "cover.west_screen"
EQUIPMENT = "shade_west_screen"


def entity(hass, platform, unique_id):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)


async def office(hass):
    hass.states.async_set("sensor.west_temperature", "23.5", CELSIUS)
    hass.states.async_set("sensor.solar_power", "2500", {"unit_of_measurement": "W"})
    hass.states.async_set("sun.sun", "above_horizon", {"azimuth": 180, "elevation": 50})
    hass.states.async_set(SCREEN, "open", {"current_position": 100})
    central = await setup_central(hass)
    building = {**central.options["building"], "sun_power_entity": "sensor.solar_power"}
    hass.config_entries.async_update_entry(
        central, options={**central.options, "building": building}
    )
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    zone = await add_zone(
        hass, zone_options("west", shading_entities=[SCREEN], facade="south")
    )
    return central, zone


async def test_screen_simulates_then_shades_and_respects_people(hass, freezer):
    moves = async_mock_service(hass, "cover", "set_cover_position")
    central, zone = await office(hass)
    runtime = central.runtime_data
    sensor_id = entity(hass, "sensor", f"{zone.entry_id}_{EQUIPMENT}_screen")
    # Sunshine needs 5 minutes of solar power above the threshold.
    assert hass.states.get(sensor_id).attributes["reason"] == "no_sun"
    await later(hass, freezer, minutes=6)
    state = hass.states.get(sensor_id)
    # Sun on the south facade and a warm room (23.5 °C in 22-24): down.
    assert state.state == "shade"
    assert state.attributes["reason"] == "room_warm"
    assert state.attributes["status"] == "simulation"  # Off by default.
    assert moves == []

    switch_id = entity(hass, "switch", f"{zone.entry_id}_screen_regulation")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert [call.data["position"] for call in moves] == [0]
    hass.states.async_set(SCREEN, "closing", {"current_position": 40})
    hass.states.async_set(SCREEN, "closed", {"current_position": 0})
    await hass.async_block_till_done()
    assert runtime.last_transitions[EQUIPMENT][0] == "zonentra_screen"
    assert EQUIPMENT not in runtime.screen_overrides

    # A person opens it in Home Assistant: respected for 2 hours.
    hass.states.async_set(
        SCREEN, "open", {"current_position": 100}, context=Context(user_id="u")
    )
    await hass.async_block_till_done()
    assert EQUIPMENT in runtime.screen_overrides
    await later(hass, freezer, minutes=30)
    assert len(moves) == 1
    assert runtime.screen_moves[EQUIPMENT].status == "manual_override"
    await later(hass, freezer, minutes=91)
    assert [call.data["position"] for call in moves] == [0, 0]


async def test_night_and_heating_open_the_screen(hass, freezer):
    async_mock_service(hass, "cover", "set_cover_position")
    central, zone = await office(hass)
    runtime = central.runtime_data
    await later(hass, freezer, minutes=6)
    hass.states.async_set("sensor.west_temperature", "20", CELSIUS)  # Heating.
    await hass.async_block_till_done()
    assert runtime.screen_decisions[EQUIPMENT].reason == "solar_gain_heating"
    hass.states.async_set("sun.sun", "below_horizon", {"azimuth": 300, "elevation": -4})
    await hass.async_block_till_done()
    decision = runtime.screen_decisions[EQUIPMENT]
    assert (decision.target, decision.reason, decision.position) == (
        "open",
        "night",
        100,
    )
