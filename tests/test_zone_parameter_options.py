"""Visible local parameters can be cleared without deleting dormant settings."""

from homeassistant.data_entry_flow import FlowResultType

from custom_components.zonentra.const import DOMAIN
from tests.test_entry_layout import (
    CELSIUS,
    add_zone,
    set_states,
    setup_central,
    zone_options,
)

HEAT = "input_number.west_heat"
COOL = "input_number.west_cool"


async def local_zone(hass, **fields):
    set_states(hass, "west")
    hass.states.async_set(HEAT, "19", CELSIUS)
    hass.states.async_set(COOL, "26", CELSIUS)
    central = await setup_central(hass)
    zone = await add_zone(
        hass,
        zone_options(
            "west",
            use_building_limits=False,
            heating_limit_entity=HEAT,
            cooling_limit_entity=COOL,
            **fields,
        ),
    )
    return central, zone


async def parameters(hass, zone, **changes):
    flow = await hass.config_entries.options.async_init(zone.entry_id)
    values = {
        key: value
        for key, value in zone.options.items()
        if key
        not in (
            "id",
            "heating_limit_entity",
            "cooling_limit_entity",
            "hysteresis",
            "sensor_validation",
            "max_age_seconds",
        )
    }
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**values, **changes}
    )
    assert flow["step_id"] == "zone_parameters"
    return flow


async def test_clearing_local_limit_entities_removes_sources_and_uses_fallback(hass):
    central, zone = await local_zone(
        hass, hysteresis=0.4, sensor_validation="update_based", max_age_seconds=600
    )
    flow = await parameters(hass, zone)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    assert flow["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "heating_limit_entity" not in zone.options
    assert "cooling_limit_entity" not in zone.options
    assert zone.options["hysteresis"] == 0.4
    assert zone.options["sensor_validation"] == "update_based"
    assert zone.options["max_age_seconds"] == 600
    runtime = central.runtime_data
    assert HEAT not in runtime.building.entity_ids
    assert COOL not in runtime.building.entity_ids
    snapshot = runtime.zone_snapshots["west"]
    assert (snapshot.heating_limit.value, snapshot.cooling_limit.value) == (22, 24)
    hass.states.async_set(HEAT, "17", CELSIUS)
    await hass.async_block_till_done()
    assert runtime.zone_snapshots["west"].heating_limit.value == 22


async def test_hidden_limit_entities_survive_editing_only_local_parameters(hass):
    _, zone = await local_zone(
        hass,
        use_building_parameters=False,
        hysteresis=0.4,
        sensor_validation="state_based",
        max_age_seconds=600,
    )
    flow = await parameters(hass, zone, use_building_limits=True)
    assert "heating_limit_entity" not in flow["data_schema"].schema
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"hysteresis": 0.5}
    )
    assert flow["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert zone.options["heating_limit_entity"] == HEAT
    assert zone.options["cooling_limit_entity"] == COOL
    assert zone.options["hysteresis"] == 0.5
    assert "max_age_seconds" not in zone.options


async def test_partial_clear_is_validated_before_saving_and_can_be_corrected(hass):
    _, zone = await local_zone(hass)
    previous = dict(zone.options)
    flow = await parameters(hass, zone)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"heating_limit_entity": HEAT}
    )
    assert flow["type"] == FlowResultType.FORM
    assert flow["errors"] == {"base": "invalid_limits"}
    assert dict(zone.options) == previous
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    assert flow["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "heating_limit_entity" not in zone.options
    assert "cooling_limit_entity" not in zone.options


async def test_new_zone_can_clear_a_limit_after_validation_error(hass):
    set_states(hass, "west")
    hass.states.async_set(HEAT, "19", CELSIUS)
    central = await setup_central(hass)
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "zone"}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "name": "West",
            "temperature_entity": "sensor.west_temperature",
            "use_building_limits": False,
            "use_building_parameters": True,
        },
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"heating_limit_entity": HEAT}
    )
    assert flow["errors"] == {"base": "invalid_limits"}
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert flow["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "heating_limit_entity" not in flow["result"].options
    assert HEAT not in central.runtime_data.building.entity_ids
