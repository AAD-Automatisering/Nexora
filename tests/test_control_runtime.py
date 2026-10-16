"""0.5.0 integration: simulated control and manual override on real HA events."""

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

UNIT = "climate.open_office_ac"
TEMPERATURE = "sensor.open_office_temperature"
CELSIUS = {"unit_of_measurement": "°C"}
ATTRIBUTES = {"hvac_action": "off", "current_temperature": 23, "temperature": 21}


def topology(**building):
    return {
        "building": {
            "heating_limit": 22,
            "cooling_limit": 24,
            "hysteresis": 0.3,
            **building,
        },
        "zones": [
            {
                "id": "open_office",
                "name": "Open Office",
                "temperature_entity": TEMPERATURE,
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


async def setup_office(hass, options=None, temperature="23"):
    """No climate demand (23 °C between 22 and 24 °C), unit off."""
    hass.states.async_set(TEMPERATURE, temperature, CELSIUS)
    hass.states.async_set(UNIT, "off", ATTRIBUTES)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Building",
        data={"name": "Building"},
        options=options or topology(),
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def control(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_equipment_open_office_ac_control"
    )
    return hass.states.get(entity_id)


def coordination(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_group_outdoor_1_coordination"
    )
    return hass.states.get(entity_id)


async def switch(hass, state, **attributes):
    hass.states.async_set(UNIT, state, {**ATTRIBUTES, **attributes})
    await hass.async_block_till_done()


async def test_manual_override_lifecycle_without_commands(hass, freezer):
    """5, 7, 9, 11, 12 and 31 on real state_changed events and timers."""
    with patch("homeassistant.core.ServiceRegistry.async_call") as service_call:
        entry = await setup_office(hass)
        runtime = entry.runtime_data
        state = control(hass, entry)
        assert state.state == "hold"
        assert state.attributes["simulation"] is True
        assert state.attributes["reason"] == "no_zone_demand"
        start = dt_util.utcnow()
        await switch(hass, "heat", hvac_action="heating")
        state = control(hass, entry)
        assert state.attributes["manual_override_active"] is True
        assert state.attributes["override_remaining_seconds"] == 30 * 60
        assert state.attributes["reason"] == "manual_override_neutral"
        assert runtime.last_transitions["open_office_ac"][0] == "manual_on"
        expires = runtime.overrides["open_office_ac"].expires_at
        assert expires == start + timedelta(minutes=30)
        # Attribute-only updates and same-state reports never extend the timer.
        freezer.move_to(start + timedelta(minutes=10))
        await switch(hass, "heat", hvac_action="idle")
        await switch(hass, "heat", hvac_action="idle")
        assert runtime.last_transitions["open_office_ac"][0] == "attribute_update"
        assert runtime.overrides["open_office_ac"].expires_at == expires
        assert control(hass, entry).attributes["override_remaining_seconds"] == 20 * 60
        # Expiry without any new climate event, via the scheduled deadline.
        with patch("homeassistant.util.dt.utcnow", return_value=expires):
            async_fire_time_changed(hass, expires)
            await hass.async_block_till_done()
        assert "open_office_ac" not in runtime.overrides
        state = control(hass, entry)
        assert state.attributes["manual_override_active"] is False
        assert state.attributes["desired_mode"] == "off"
        assert state.state == "turn_off"
        assert state.attributes["reason"] == "override_expired"
        service_call.assert_not_called()


async def test_manual_off_ends_override_and_new_on_restarts(hass, freezer):
    """6 and 10: off -> cool starts, manual off ends, a new on starts fresh."""
    entry = await setup_office(hass)
    runtime = entry.runtime_data
    await switch(hass, "cool")
    assert "open_office_ac" in runtime.overrides
    freezer.move_to(dt_util.utcnow() + timedelta(minutes=5))
    await switch(hass, "off")
    assert "open_office_ac" not in runtime.overrides
    assert control(hass, entry).attributes["manual_override_active"] is False
    freezer.move_to(dt_util.utcnow() + timedelta(minutes=5))
    await switch(hass, "cool")
    assert runtime.overrides["open_office_ac"].started_at == dt_util.utcnow()


async def test_transitions_that_never_start_an_override(hass):
    """14, 15, 16 and 17 with real HA state changes."""
    entry = await setup_office(hass)
    runtime = entry.runtime_data
    for unavailable, active in (("unknown", "heat"), ("unavailable", "cool")):
        await switch(hass, unavailable)
        await switch(hass, active)
        assert runtime.last_transitions["open_office_ac"][0] == "from_unavailable"
        assert not runtime.overrides
        await switch(hass, "off")
    # A change Zonentra itself initiated (future active control) is excluded.
    runtime.command_tracker.register(UNIT, "heat", dt_util.utcnow())
    await switch(hass, "heat")
    assert runtime.last_transitions["open_office_ac"][0] == "zonentra_initiated"
    assert not runtime.overrides
    await switch(hass, "off")
    # Anything else (e.g. an automation) cannot be told apart: manual override.
    await switch(hass, "heat")
    assert runtime.last_transitions["open_office_ac"][0] == "manual_on"
    assert runtime.overrides


async def test_restart_never_creates_or_restores_an_override(hass):
    """13 and 30: reload/restart drops overrides; no duplicate listeners."""
    entry = await setup_office(hass)
    await switch(hass, "heat")
    assert entry.runtime_data.overrides
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    listeners = hass.bus.async_listeners()
    assert not entry.runtime_data.overrides  # A running unit at startup is no override.
    state = control(hass, entry)
    assert state.attributes["manual_override_active"] is False
    assert state.attributes["desired_mode"] == "off"
    for _ in range(2):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.bus.async_listeners() == listeners


async def test_group_heat_demand_and_manual_cool_is_corrected(hass, freezer):
    """1 and 18 end to end: heat demand leads, a manual cool is corrected."""
    entry = await setup_office(hass, temperature="21")
    state = control(hass, entry)
    # The unit just switched off: the safety minimum off-time applies first.
    assert state.state == "blocked"
    assert state.attributes["blocked_reason"] == "minimum_off_time"
    freezer.move_to(dt_util.utcnow() + timedelta(minutes=10))
    hass.states.async_set(TEMPERATURE, "21", CELSIUS)  # Same-value report.
    await hass.async_block_till_done()
    state = control(hass, entry)
    assert state.state == "turn_on_heat"
    assert state.attributes["desired_mode"] == "heat"
    group = coordination(hass, entry)
    assert group.state == "idle"
    assert group.attributes["group_mode"] == "heat"
    assert group.attributes["active_switch_permitted"] is False
    assert "read_only_simulation" in group.attributes["blockers"]
    assert "current_mode_unknown" in group.attributes["blockers"]
    assert group.attributes["planned_actions"] == {"Open Office AC": "turn_on_heat"}
    await switch(hass, "cool")
    state = control(hass, entry)
    assert state.state == "correct_mode"
    assert state.attributes["desired_mode"] == "heat"
    assert state.attributes["manual_override_active"] is True
    assert coordination(hass, entry).attributes["group_mode"] == "heat"


async def test_disabled_override_and_options_flow(hass):
    """8 and 28: building-wide settings via the central Options Flow."""
    entry = await setup_office(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "building"}
    )
    schema = result["data_schema"].schema
    for key in (
        "manual_override_enabled",
        "manual_override_duration_minutes",
        "min_on_seconds",
        "min_off_seconds",
        "changeover_wait_seconds",
    ):
        assert key in schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "heating_limit": 22,
            "cooling_limit": 24,
            "hysteresis": 0.3,
            "manual_override_enabled": True,
            "manual_override_duration_minutes": 45,
            "min_on_seconds": 300,
            "min_off_seconds": 120,
            "changeover_wait_seconds": 240,
        },
    )
    assert result["type"] == FlowResultType.MENU
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    await hass.async_block_till_done()
    settings = entry.runtime_data.building.settings
    assert settings.manual_override_duration_minutes == 45
    assert (settings.min_on_seconds, settings.min_off_seconds) == (300, 120)
    assert settings.changeover_wait_seconds == 240
    await switch(hass, "heat")
    assert control(hass, entry).attributes["override_remaining_seconds"] == 45 * 60
    await switch(hass, "off")
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "building": {**entry.options["building"], "manual_override_enabled": False},
        },
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await switch(hass, "heat")
    assert not entry.runtime_data.overrides
    assert control(hass, entry).attributes["desired_mode"] == "off"


