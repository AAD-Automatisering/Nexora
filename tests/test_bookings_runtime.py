"""Calendar-driven comfort, independent rooms and safe adaptive preparation."""

import json
from dataclasses import asdict
from datetime import timedelta

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.zonentra.bookings import ThermalRates
from custom_components.zonentra.const import DOMAIN
from custom_components.zonentra.diagnostics import async_get_config_entry_diagnostics
from tests.test_entry_layout import CELSIUS, add_zone, setup_central, zone_options
from tests.test_thermostat_runtime import clear, mock_climate
from tests.test_thermostat_runtime import later as advance

CALENDAR = "calendar.west_meeting"


async def later(hass, freezer, **delta):
    await advance(hass, freezer, **delta)
    await hass.async_block_till_done(wait_background_tasks=True)


def booking(start_minutes=60, duration=60):
    start = dt_util.utcnow() + timedelta(minutes=start_minutes)
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=duration)).isoformat(),
        "summary": "confidential board meeting",
        "description": "private agenda",
        "location": "private address",
    }


def calendar_service(hass, events, error=None):
    return async_mock_service(
        hass,
        "calendar",
        "get_events",
        response=events,
        supports_response="only",
        raise_exception=error,
    )


async def office(
    hass,
    *,
    temperature="20",
    outside="15",
    start=60,
    presence=None,
    units=False,
    group_id=None,
    **fields,
):
    hass.states.async_set(CALENDAR, "off")
    hass.states.async_set("sensor.outside", outside, CELSIUS)
    hass.states.async_set("sensor.west_temperature", temperature, CELSIUS)
    if units:
        hass.states.async_set(
            "climate.west_ac", "off", {"temperature": 22, "target_temp_step": 0.5}
        )
    central = await setup_central(hass)
    settings = {
        **central.options["building"],
        "outdoor_temperature_entity": "sensor.outside",
    }
    if presence:
        settings["presence_entity"] = presence
    hass.config_entries.async_update_entry(
        central, options={**central.options, "building": settings}
    )
    assert await hass.config_entries.async_reload(central.entry_id)
    calls = calendar_service(
        hass, {CALENDAR: {"events": [booking(start)] if start is not None else []}}
    )
    zone = await add_zone(
        hass,
        zone_options(
            "west",
            *(["climate.west_ac"] if units else []),
            group_id=group_id,
            calendar_entity=CALENDAR,
            **fields,
        ),
    )
    return central, zone, calls


async def test_winter_prepares_earlier_than_mild_weather(hass):
    central, zone, calls = await office(hass)
    runtime = central.runtime_data
    mild = runtime.booking_plans["west"]
    assert mild.status == "scheduled"
    assert runtime.zone_bands["west"] == ("eco", "no_booking")
    hass.states.async_set("sensor.outside", "-5", CELSIUS)
    await hass.async_block_till_done()
    winter = runtime.booking_plans["west"]
    assert winter.status == "preparing"
    assert winter.prepare_at < mild.prepare_at
    assert runtime.zone_bands["west"] == ("comfort", "booking_preparing")
    assert runtime.zone_demands["west"].demand == "heating_demand"
    assert calls[0].data["entity_id"] == CALENDAR
    sensor_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{zone.entry_id}_booking"
    )
    sensor = hass.states.get(sensor_id)
    assert sensor.state == "preparing"
    assert sensor.attributes["outdoor_band"] == "freezing"
    assert sensor.attributes["lead_minutes"] > 60
    assert sensor.attributes["learned_rate"] is False


async def test_preparation_and_meeting_boundaries_without_temperature_events(
    hass, freezer
):
    central, _, _ = await office(hass, temperature="21", start=45)
    runtime = central.runtime_data
    assert runtime.booking_plans["west"].status == "scheduled"
    await later(hass, freezer, minutes=10)
    assert runtime.booking_plans["west"].status == "preparing"
    await later(hass, freezer, minutes=35)
    assert runtime.booking_plans["west"].status == "meeting"
    await later(hass, freezer, minutes=60)
    assert runtime.booking_plans["west"].status == "idle"
    assert runtime.zone_bands["west"][0] == "eco"


