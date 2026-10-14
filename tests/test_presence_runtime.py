"""0.8.0 integration: presence and motion select comfort / eco / away bands."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.zonentra.const import DOMAIN
from tests.test_entry_layout import add_zone, set_states, setup_central, zone_options

CELSIUS = {"unit_of_measurement": "°C"}
PRESENCE = "binary_sensor.office_occupied"
MOTION = "binary_sensor.office_motion"


async def setup_office(hass):
    hass.states.async_set("sensor.office_temperature", "20", CELSIUS)
    hass.states.async_set(PRESENCE, "on")
    hass.states.async_set(MOTION, "on")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office",
        data={"name": "Office"},
        options={
            "building": {
                "heating_limit": 21,
                "cooling_limit": 24,
                "hysteresis": 0.3,
                "presence_entity": PRESENCE,
            },
            "zones": [
                {
                    "id": "office",
                    "name": "Office",
                    "temperature_entity": "sensor.office_temperature",
                    "occupancy_entity": MOTION,
                    "use_building_limits": True,
                    "use_building_parameters": True,
                }
            ],
            "groups": [],
            "equipment": [],
        },
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def demand(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_zone_office_demand"
    )
    return hass.states.get(entity_id)


async def fire(hass, moment):
    with patch("homeassistant.util.dt.utcnow", return_value=moment):
        async_fire_time_changed(hass, moment)
        await hass.async_block_till_done()


async def test_motion_delays_and_presence_bands(hass, freezer):
    entry = await setup_office(hass)
    start = dt_util.utcnow()
    # Motion just started: not yet confirmed, so the eco band (19 °C) applies.
    state = demand(hass, entry)
    assert state.attributes["occupancy_mode"] == "eco"
    assert state.attributes["heating_limit_c"] == 19
    assert state.state == "neutral"
    # After the 30 s detection delay: comfort band (21 °C) -> heating demand.
    await fire(hass, start + timedelta(seconds=31))
    state = demand(hass, entry)
    assert state.attributes["occupancy_mode"] == "comfort"
    assert state.attributes["motion"] == "active"
    assert state.state == "heating_demand"
    # Motion stops: the zone stays occupied for 30 minutes.
    freezer.move_to(start + timedelta(minutes=1))
    hass.states.async_set(MOTION, "off")
    await hass.async_block_till_done()
    assert demand(hass, entry).attributes["occupancy_mode"] == "comfort"
    await fire(hass, start + timedelta(minutes=31, seconds=1))
    state = demand(hass, entry)
    assert state.attributes["occupancy_mode"] == "eco"
    assert state.attributes["occupancy_reason"] == "no_motion"
    # The building becomes absent: away band (16 °C), whatever the motion.
    hass.states.async_set(MOTION, "on")
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    state = demand(hass, entry)
    assert state.attributes["occupancy_mode"] == "away"
    assert state.attributes["building_presence"] == "absent"
    assert state.attributes["heating_limit_c"] == 16
    assert state.state == "neutral"


async def test_unavailable_presence_keeps_comfort(hass):
    entry = await setup_office(hass)
    hass.states.async_set(PRESENCE, "unavailable")
    hass.states.async_set(MOTION, "unavailable")
    await hass.async_block_till_done()
    state = demand(hass, entry)
    assert state.attributes["occupancy_mode"] == "comfort"
    assert state.attributes["occupancy_reason"] == "motion_sensor_unknown"
    assert state.state == "heating_demand"


async def test_thermostat_preset_follows_absence(hass):
    """0.10: an absent building shows preset away and the away limits."""
    set_states(hass, "west", "climate.west_ac")
    hass.states.async_set(PRESENCE, "on")
    central = await setup_central(hass)
    building = {**central.options["building"], "presence_entity": PRESENCE}
    hass.config_entries.async_update_entry(
        central, options={**central.options, "building": building}
    )
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    zone = await add_zone(hass, zone_options("west", "climate.west_ac"))
    climate_id = er.async_get(hass).async_get_entity_id(
        "climate", DOMAIN, f"{zone.entry_id}_thermostat"
    )
    assert hass.states.get(climate_id).attributes["preset_mode"] == "comfort"
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    thermostat = hass.states.get(climate_id)
    assert thermostat.attributes["preset_mode"] == "away"
    assert thermostat.attributes["chosen_preset"] == "comfort"
    assert (
        thermostat.attributes["target_temp_low"],
        thermostat.attributes["target_temp_high"],
    ) == (16, 30)
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert hass.states.get(climate_id).attributes["preset_mode"] == "comfort"
