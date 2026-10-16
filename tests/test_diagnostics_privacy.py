"""Configuration sources and device identifiers must be redacted in exports."""

import json

from custom_components.zonentra.diagnostics import async_get_config_entry_diagnostics
from tests.test_entry_layout import add_zone, set_states, setup_central, zone_options


async def test_central_and_zone_exports_redact_sources_and_equipment_keys(hass):
    sources = {
        "outdoor_temperature_entity": "sensor.private_outdoor",
        "heating_limit_entity": "input_number.private_heat",
        "cooling_limit_entity": "input_number.private_cool",
        "presence_entity": "alarm_control_panel.private_presence",
        "sun_power_entity": "sensor.private_power",
        "sun_entity": "sun.private_position",
        "screen_block_entity": "input_boolean.private_wind",
        "weather_entity": "weather.private_address",
    }
    central = await setup_central(hass)
    hass.config_entries.async_update_entry(
        central,
        options={
            **central.options,
            "building": {**central.options["building"], **sources},
        },
    )
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    unit = "climate.private_ac"
    set_states(hass, "west", unit)
    zone = await add_zone(
        hass,
        zone_options(
            "west",
            unit,
            vane_entity="select.private_vane",
            vane_heat_value="down",
            vane_cool_value="up",
        ),
    )
    for entry in (central, zone):
        data = await async_get_config_entry_diagnostics(hass, entry)
        encoded = json.dumps(data)
        for source in (
            *sources.values(),
            unit,
            "select.private_vane",
            "sensor.west_temperature",
        ):
            assert source not in encoded
        assert "hvac_private_ac" not in encoded
        assert "**REDACTED**" in encoded
    central_data = await async_get_config_entry_diagnostics(hass, central)
    building = central_data["configuration"]["options"]["building"]
    removed = {"heating_limit_entity", "cooling_limit_entity"}
    assert removed.isdisjoint(building)
    assert all(building[key] == "**REDACTED**" for key in sources.keys() - removed)
    zone_data = await async_get_config_entry_diagnostics(hass, zone)
    assert zone_data["room_regulation"][0]["equipment_id"] == "**REDACTED**"
    assert zone_data["room_regulation"][0]["status"] == "simulation"
