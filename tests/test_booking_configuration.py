"""Room calendars are optional, validated and removable through options."""

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.zonentra.models import build_model
from tests.test_bookings_runtime import CALENDAR, calendar_service, office


@pytest.mark.parametrize(
    "settings",
    [
        {"calendar_entity": "sensor.wrong_domain"},
        {"preconditioning_heating_rate": 0},
        {"preconditioning_cooling_rate": float("nan")},
        {"preconditioning_max_minutes": 361},
        {"preconditioning_buffer_minutes": -1},
        {"preconditioning_max_minutes": True},
    ],
)
def test_booking_configuration_rejects_invalid_values(settings):
    with pytest.raises(ValueError):
        build_model(
            "test", "Test", {"zones": [{"id": "west", "name": "West", **settings}]}
        )


async def test_calendar_can_be_changed_and_removed_using_room_options(hass):
    central, zone, _ = await office(hass)
    other = "calendar.other_meeting"
    hass.states.async_set(other, "off")
    calendar_service(hass, {other: {"events": []}})
    flow = await hass.config_entries.options.async_init(zone.entry_id)
    assert "calendar_entity" in flow["data_schema"].schema
    values = {
        "name": "West",
        "temperature_entity": "sensor.west_temperature",
        "calendar_entity": other,
        "preconditioning_max_minutes": 120,
        "preconditioning_buffer_minutes": 15,
        "preconditioning_heating_rate": 0.04,
        "preconditioning_cooling_rate": 0.06,
        "use_building_limits": True,
        "use_building_parameters": True,
    }
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], values)
    assert flow["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    runtime = central.runtime_data
    room = runtime.building.zones[0]
    assert room.calendar_entity == other
    assert room.preconditioning_max_minutes == 120
    assert room.preconditioning_buffer_minutes == 15
    assert CALENDAR not in runtime.building.entity_ids
    assert other in runtime.building.entity_ids
    values.pop("calendar_entity")
    flow = await hass.config_entries.options.async_init(zone.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], values)
    assert flow["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert central.runtime_data.building.zones[0].calendar_entity is None
    assert central.runtime_data.booking_plans["west"].status == "not_configured"
    assert other not in central.runtime_data.building.entity_ids