async def test_existing_04_configuration_uses_defaults(hass):
    """29: a 0.4 entry without control settings keeps working unchanged."""
    options = topology()
    entry = await setup_office(hass, options)
    assert entry.options == {
        **options,
        "zones": [
            {**zone, "use_building_preconditioning": True} for zone in options["zones"]
        ],
    }
    settings = entry.runtime_data.building.settings
    assert settings.manual_override_enabled is True
    assert settings.manual_override_duration_minutes == 30
    assert (settings.min_on_seconds, settings.min_off_seconds) == (600, 180)
    assert settings.changeover_wait_seconds == 300


async def test_unavailable_unit_and_diagnostics(hass):
    """26 and diagnostics: simulation is labelled and identifiers are redacted."""
    entry = await setup_office(hass, temperature="21")
    await switch(hass, "unavailable")
    state = control(hass, entry)
    assert state.state == "blocked"
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    simulation = diagnostic["control_simulation"]
    assert simulation["simulation"] is True
    assert simulation["coordinations"][0]["group_id"] == "**REDACTED**"
    assert simulation["coordinations"][0]["active_switch_permitted"] is False
    assert simulation["unit_intents"][0]["equipment_id"] == "**REDACTED**"
    assert simulation["unit_intents"][0]["action"] == "blocked"
    assert UNIT not in str(diagnostic)
    assert "Open Office" not in str(diagnostic)
