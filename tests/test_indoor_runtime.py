"""0.4.0 integration: indoor unit observation with real HA states and flows."""

from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zonentra.const import DOMAIN
from custom_components.zonentra.diagnostics import async_get_config_entry_diagnostics

UNIT = "climate.open_office_ac"
OFF = {
    "hvac_action": "off",
    "current_temperature": 21,
    "temperature": 26,
    "fan_mode": "50%",
    "hvac_modes": ["auto", "cool", "dry", "fan_only", "heat", "off"],
}


def office_topology():
    return {
        "building": {"heating_limit": 22, "cooling_limit": 24, "hysteresis": 0.3},
        "zones": [
            {
                "id": "open_office",
                "name": "Open Office",
                "temperature_entity": "sensor.open_office_temperature",
                "group_id": "outdoor_1",
                "use_building_limits": True,
                "use_building_parameters": True,
            }
        ],
        "groups": [{"id": "outdoor_1", "name": "Outdoor 1"}],
        "equipment": [
            {
                "id": "open_office_ac",
                "name": "Open Office AC",
                "kind": "hvac",
                "entity_id": UNIT,
                "zone_id": "open_office",
            }
        ],
    }


async def setup_office(hass, topology=None):
    hass.states.async_set(
        "sensor.open_office_temperature", "21", {"unit_of_measurement": "°C"}
    )
    hass.states.async_set(UNIT, "off", OFF)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Building",
        data={"name": "Building"},
        options=topology or office_topology(),
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass, entry, suffix):
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
    )


def states(hass, entry, unit_id="open_office_ac"):
    unit = hass.states.get(entity_id(hass, entry, f"equipment_{unit_id}_indoor_unit"))
    derived = hass.states.get(entity_id(hass, entry, "group_outdoor_1_derived_mode"))
    group = hass.states.get(entity_id(hass, entry, "group_outdoor_1_mode"))
    return unit, derived, group


def assert_guard_kept(group):
    """Indoor observations never replace trusted physical mode feedback."""
    assert group.state == "unknown"
    assert group.attributes["desired_mode"] == "heat"
    assert group.attributes["current_mode"] == "unknown"
    assert group.attributes["physical_mode"] == "unknown"
    assert group.attributes["physical_mode_feedback_available"] is False
    assert group.attributes["blocked_reason"] == "current_mode_unknown"
    assert group.attributes["mode_change_proposed"] is False


async def test_practical_case_and_dynamic_updates_without_commands(hass):
    """Scenarios 1, 2, 4, 5, 18, 23, 24, 25 on real HA state changes."""
    with patch("homeassistant.core.ServiceRegistry.async_call") as service_call:
        entry = await setup_office(hass)
        unit, derived, group = states(hass, entry)
        assert unit.state == "off"
        assert unit.attributes["indoor_unit_entity"] == UNIT
        assert unit.attributes["selected_mode"] == "off"
        assert unit.attributes["reported_action"] == "off"
        assert unit.attributes["current_temperature"] == 21
        assert unit.attributes["target_temperature"] == 26
        assert unit.attributes["fan_mode"] == "50%"
        assert unit.attributes["availability"] == "available"
        assert unit.attributes["observation_quality"] == "complete"
        assert derived.state == "inactive"
        assert derived.attributes["derived_from"] == "indoor_units"
        assert derived.attributes["reason"] == "all_units_off"
        assert derived.attributes["member_indoor_units"] == 1
        assert derived.attributes["available_indoor_units"] == 1
        assert derived.attributes["conflict_detected"] is False
        assert derived.attributes["observation_reason"] == (
            "heat_requested_units_inactive"
        )
        assert derived.attributes["physical_mode_feedback_available"] is False
        assert group.attributes["derived_group_mode"] == "inactive"
        assert group.attributes["heating_score"] == 1
        assert group.attributes["reliable_zones"] == 1
        assert_guard_kept(group)
        # Selected heat, not actively heating: normal, not a conflict.
        hass.states.async_set(UNIT, "heat", {**OFF, "hvac_action": "idle"})
        await hass.async_block_till_done()
        unit, derived, group = states(hass, entry)
        assert unit.state == "heat"
        assert unit.attributes["reported_action"] == "idle"
        assert derived.state == "heat"
        assert derived.attributes["reported_activity"] == "inactive"
        assert derived.attributes["observation_reason"] == "observed_matches_desired"
        assert_guard_kept(group)
        # An attribute-only change (hvac_action) is picked up via the same event.
        hass.states.async_set(UNIT, "heat", {**OFF, "hvac_action": "heating"})
        await hass.async_block_till_done()
        unit, derived, group = states(hass, entry)
        assert unit.attributes["reported_action"] == "heating"
        assert derived.attributes["reason"] == "heat_selected_heating_reported"
        assert derived.attributes["quality"] == "consistent"
        assert group.attributes["heating_score"] == 1  # Demand is unchanged.
        assert_guard_kept(group)
        service_call.assert_not_called()