async def test_booking_overrides_absence_until_end_and_cancellation_releases(hass):
    hass.states.async_set("input_boolean.building_present", "off")
    central, _, _ = await office(
        hass, start=20, presence="input_boolean.building_present"
    )
    runtime = central.runtime_data
    assert runtime.zone_bands["west"] == ("comfort", "booking_preparing")
    calendar_service(hass, {CALENDAR: {"events": []}})
    await runtime.async_update_bookings()
    assert runtime.booking_plans["west"].status == "idle"
    assert runtime.zone_bands["west"][0] == "away"


async def test_motion_still_allows_an_unbooked_meeting(hass):
    hass.states.async_set("binary_sensor.west_motion", "on")
    central, _, _ = await office(
        hass, start=None, occupancy_entity="binary_sensor.west_motion"
    )
    # Motion becomes confirmed after the configured sensor delay.
    runtime = central.runtime_data
    from custom_components.zonentra.presence import MotionMemory

    runtime.motion_memories["west"] = MotionMemory(True)
    runtime.refresh()
    assert runtime.booking_plans["west"].status == "idle"
    assert runtime.zone_bands["west"][0] == "comfort"


async def test_two_room_calendars_do_not_activate_each_other(hass):
    central, _, _ = await office(hass, start=120)
    other = "calendar.east_meeting"
    hass.states.async_set(other, "off")
    hass.states.async_set("sensor.east_temperature", "27", CELSIUS)
    calendar_service(
        hass, {CALENDAR: {"events": [booking(120)]}, other: {"events": [booking(30)]}}
    )
    await add_zone(hass, zone_options("east", group_id=None, calendar_entity=other))
    runtime = central.runtime_data
    assert runtime.booking_plans["west"].status == "scheduled"
    assert runtime.booking_plans["east"].status == "preparing"
    assert runtime.zone_bands["west"][0] == "eco"
    assert runtime.zone_bands["east"][0] == "comfort"
    assert runtime.zone_demands["east"].demand == "cooling_demand"


@pytest.mark.parametrize("error", ["service", "malformed", "unavailable", "stale"])
async def test_unusable_calendar_falls_back_to_normal_occupancy(hass, error):
    central, _, _ = await office(hass, start=20)
    runtime = central.runtime_data
    if error == "service":
        calendar_service(hass, {}, HomeAssistantError("unavailable"))
        await runtime.async_update_bookings()
    elif error == "malformed":
        calendar_service(hass, {CALENDAR: {"events": [None]}})
        await runtime.async_update_bookings()
    elif error == "unavailable":
        hass.states.async_set(CALENDAR, "unavailable")
        await hass.async_block_till_done()
    else:
        runtime.booking_updated[CALENDAR] -= timedelta(minutes=11)
        runtime.refresh()
    assert runtime.booking_plans["west"].status == "unknown"
    assert runtime.zone_bands["west"][0] == "comfort"  # Original no-presence fallback.
    assert not runtime._calendar_refreshing


async def test_calendar_state_change_refreshes_cancelled_booking(hass):
    central, _, _ = await office(hass, start=20)
    runtime = central.runtime_data
    calls = calendar_service(hass, {CALENDAR: {"events": []}})
    hass.states.async_set(CALENDAR, "off", {"message": "cancelled"})
    await hass.async_block_till_done()
    assert calls
    assert runtime.booking_plans["west"].status == "idle"
    assert runtime.zone_bands["west"][0] == "eco"


