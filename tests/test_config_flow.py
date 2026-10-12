"""Real config/options flow manager tests."""

from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nexora.const import DOMAIN


async def test_user_and_singleton(hass):
    with patch("custom_components.nexora.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "   "}
        )
        assert result["errors"] == {"name": "invalid_name"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": " Office "}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"] == {"name": "Office"}
        assert result["result"].unique_id == DOMAIN
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "single_instance_allowed"


async def start_options(hass, topology=None):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"name": "Office"}, options=topology or {}, unique_id=DOMAIN
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU
    return entry, result


async def edit(hass, result, category, record_id, data):
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": category}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"record": record_id}
    )
    return await hass.config_entries.options.async_configure(result["flow_id"], data)


async def test_create_topology_and_save(hass):
    entry, result = await start_options(hass)
    hass.states.async_set(
        "sensor.office_temperature", "20", {"unit_of_measurement": "°C"}
    )
    hass.states.async_set("climate.indoor_1", "off")
    result = await edit(
        hass,
        result,
        "zone",
        "__new__",
        {
            "id": "office",
            "name": "Office",
            "temperature_entity": "sensor.office_temperature",
        },
    )
    assert result["type"] == FlowResultType.MENU
    assert entry.options == {}  # No partial writes.
    result = await edit(
        hass, result, "group", "__new__", {"id": "outdoor_1", "name": "Outdoor 1"}
    )
    result = await edit(
        hass,
        result,
        "equipment",
        "__new__",
        {
            "id": "indoor_1",
            "name": "Indoor 1",
            "kind": "hvac",
            "entity_id": "climate.indoor_1",
            "zone_id": "office",
            "group_id": "outdoor_1",
        },
    )
    assert result["type"] == FlowResultType.MENU
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert len(entry.options["equipment"]) == 1
    assert entry.options["equipment"][0]["group_id"] == "outdoor_1"


async def test_missing_entity_and_duplicate_id(hass, topology):
    entry, result = await start_options(hass, topology)
    result = await edit(
        hass,
        result,
        "zone",
        "__new__",
        {"id": "new", "name": "New", "temperature_entity": "sensor.does_not_exist"},
    )
    assert result["errors"] == {"base": "entity_not_found"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"id": "office", "name": "Duplicate"}
    )
    assert result["errors"] == {"base": "duplicate_id"}
    assert len(entry.options["zones"]) == 1


async def test_referenced_delete_blocked_and_optional_link_removed(hass, topology):
    entry, result = await start_options(hass, topology)
    result = await edit(
        hass,
        result,
        "zone",
        "office",
        {"id": "office", "name": "Office", "delete": True},
    )
    assert result["errors"] == {"base": "invalid_reference"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"id": "office", "name": "Renamed"}
    )
    assert result["type"] == FlowResultType.MENU
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
    assert entry.options["zones"] == [{"id": "office", "name": "Renamed"}]


async def test_group_edit_delete_and_cancel(hass, topology):
    """Referenced groups cannot be deleted and unsaved edits are discarded."""
    entry, result = await start_options(hass, topology)
    result = await edit(
        hass,
        result,
        "group",
        "outdoor_1",
        {"id": "outdoor_1", "name": "Outdoor 1", "delete": True},
    )
    assert result["errors"] == {"base": "invalid_reference"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"id": "outdoor_1", "name": "Renamed"}
    )
    assert result["type"] == FlowResultType.MENU
    hass.config_entries.options.async_abort(result["flow_id"])
    assert entry.options["groups"][0]["name"] == "Outdoor 1"


async def test_equipment_delete_then_group_delete(hass, topology):
    entry, result = await start_options(hass, topology)
    result = await edit(
        hass,
        result,
        "equipment",
        "indoor_1",
        {**topology["equipment"][0], "delete": True},
    )
    assert result["type"] == FlowResultType.MENU
    result = await edit(
        hass,
        result,
        "group",
        "outdoor_1",
        {"id": "outdoor_1", "name": "Outdoor 1", "delete": True},
    )
    assert result["type"] == FlowResultType.MENU
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
    assert entry.options["equipment"] == []
    assert entry.options["groups"] == []