async def test_conflicts_partial_groups_and_missing_action(hass):
    """Scenarios 9, 11, 12, 14, 17 with two indoor units in one group."""
    topology = office_topology()
    topology["equipment"].append(
        {
            "id": "second_ac",
            "name": "Second AC",
            "kind": "hvac",
            "entity_id": "climate.second_ac",
            "zone_id": "open_office",
        }
    )
    hass.states.async_set("climate.second_ac", "cool", {**OFF, "hvac_action": "idle"})
    entry = await setup_office(hass, topology)
    hass.states.async_set(UNIT, "heat", {**OFF, "hvac_action": "idle"})
    await hass.async_block_till_done()
    _, derived, group = states(hass, entry)
    assert derived.state == "mixed"
    assert derived.attributes["conflicts"] == ["selected_heat_and_cool"]
    assert derived.attributes["selected_modes"] == {"cool": 1, "heat": 1}
    assert group.attributes["observation_reason"] == "indoor_units_conflict"
    hass.states.async_set("climate.second_ac", "unavailable")
    await hass.async_block_till_done()
    _, derived, _ = states(hass, entry)
    assert derived.state == "heat"
    assert derived.attributes["available_indoor_units"] == 1
    assert derived.attributes["completeness"] == "partial"
    second, _, _ = states(hass, entry, "second_ac")
    assert second.state == "unknown"
    assert second.attributes["availability"] == "unavailable"
    hass.states.async_set("climate.second_ac", "heat", {"current_temperature": 21})
    await hass.async_block_till_done()
    second, derived, _ = states(hass, entry, "second_ac")
    assert second.attributes["reported_action"] == "missing"
    assert derived.attributes["quality"] == "selected_only"
    hass.states.async_set("climate.second_ac", "heat", {"hvac_action": "cooling"})
    await hass.async_block_till_done()
    second, derived, _ = states(hass, entry, "second_ac")
    assert second.attributes["selected_action_mismatch"] is True
    assert "selected_mode_action_mismatch" in derived.attributes["conflicts"]


async def test_restart_reload_and_no_duplicate_listeners(hass):
    """Scenarios 19 and 22."""
    entry = await setup_office(hass)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    listeners = hass.bus.async_listeners()
    for _ in range(2):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.bus.async_listeners() == listeners
    assert await hass.config_entries.async_unload(entry.entry_id)
    # During startup HA can expose a restored placeholder before the source loads.
    hass.states.async_set(UNIT, "unavailable", {"restored": True})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    unit, derived, group = states(hass, entry)
    assert unit.state == "unknown"
    assert derived.state == "unknown"
    assert derived.attributes["reason"] == "no_available_indoor_units"
    assert group.attributes["blocked_reason"] == "insufficient_data"
    hass.states.async_set(UNIT, "heat", {**OFF, "hvac_action": "heating"})
    await hass.async_block_till_done()
    unit, derived, group = states(hass, entry)
    assert unit.state == "heat"
    assert derived.state == "heat"
    assert_guard_kept(group)


async def test_existing_configuration_is_used_without_reconfiguration(hass, topology):
    """Scenario 20: a 0.1 entry with HVAC equipment gets indoor diagnostics."""
    original = {**topology, "equipment": [dict(topology["equipment"][0])]}
    hass.states.async_set("climate.indoor_1", "cool", {"hvac_action": "cooling"})
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
    assert entry.version == 3
    assert entry.options["equipment"] == original["equipment"]
    unit = hass.states.get(entity_id(hass, entry, "equipment_indoor_1_indoor_unit"))
    assert unit.state == "cool"
    derived = hass.states.get(entity_id(hass, entry, "group_outdoor_1_derived_mode"))
    assert derived.state == "cool"


async def test_removed_and_relinked_climate_entity(hass):
    """Scenario 21: entity removed from HA, relinked and unlinked via Options."""
    entry = await setup_office(hass)
    hass.states.async_remove(UNIT)
    await hass.async_block_till_done()
    unit, derived, _ = states(hass, entry)
    assert unit.attributes["availability"] == "missing"
    assert derived.attributes["reason"] == "no_available_indoor_units"
    hass.states.async_set("climate.replacement_ac", "heat", {"hvac_action": "idle"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "equipment"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"record": "open_office_ac"}
    )
    data = {
        "name": "Open Office AC",
        "kind": "hvac",
        "entity_id": "climate.replacement_ac",
        "zone_id": "open_office",
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], data)
    assert result["type"] == FlowResultType.MENU
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    await hass.async_block_till_done()
    unit, derived, _ = states(hass, entry)
    assert unit.attributes["indoor_unit_entity"] == "climate.replacement_ac"
    assert unit.state == "heat"
    assert derived.state == "heat"
    unit_entity = entity_id(hass, entry, "equipment_open_office_ac_indoor_unit")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "equipment"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"record": "open_office_ac"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**data, "entity_id": "climate.replacement_ac", "delete": True},
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(unit_entity) is None
    derived = hass.states.get(entity_id(hass, entry, "group_outdoor_1_derived_mode"))
    assert derived.state == "unknown"
    assert derived.attributes["reason"] == "no_indoor_units"


async def test_same_indoor_unit_cannot_be_linked_twice(hass):
    """Configuration requirement 8: one indoor unit belongs to one zone."""
    topology = office_topology()
    topology["zones"].append({"id": "meeting", "name": "Meeting"})
    entry = await setup_office(hass, topology)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "equipment"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"record": "__new__"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Duplicate", "kind": "hvac", "entity_id": UNIT, "zone_id": "meeting"},
    )
    assert result["errors"] == {"base": "duplicate_equipment_entity"}


async def test_diagnostics_explain_groups_without_leaking_sources(hass):
    entry = await setup_office(hass)
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    observation = diagnostic["group_observations"][0]
    assert observation["group_id"] == "**REDACTED**"
    assert observation["derived_mode"] == "inactive"
    assert observation["desired_mode"] == "heat"
    assert observation["physical_mode"] == "unknown"
    assert observation["physical_mode_feedback_available"] is False
    assert observation["observation_reason"] == "heat_requested_units_inactive"
    assert observation["units"][0]["equipment_id"] == "**REDACTED**"
    assert observation["units"][0]["selected_mode"] == "off"
    assert UNIT not in str(diagnostic)
    assert "Open Office" not in str(diagnostic)
    assert "current_temperature" not in str(diagnostic)