async def test_learning_is_separate_per_outdoor_band_and_survives_restart(
    hass, freezer
):
    mocks = await mock_climate(hass)
    central, _, _ = await office(hass, start=20, units=True)
    runtime = central.runtime_data
    runtime.set_thermostat("west", regulation=True)
    hass.states.async_set(
        "climate.west_ac",
        "heat",
        {"temperature": 22, "hvac_action": "heating"},
        context=Context(parent_id="test"),
    )
    await hass.async_block_till_done()
    await later(hass, freezer, minutes=10)
    hass.states.async_set("sensor.west_temperature", "20.5", CELSIUS)
    await hass.async_block_till_done()
    await later(hass, freezer, minutes=10)
    hass.states.async_set("sensor.west_temperature", "21", CELSIUS)
    await hass.async_block_till_done()
    assert runtime.thermal_rates["west"]["mild"].heating == pytest.approx(0.05)
    assert runtime.thermal_rates["west"]["mild"].heating_samples == 2
    hass.states.async_set("sensor.outside", "-5", CELSIUS)
    await hass.async_block_till_done()
    assert not runtime.booking_plans["west"].learned
    assert runtime.thermal_rates["west"].get("freezing", ThermalRates()).heating is None
    # Persist and recreate without adopting in-memory profiles (a full restart).
    await runtime.thermal_store.async_save(
        {
            z: {b: asdict(r) for b, r in values.items()}
            for z, values in runtime.thermal_rates.items()
        }
    )
    assert await hass.config_entries.async_unload(central.entry_id)
    hass.data[DOMAIN]["runtimes"].clear()
    assert await hass.config_entries.async_setup(central.entry_id)
    await hass.async_block_till_done()
    assert central.runtime_data.thermal_rates["west"]["mild"].heating_samples == 2
    clear(mocks)


async def test_booking_does_not_turn_on_disabled_room_regulation_or_thermostat(
    hass, freezer
):
    mocks = await mock_climate(hass)
    central, _, _ = await office(hass, start=20, units=True)
    runtime = central.runtime_data
    await later(hass, freezer, minutes=4)
    clear(mocks)
    assert runtime.booking_plans["west"].active
    runtime.refresh()
    await hass.async_block_till_done()
    assert not mocks["set_hvac_mode"]
    runtime.set_thermostat("west", regulation=True, hvac_mode="off")
    await hass.async_block_till_done()
    assert not mocks["set_hvac_mode"]


async def test_booked_room_starts_heating_when_regulation_is_enabled(hass, freezer):
    mocks = await mock_climate(hass)
    central, _, _ = await office(hass, start=20, units=True)
    runtime = central.runtime_data
    await later(hass, freezer, minutes=4)
    clear(mocks)
    runtime.set_thermostat("west", regulation=True)
    await hass.async_block_till_done()
    assert [
        (c.data["entity_id"], c.data["hvac_mode"]) for c in mocks["set_hvac_mode"]
    ] == [("climate.west_ac", "heat")]


async def test_event_titles_and_calendar_ids_are_redacted_from_diagnostics(hass):
    central, zone, _ = await office(hass, start=20)
    for entry in (central, zone):
        exported = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
        assert CALENDAR not in exported
        assert "confidential board meeting" not in exported
        assert "private agenda" not in exported
    assert "confidential" not in repr(central.runtime_data.booking_events)


async def test_overlapping_bookings_hold_comfort_until_final_end(hass, freezer):
    central, _, _ = await office(hass, start=0)
    runtime = central.runtime_data
    entries = [booking(0, 30), booking(20, 40)]
    calendar_service(hass, {CALENDAR: {"events": entries}})
    await runtime.async_update_bookings()
    await later(hass, freezer, minutes=31)
    assert runtime.booking_plans["west"].status == "meeting"
    await later(hass, freezer, minutes=30)
    assert runtime.booking_plans["west"].status == "idle"


async def test_calendar_preparation_respects_group_stop(hass, freezer):
    mocks = await mock_climate(hass)
    central, _, _ = await office(hass, start=20, units=True, group_id="outdoor_1")
    runtime = central.runtime_data
    runtime.set_mode_active("outdoor_1", False)
    await later(hass, freezer, minutes=4)
    clear(mocks)
    runtime.set_thermostat("west", regulation=True)
    await hass.async_block_till_done()
    assert runtime.booking_plans["west"].active
    assert runtime.room_controls["hvac_west_ac"].status == "group_disabled"
    assert not mocks["set_hvac_mode"]


