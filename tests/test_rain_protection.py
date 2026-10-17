"""Rain opens screens promptly; only fresh, continuous dry reports release shade."""

from datetime import timedelta

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.zonentra.diagnostics import async_get_config_entry_diagnostics
from custom_components.zonentra.models import build_model
from custom_components.zonentra.rain import RainMemory, current_rain, rain_protection
from tests.test_followup_improvements import restart_central
from tests.test_shading_runtime import EQUIPMENT, SCREEN, office
from tests.test_thermostat_runtime import later

WEATHER = "weather.pirateweather"


@pytest.mark.parametrize(
    "value",
    [
        "rainy",
        "pouring",
        "lightning",
        "lightning-rainy",
        "hail",
        "snowy",
        "snowy-rainy",
    ],
)
def test_current_precipitation_conditions(value):
    assert current_rain(value, "weather") is True


@pytest.mark.parametrize(
    "value",
    ["sunny", "cloudy", "partlycloudy", "clear-night", "fog", "windy", "windy-variant"],
)
def test_current_dry_conditions(value):
    assert current_rain(value, "weather") is False


@pytest.mark.parametrize(
    "value", ["unknown", "unavailable", "exceptional", "", "rain", "80"]
)
def test_unknown_conditions_are_not_proof_of_dry_weather(value):
    assert current_rain(value, "weather") is None


def test_binary_rain_input():
    assert current_rain("on", "binary_sensor") is True
    assert current_rain("off", "binary_sensor") is False
    assert current_rain("on", "sensor") is None


def test_continuous_dry_hold_resets_on_rain_and_unknown():
    now = dt_util.utcnow()
    wet = rain_protection(True, RainMemory(), now, 30)
    assert wet.open_required and wet.block_closing
    dry = rain_protection(False, wet.memory, now, 30)
    assert dry.status == "drying"
    assert dry.next_check == now + timedelta(minutes=30)
    unknown = rain_protection(None, dry.memory, now + timedelta(minutes=29), 30)
    assert unknown.open_required and unknown.memory.dry_since is None
    resumed = rain_protection(False, unknown.memory, now + timedelta(minutes=30), 30)
    assert resumed.next_check == now + timedelta(minutes=60)
    assert (
        rain_protection(False, resumed.memory, now + timedelta(minutes=60), 30).status
        == "dry"
    )
    assert (
        rain_protection(
            True, dry.memory, now + timedelta(minutes=29), 30
        ).memory.dry_since
        is None
    )
    assert rain_protection(None, RainMemory(), now, 30).block_closing


async def rainy_office(hass, *, weather="sunny", **settings):
    moves = async_mock_service(hass, "cover", "set_cover_position")
    hass.states.async_set(WEATHER, weather)
    central, room = await office(hass, weather_entity=WEATHER, **settings)
    runtime = central.runtime_data
    runtime.set_thermostat("west", screen_regulation=True)
    await hass.async_block_till_done()
    return central, room, moves


async def report_rain(hass, state):
    hass.states.async_set(WEATHER, state)
    await hass.async_block_till_done()


async def lower_screen(hass, runtime):
    # Simulate a screen already lowered recently: rain must bypass both a
    # manual pause and the normal minimum movement interval.
    hass.states.async_set(
        SCREEN, "closed", {"current_position": 0}, context=Context(user_id="person")
    )
    await hass.async_block_till_done()
    runtime.screen_last_move[EQUIPMENT] = dt_util.utcnow()


async def test_rain_opens_immediately_despite_manual_pause_interval_and_bad_sun(hass):
    central, _, moves = await rainy_office(hass)
    runtime = central.runtime_data
    await lower_screen(hass, runtime)
    assert runtime.screen_overrides
    hass.states.async_set("sun.sun", "unavailable")
    await report_rain(hass, "rainy")
    assert [call.data["position"] for call in moves] == [100]
    assert runtime.screen_decisions[EQUIPMENT].reason == "rain"
    assert runtime.rain.open_required
    hass.states.async_set(SCREEN, "open", {"current_position": 100})
    await hass.async_block_till_done()
    await report_rain(hass, "pouring")
    assert len(moves) == 1


async def test_dry_hold_then_normal_closing_stability(hass, freezer):
    central, _, moves = await rainy_office(hass)
    runtime = central.runtime_data
    runtime.set_thermostat("west", screen_regulation=False)
    hass.states.async_set(SCREEN, "closed", {"current_position": 0})
    await hass.async_block_till_done()
    runtime.screen_overrides.clear()
    runtime.set_thermostat("west", screen_regulation=True)
    await report_rain(hass, "rainy")
    hass.states.async_set(SCREEN, "open", {"current_position": 100})
    await hass.async_block_till_done()
    await report_rain(hass, "sunny")
    assert runtime.rain.status == "drying"
    await later(hass, freezer, minutes=29)
    assert [call.data["position"] for call in moves] == [100]
    await later(hass, freezer, minutes=1)
    assert runtime.rain.status == "dry"
    assert runtime.screen_moves[EQUIPMENT].status == "stabilizing"
    await later(hass, freezer, minutes=5)
    assert [call.data["position"] for call in moves] == [100, 0]


