"""Review regressions: verify corrected behavior and the original controls."""

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.zonentra.config_flow import merge_zone, merge_zone_parameters
from custom_components.zonentra.models import build_model
from custom_components.zonentra.runtime import BuildingRuntime
from tests.test_entry_layout import (
    CELSIUS,
    add_zone,
    set_states,
    setup_central,
    zone_options,
)
from tests.test_mode_control_runtime import UNIT, mock_climate, office
from tests.test_thermostat_runtime import later


async def test_review_group_switch_off_blocks_room_commands(hass, freezer):
    set_mode, _ = await mock_climate(hass)
    central, _ = await office(hass)
    runtime = central.runtime_data
    runtime.set_mode_active("outdoor_1", False)
    runtime.command_tracker.cancel(UNIT)
    set_mode.clear()
    await later(hass, freezer, minutes=4)
    runtime.set_thermostat("west", regulation=True)
    await hass.async_block_till_done()
    assert runtime.mode_active["outdoor_1"] is False
    assert set_mode == []
    assert runtime.room_controls["hvac_west_ac"].status == "group_disabled"


async def test_review_disabled_zone_leaves_active_runtime(hass, freezer):
    set_mode, _ = await mock_climate(hass)
    central, zone = await office(hass)
    runtime = central.runtime_data
    runtime.set_mode_active("outdoor_1", False)
    runtime.command_tracker.cancel(UNIT)
    await later(hass, freezer, minutes=4)
    runtime.set_thermostat("west", regulation=True)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_set_disabled_by(
        zone.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert zone.disabled_by is ConfigEntryDisabler.USER
    assert "west" not in central.runtime_data.zone_demands
    set_mode.clear()
    hass.states.async_set("sensor.west_temperature", "20.5", CELSIUS)
    await hass.async_block_till_done()
    assert not set_mode


async def test_review_failed_preset_is_not_applied_and_is_retried_for_off_unit(
    hass, freezer
):
    await mock_climate(hass)
    commands = async_mock_service(
        hass,
        "climate",
        "set_hvac_mode",
        raise_exception=HomeAssistantError("review failure"),
    )
    central, _ = await office(hass)
    runtime = central.runtime_data
    assert "outdoor_1" not in runtime.preset_memories
    assert any(c["result"].startswith("failed:") for c in runtime.command_log)
    count = len(commands)
    await later(hass, freezer, minutes=20)
    runtime.refresh()
    await hass.async_block_till_done()
    assert len(commands) > count
    assert runtime.mode_controls["outdoor_1"].status == "preset_retry"
    assert hass.states.get(UNIT).state == "off"


def test_review_cleared_limit_entities_are_removed_from_zone_parameters():
    previous = {
        "id": "west",
        "name": "West",
        "use_building_limits": False,
        "heating_limit_entity": "input_number.heat",
        "cooling_limit_entity": "input_number.cool",
    }
    first = merge_zone(previous, {"name": "West", "use_building_limits": False})
    second = merge_zone_parameters(
        first, {"heating_limit_entity": "", "cooling_limit_entity": ""}
    )
    assert "heating_limit_entity" not in second
    assert "cooling_limit_entity" not in second


async def test_review_removed_local_limit_entities_use_central_limits(hass):
    set_states(hass, "west")
    hass.states.async_set("input_number.heat", "19", CELSIUS)
    hass.states.async_set("input_number.cool", "26", CELSIUS)
    central = await setup_central(hass)
    await add_zone(
        hass,
        zone_options(
            "west",
            use_building_limits=False,
            heating_limit_entity="input_number.heat",
            cooling_limit_entity="input_number.cool",
        ),
    )
    snapshot = central.runtime_data.zone_snapshots["west"]
    assert (snapshot.heating_limit.value, snapshot.cooling_limit.value) == (22, 24)
    hass.states.async_set("input_number.heat", "18", CELSIUS)
    await hass.async_block_till_done()
    assert central.runtime_data.zone_snapshots["west"].heating_limit.value == 22


async def test_review_unavailable_cover_is_not_commanded(hass):
    moves = async_mock_service(hass, "cover", "set_cover_position")
    from tests.test_shading_runtime import SCREEN
    from tests.test_shading_runtime import office as screen_office

    central, _ = await screen_office(hass)
    hass.states.async_set(SCREEN, "unavailable")
    central.runtime_data.set_thermostat("west", screen_regulation=True)
    await hass.async_block_till_done()
    assert not moves
    assert (
        central.runtime_data.screen_moves["shade_west_screen"].status
        == "cover_unavailable"
    )


async def test_review_fahrenheit_forecast_is_converted_to_celsius(hass):
    from tests.test_forecast_runtime import WEATHER, weather
    from tests.test_forecast_runtime import office as forecast_office

    weather(hass, 41, 50)
    hass.states.async_set(WEATHER, "cloudy", {"temperature_unit": "°F"})
    central, _ = await forecast_office(hass)
    assert central.runtime_data.day_type == "cold"
    assert central.runtime_data.forecast.maximum == 10


async def test_review_fahrenheit_limits_are_converted_for_setpoint_planner(hass):
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    hass.config.units = US_CUSTOMARY_SYSTEM
    hass.states.async_set("sensor.west_temperature", "20", CELSIUS)
    hass.states.async_set(
        UNIT,
        "heat",
        {"temperature": 68, "min_temp": 60, "max_temp": 86, "target_temp_step": 1},
    )
    model = build_model(
        "review",
        "Review",
        {
            "building": {"heating_limit": 22, "cooling_limit": 24},
            "zones": [
                {
                    "id": "west",
                    "name": "West",
                    "temperature_entity": "sensor.west_temperature",
                }
            ],
            "equipment": [
                {
                    "id": "ac",
                    "name": "AC",
                    "kind": "hvac",
                    "zone_id": "west",
                    "entity_id": UNIT,
                }
            ],
        },
    )
    runtime = BuildingRuntime(hass, model)
    runtime.refresh()
    item, zone = model.equipment[0], model.zones[0]
    plan = runtime._setpoint_plan(item, zone, model.settings, dt_util.utcnow())
    assert round(plan.setpoint, 3) == 24.444  # 76 °F on the native one-degree grid.
    runtime.close()


async def test_review_diagnostics_redact_new_source_entity_ids(hass):
    from custom_components.zonentra.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    central = await setup_central(hass)
    settings = {
        **central.options["building"],
        "presence_entity": "alarm_control_panel.private_office",
        "sun_power_entity": "sensor.private_solar",
        "screen_block_entity": "binary_sensor.private_wind",
        "weather_entity": "weather.private_address",
    }
    hass.config_entries.async_update_entry(
        central, options={**central.options, "building": settings}
    )
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, central)
    assert (
        result["configuration"]["options"]["building"]["presence_entity"]
        == "**REDACTED**"
    )
    assert (
        result["configuration"]["options"]["building"]["weather_entity"]
        == "**REDACTED**"
    )
