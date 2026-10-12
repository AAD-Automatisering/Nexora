"""Real setup, source events, unload, reload, diagnostics and no hardware calls."""

from unittest.mock import patch

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nexora.const import DOMAIN
from custom_components.nexora.diagnostics import async_get_config_entry_diagnostics


async def test_lifecycle_read_only(hass, topology):
    hass.states.async_set(
        "sensor.office_temperature", "20", {"unit_of_measurement": "°C"}
    )
    hass.states.async_set("climate.indoor_1", "heat")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office",
        data={"name": "Office"},
        options=topology,
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("homeassistant.core.ServiceRegistry.async_call") as service_call:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        runtime = entry.runtime_data
        assert runtime.status == "read_only"
        registry = er.async_get(hass)
        sensor_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_status"
        )
        assert hass.states.get(sensor_id).state == "read_only"
        hass.states.async_set("climate.indoor_1", "unavailable")
        await hass.async_block_till_done()
        assert hass.states.get(sensor_id).state == "degraded"
        diagnostic = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostic["configuration"]["data"]["name"] == "**REDACTED**"
        assert diagnostic["summary"]["decisions"][0]["equipment_id"] == "**REDACTED**"
        assert "climate.indoor_1" not in str(diagnostic)
        assert await hass.config_entries.async_unload(entry.entry_id)
        hass.states.async_set("climate.indoor_1", "cool")
        await hass.async_block_till_done()
        assert runtime.status == "degraded"  # Listener removed.
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.status == "read_only"
        service_call.assert_not_called()


async def test_missing_sources_do_not_prevent_setup(hass, topology):
    entry = MockConfigEntry(domain=DOMAIN, data={"name": "Office"}, options=topology)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.status == "degraded"
    hass.states.async_set("climate.indoor_1", "off")
    hass.states.async_set("sensor.office_temperature", "21")
    await hass.async_block_till_done()
    assert entry.runtime_data.status == "read_only"


async def test_options_reload_and_floor_protection(hass, topology):
    """Saving UI options replaces listeners and never touches floor setpoints."""
    hass.states.async_set("sensor.office_temperature", "20")
    hass.states.async_set("climate.indoor_1", "heat")
    hass.states.async_set("climate.floor", "heat", {"temperature": 16})
    topology["equipment"].append(
        {
            "id": "floor",
            "name": "Floor",
            "kind": "floor_heating",
            "entity_id": "climate.floor",
            "zone_id": "office",
        }
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office",
        data={"name": "Office"},
        options=topology,
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("homeassistant.core.ServiceRegistry.async_call") as service_call:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        old_runtime = entry.runtime_data
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "zone"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"record": "office"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"id": "office", "name": "Office"}
        )
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
        assert entry.runtime_data is not old_runtime
        assert "sensor.office_temperature" not in entry.runtime_data.observations
        hass.states.async_set("sensor.office_temperature", "unavailable")
        await hass.async_block_till_done()
        assert old_runtime.observations["sensor.office_temperature"].state == "20"
        assert entry.runtime_data.status == "read_only"
        assert hass.states.get("climate.floor").attributes["temperature"] == 16
        service_call.assert_not_called()