async def test_rain_respects_block_and_regulation_switch(hass):
    hass.states.async_set("binary_sensor.wind_lock", "on")
    central, _, moves = await rainy_office(
        hass, screen_block_entity="binary_sensor.wind_lock"
    )
    runtime = central.runtime_data
    await lower_screen(hass, runtime)
    await report_rain(hass, "rainy")
    assert moves == []
    assert runtime.screen_moves[EQUIPMENT].status == "blocked"
    runtime.set_thermostat("west", screen_regulation=False)
    hass.states.async_set("binary_sensor.wind_lock", "off")
    await hass.async_block_till_done()
    assert moves == []
    runtime.set_thermostat("west", screen_regulation=True)
    await hass.async_block_till_done()
    assert [call.data["position"] for call in moves] == [100]


async def test_queued_close_is_rejected_when_live_weather_turns_wet(hass):
    central, _, moves = await rainy_office(hass)
    runtime = central.runtime_data
    item = next(i for i in runtime.building.equipment if i.kind == "shading")
    # No refresh: the final dispatcher must read the current state itself.
    hass.states.async_set(WEATHER, "rainy")
    entry = {"equipment_id": item.id, "reason": "screen_cooling"}
    assert not await runtime._call(
        "set_cover_position", {"entity_id": SCREEN, "position": 0}, entry, "cover"
    )
    assert entry["result"] == "blocked: rain_blocked"
    assert moves == []


async def test_rain_preempts_closing_at_top_and_supersedes_close_receipt(hass):
    central, _, moves = await rainy_office(hass)
    runtime = central.runtime_data
    hass.states.async_set(SCREEN, "closing", {"current_position": 100})
    runtime.cover_tracker.register(SCREEN, "0", dt_util.utcnow())
    await report_rain(hass, "rainy")
    assert [call.data["position"] for call in moves] == [100]
    assert runtime.cover_tracker.pending[0].expected_state == "100"
    await report_rain(hass, "pouring")
    assert len(moves) == 1


async def test_stale_weather_does_not_clear_rain_or_allow_lowering(hass, freezer):
    central, _, moves = await rainy_office(hass, screen_rain_max_age_minutes=10)
    runtime = central.runtime_data
    await lower_screen(hass, runtime)
    await report_rain(hass, "rainy")
    hass.states.async_set(SCREEN, "open", {"current_position": 100})
    await hass.async_block_till_done()
    await report_rain(hass, "sunny")
    await later(hass, freezer, minutes=11)
    assert runtime.rain.status == "unknown"
    assert runtime.rain.open_required
    await later(hass, freezer, minutes=20)
    assert [call.data["position"] for call in moves] == [100]
    await report_rain(hass, "sunny")
    assert runtime.rain.status == "drying"
    assert runtime.rain.next_check == dt_util.utcnow() + timedelta(minutes=30)


async def test_unknown_weather_initially_holds_downward_moves(hass, freezer):
    central, _, moves = await rainy_office(
        hass, weather="unavailable", screen_wind_protection=False
    )
    await later(hass, freezer, minutes=10)
    runtime = central.runtime_data
    assert runtime.rain.status == "unknown"
    assert runtime.screen_decisions[EQUIPMENT].reason == "rain_unknown"
    assert moves == []


async def test_optional_binary_rain_source_overrides_weather_condition(hass):
    hass.states.async_set("binary_sensor.rain", "on")
    central, _, moves = await rainy_office(
        hass, screen_rain_entity="binary_sensor.rain"
    )
    runtime = central.runtime_data
    await lower_screen(hass, runtime)
    assert [call.data["position"] for call in moves] == [100]
    assert runtime.rain.status == "rain"
    assert runtime.rain_source == "binary_sensor.rain"


async def test_rain_switch_off_preserves_regular_shading(hass, freezer):
    central, _, moves = await rainy_office(
        hass,
        weather="rainy",
        screen_rain_protection=False,
        screen_shade_delay_minutes=0,
    )
    runtime = central.runtime_data
    await later(hass, freezer, minutes=10)
    assert runtime.rain.status == "disabled"
    assert [call.data["position"] for call in moves] == [0]


