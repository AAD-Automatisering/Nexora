"""Real HA events, deadlines, restart protection, UI and diagnostic entities."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.zonentra.const import DOMAIN
from custom_components.zonentra.diagnostics import async_get_config_entry_diagnostics


async def setup_intelligence(hass, topology, max_age=1800, validation=None):
    if validation:
        topology["zones"][0]["sensor_validation"] = validation
    topology["zones"][0].update(
        heating_limit=21,
        cooling_limit=24,
        max_age_seconds=max_age,
        occupancy_entity="binary_sensor.presence",
        contact_entities=["binary_sensor.window"],
    )
    topology["groups"][0].update(
        mode_entity="sensor.outdoor_mode", max_age_seconds=3600
    )
    hass.states.async_set(
        "sensor.office_temperature", "20", {"unit_of_measurement": "°C"}
    )
    hass.states.async_set("climate.indoor_1", "off")
    hass.states.async_set("sensor.outdoor_mode", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office",
        data={"name": "Office"},
        options=topology,
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass, entry, suffix):
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
    )


async def test_sensors_restart_and_zero_commands(hass, topology, freezer):
    with patch("homeassistant.core.ServiceRegistry.async_call") as service_call:
        entry = await setup_intelligence(hass, topology)
        runtime = entry.runtime_data
        demand_id = entity_id(hass, entry, "zone_office_demand")
        group_id = entity_id(hass, entry, "group_outdoor_1_mode")
        state = hass.states.get(demand_id)
        assert state.state == "heating_demand"
        assert state.attributes["heating_score"] == 1
        assert (
            state.attributes["occupancy"] == "unknown"
        )  # Absent optional sensor never means away.
        assert hass.states.get(group_id).state == "off"
        assert hass.states.get(group_id).attributes["desired_mode"] == "heat"
        assert (
            hass.states.get(group_id).attributes["blocked_reason"]
            == "minimum_switch_interval"
        )
        freezer.move_to(dt_util.utcnow() + timedelta(seconds=900))
        # A fresh same-state report reevaluates the plan after the interval.
        hass.states.async_set("sensor.outdoor_mode", "off")
        await hass.async_block_till_done()
        assert hass.states.get(group_id).state == "heat"
        assert hass.states.get(group_id).attributes["mode_change_proposed"]
        # A proposal does not become an observed switch.
        assert runtime.memories["outdoor_1"].current_mode == "off"
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert runtime._cancel_deadline is None
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(group_id).state == "off"  # Conservative guard restarts.
        hass.states.async_set(
            "sensor.office_temperature", "25", {"unit_of_measurement": "°C"}
        )
        await hass.async_block_till_done()
        assert hass.states.get(demand_id).state == "cooling_demand"
        assert hass.states.get(group_id).attributes["desired_mode"] == "cool"
        service_call.assert_not_called()


async def test_deadlines_and_unchanged_measurement_recovery(hass, topology, freezer):
    # Since 0.3.1 report age only expires with explicit update_based validation.
    entry = await setup_intelligence(
        hass, topology, max_age=20, validation="update_based"
    )
    now = dt_util.utcnow()
    runtime = entry.runtime_data
    after = now + timedelta(seconds=21)
    with patch("homeassistant.util.dt.utcnow", return_value=after):
        async_fire_time_changed(hass, after)
        await hass.async_block_till_done()
    assert runtime.zone_demands["office"].sensor_health == "stale"
    assert runtime.group_decisions["outdoor_1"].blocked_reason == "insufficient_data"
    freezer.move_to(after)
    hass.states.async_set(
        "sensor.office_temperature", "20", {"unit_of_measurement": "°C"}
    )
    await hass.async_block_till_done()
    assert runtime.zone_demands["office"].demand == "heating_demand"
    assert runtime.zone_demands["office"].sensor_health == "valid"
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set(
        "sensor.office_temperature", "25", {"unit_of_measurement": "°C"}
    )
    await hass.async_block_till_done()
    assert (
        runtime.zone_demands["office"].demand == "heating_demand"
    )  # Both report and change listeners removed.


async def test_guard_deadline_reevaluates_without_an_input_event(hass, topology):
    entry = await setup_intelligence(hass, topology)
    after = dt_util.utcnow() + timedelta(seconds=901)
    with patch("homeassistant.util.dt.utcnow", return_value=after):
        async_fire_time_changed(hass, after)
        await hass.async_block_till_done()
    assert entry.runtime_data.group_decisions["outdoor_1"].proposed_mode == "heat"


async def test_full_configuration_and_invalid_limits(hass, topology):
    entry = await setup_intelligence(hass, topology)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "zone"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"record": "office"}
    )
    data = {
        "name": "Renamed office",
        "temperature_entity": "sensor.office_temperature",
        "heating_limit": 24,
        "cooling_limit": 21,
        "weight": 2,
        "hysteresis": 0.3,
        "group_id": "outdoor_1",
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], data)
    assert result["errors"] == {"base": "invalid_limits"}
    data.update(heating_limit=21, cooling_limit=24)
    result = await hass.config_entries.options.async_configure(result["flow_id"], data)
    assert result["type"] == FlowResultType.MENU
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.zone_demands["office"].heating_score == 2
    assert entry.options["zones"][0]["id"] == "office"
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    assert "Renamed office" not in str(diagnostic)
    assert "sensor.outdoor_mode" not in str(diagnostic)
    assert diagnostic["group_decisions"][0]["member_zone_ids"] == "**REDACTED**"


async def test_dynamic_diagnostics_removed_on_topology_delete(hass, topology):
    entry = await setup_intelligence(hass, topology)
    demand_id = entity_id(hass, entry, "zone_office_demand")
    group_id = entity_id(hass, entry, "group_outdoor_1_mode")
    hass.config_entries.async_update_entry(
        entry, options={"zones": [], "groups": [], "equipment": []}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(demand_id) is None
    assert er.async_get(hass).async_get(group_id) is None
    assert hass.states.get(entity_id(hass, entry, "status")).state == "read_only"


async def test_group_options_feedback_and_parameters(hass, topology):
    entry = await setup_intelligence(hass, topology)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "group"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"record": "outdoor_1"}
    )
    assert "mode_entity" in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "name": "Outdoor 1",
            "mode_entity": "sensor.outdoor_mode",
            "min_switch_seconds": 0,
            "min_demand_score": 0.5,
            "score_deadband": 0.5,
            "max_age_seconds": 3600,
        },
    )
    assert result["type"] == FlowResultType.MENU
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.group_decisions["outdoor_1"].proposed_mode == "heat"
    assert entry.options["groups"][0]["id"] == "outdoor_1"