async def test_booked_room_starts_cooling(hass, freezer):
    mocks = await mock_climate(hass)
    central, _, _ = await office(
        hass, temperature="27", outside="32", start=20, units=True
    )
    runtime = central.runtime_data
    await later(hass, freezer, minutes=4)
    clear(mocks)
    runtime.set_thermostat("west", regulation=True)
    await hass.async_block_till_done()
    assert [
        (c.data["entity_id"], c.data["hvac_mode"]) for c in mocks["set_hvac_mode"]
    ] == [("climate.west_ac", "cool")]


async def test_learned_winter_and_spring_profiles_have_distinct_start_times(hass):
    central, _, _ = await office(hass, start=120)
    runtime = central.runtime_data
    runtime.thermal_rates["west"] = {
        "mild": ThermalRates(heating=0.1, heating_samples=4),
        "freezing": ThermalRates(heating=0.025, heating_samples=4),
    }
    runtime.refresh()
    spring = runtime.booking_plans["west"]
    hass.states.async_set("sensor.outside", "-5", CELSIUS)
    await hass.async_block_till_done()
    winter = runtime.booking_plans["west"]
    assert spring.learned and winter.learned
    assert spring.rate == 0.1
    assert winter.rate == 0.025
    assert winter.lead_minutes > spring.lead_minutes * 2
    assert winter.prepare_at < spring.prepare_at


async def test_weather_current_temperature_is_used_without_outdoor_sensor(hass):
    from dataclasses import replace

    central, _, _ = await office(hass)
    runtime = central.runtime_data
    hass.states.async_set(
        "weather.building", "cloudy", {"temperature": 23, "temperature_unit": "°F"}
    )
    runtime.building = replace(
        runtime.building,
        settings=replace(
            runtime.building.settings,
            outdoor_temperature_entity=None,
            weather_entity="weather.building",
        ),
    )
    runtime.refresh()
    assert runtime._booking_outdoor_temperature() == -5
    assert runtime.booking_plans["west"].status == "preparing"


async def test_learning_ignores_idle_units_and_open_windows(hass, freezer):
    await mock_climate(hass)
    hass.states.async_set("binary_sensor.west_window", "off")
    central, _, _ = await office(
        hass, start=20, units=True, contact_entities=["binary_sensor.west_window"]
    )
    runtime = central.runtime_data
    runtime.set_thermostat("west", regulation=True)
    hass.states.async_set(
        "climate.west_ac",
        "heat",
        {"hvac_action": "idle"},
        context=Context(parent_id="test"),
    )
    await later(hass, freezer, minutes=10)
    hass.states.async_set("sensor.west_temperature", "21", CELSIUS)
    await hass.async_block_till_done()
    assert (
        runtime.thermal_rates.get("west", {}).get("mild", ThermalRates()).heating
        is None
    )
    hass.states.async_set(
        "climate.west_ac",
        "heat",
        {"hvac_action": "heating"},
        context=Context(parent_id="test"),
    )
    hass.states.async_set("binary_sensor.west_window", "on")
    await later(hass, freezer, minutes=10)
    hass.states.async_set("sensor.west_temperature", "22", CELSIUS)
    await hass.async_block_till_done()
    assert (
        runtime.thermal_rates.get("west", {}).get("mild", ThermalRates()).heating
        is None
    )


async def test_calendar_service_timeout_becomes_unknown(hass):
    central, _, _ = await office(hass, start=20)
    calendar_service(hass, {}, TimeoutError())
    await central.runtime_data.async_update_bookings()
    assert central.runtime_data.booking_plans["west"].status == "unknown"
    assert central.runtime_data.booking_errors[CALENDAR] == "service_error"