async def test_rain_latch_survives_restart_and_dry_time_restarts(hass, freezer):
    central, _, _ = await rainy_office(hass)
    runtime = central.runtime_data
    await report_rain(hass, "rainy")
    await report_rain(hass, "sunny")
    await later(hass, freezer, minutes=20)
    await later(hass, freezer, seconds=2)
    runtime = await restart_central(hass, central)
    assert runtime.rain.status == "drying"
    assert runtime.rain.next_check == dt_util.utcnow() + timedelta(minutes=30)


async def test_rain_latch_and_dry_deadline_survive_configuration_reload(hass, freezer):
    central, _, _ = await rainy_office(hass)
    await report_rain(hass, "rainy")
    await report_rain(hass, "sunny")
    deadline = central.runtime_data.rain.next_check
    await later(hass, freezer, minutes=10)
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    assert central.runtime_data.rain.next_check == deadline


async def test_rain_diagnostics_redact_source_and_explain_hold(hass):
    central, room, _ = await rainy_office(hass, weather="rainy")
    for entry in [central, room]:
        data = await async_get_config_entry_diagnostics(hass, entry)
        assert WEATHER not in str(data)
        assert data["screen_rain"]["status"] == "rain"
        assert data["screen_rain"]["entity_id"] == "**REDACTED**"


async def test_failed_rain_open_retries_without_tight_loop(hass, freezer):
    central, _, moves = await rainy_office(hass)
    runtime = central.runtime_data
    await lower_screen(hass, runtime)
    failures = async_mock_service(
        hass,
        "cover",
        "set_cover_position",
        raise_exception=HomeAssistantError("offline"),
    )
    await report_rain(hass, "rainy")
    assert len(failures) == 1
    assert runtime.screen_moves[EQUIPMENT].status == "retry"
    await later(hass, freezer, seconds=119)
    assert len(failures) == 1
    await later(hass, freezer, seconds=1)
    assert len(failures) == 2
    assert moves == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("screen_rain_protection", 1),
        ("screen_rain_entity", "sensor.rain_probability"),
        ("screen_rain_dry_minutes", 0),
        ("screen_rain_max_age_minutes", float("nan")),
    ],
)
def test_invalid_rain_config(key, value):
    with pytest.raises(ValueError):
        build_model("test", "Test", {"building": {key: value}})


async def test_precipitation_forecast_or_chance_is_not_current_rain(hass):
    central, _, _ = await rainy_office(hass)
    hass.states.async_set(
        WEATHER,
        "sunny",
        {
            "precipitation_probability": 100,
            "forecast": [{"condition": "rainy", "precipitation": 10}],
        },
    )
    await hass.async_block_till_done()
    assert central.runtime_data.rain.status == "dry"


async def test_failed_close_backoff_does_not_delay_rain_open(hass):
    central, _, moves = await rainy_office(hass)
    runtime = central.runtime_data
    await lower_screen(hass, runtime)
    runtime.screen_retry_at[EQUIPMENT] = dt_util.utcnow() + timedelta(minutes=2)
    runtime.screen_retry_targets[EQUIPMENT] = 0
    await report_rain(hass, "rainy")
    assert [call.data["position"] for call in moves] == [100]


async def test_changing_rain_source_restarts_existing_dry_hold(hass, freezer):
    central, _, _ = await rainy_office(hass)
    runtime = central.runtime_data
    await report_rain(hass, "rainy")
    await report_rain(hass, "sunny")
    await later(hass, freezer, minutes=20)
    hass.states.async_set("binary_sensor.rain", "off")
    from dataclasses import replace

    runtime.apply_building(
        replace(
            runtime.building,
            settings=replace(
                runtime.building.settings, screen_rain_entity="binary_sensor.rain"
            ),
        )
    )
    assert runtime.rain.status == "drying"
    assert runtime.rain.next_check == dt_util.utcnow() + timedelta(minutes=30)


async def test_rain_fully_opens_even_when_normal_position_tolerance_would_hold(hass):
    central, _, moves = await rainy_office(hass)
    hass.states.async_set(
        SCREEN, "open", {"current_position": 95}, context=Context(user_id="person")
    )
    await report_rain(hass, "rainy")
    assert [call.data["position"] for call in moves] == [100]
    assert central.runtime_data.screen_decisions[EQUIPMENT].position == 100


async def test_unchanged_available_binary_rain_sensor_is_state_based(hass):
    hass.states.async_set(
        "binary_sensor.rain",
        "off",
        timestamp=(dt_util.utcnow() - timedelta(hours=2)).timestamp(),
    )
    central, _, _ = await rainy_office(hass, screen_rain_entity="binary_sensor.rain")
    assert central.runtime_data.rain.status == "dry"
    assert central.runtime_data._rain_expiry(dt_util.utcnow()) is None
