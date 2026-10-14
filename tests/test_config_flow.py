"""Real config/options flow manager tests."""

from unittest.mock import patch
from uuid import UUID

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zonentra.const import DOMAIN


async def test_user_and_singleton(hass):
    """0.6: the first step chooses the type; the central configuration is unique."""
    with patch("custom_components.zonentra.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == FlowResultType.MENU
        assert result["menu_options"] == ["central", "zone"]
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "central"}
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
        assert result["data"] == {"entry_type": "central", "name": "Office"}
        assert result["result"].unique_id == "central"
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "central"}
        )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "central_already_configured"


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
        {"name": "Office", "temperature_entity": "sensor.office_temperature"},
    )
    assert result["type"] == FlowResultType.MENU
    assert entry.options == {}  # No partial writes.
    result = await edit(hass, result, "group", "__new__", {"name": "Outdoor 1"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "equipment"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"record": "__new__"}
    )
    assert "id" not in result["data_schema"].schema
    # Read the IDs from UI choices, just as the frontend submits them.
    zone_id = result["data_schema"].schema["zone_id"].config["options"][0]["value"]
    group_id = result["data_schema"].schema["group_id"].config["options"][1]["value"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "name": "Indoor 1",
            "kind": "hvac",
            "entity_id": "climate.indoor_1",
            "zone_id": zone_id,
            "group_id": group_id,
        },
    )
    assert result["type"] == FlowResultType.MENU
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert (
        entry.options["equipment"][0]["zone_id"]
        == entry.options["zones"][0]["id"]
        == zone_id
    )
    assert (
        entry.options["equipment"][0]["group_id"]
        == entry.options["groups"][0]["id"]
        == group_id
    )
    ids = [entry.options[key][0]["id"] for key in ("zones", "groups", "equipment")]
    assert len(set(ids)) == 3
    assert all(UUID(value).version == 4 for value in ids)


async def test_missing_entity_retry_keeps_generated_id(hass, topology):
    entry, result = await start_options(hass, topology)
    with patch(
        "custom_components.zonentra.config_flow.uuid4", return_value=UUID("f" * 32)
    ) as generate_id:
        result = await edit(
            hass,
            result,
            "zone",
            "__new__",
            {"name": "New", "temperature_entity": "sensor.does_not_exist"},
        )
        assert result["errors"] == {"base": "entity_not_found"}
        assert "id" not in result["data_schema"].schema
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"name": "Office"}
        )
        assert result["type"] == FlowResultType.MENU
        generate_id.assert_called_once()
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
    assert [zone["id"] for zone in entry.options["zones"]] == ["office", "f" * 32]
    assert [zone["name"] for zone in entry.options["zones"]] == ["Office", "Office"]


async def test_referenced_delete_blocked_and_optional_link_removed(hass, topology):
    entry, result = await start_options(hass, topology)
    result = await edit(
        hass,
        result,
        "zone",
        "office",
        {"name": "Office", "delete": True},
    )
    assert result["errors"] == {"base": "invalid_reference"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Renamed"}
    )
    assert result["type"] == FlowResultType.MENU
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
    assert entry.options["zones"] == [
        {
            "id": "office",
            "name": "Renamed",
            "use_building_limits": True,
            "use_building_parameters": True,
        }
    ]


async def test_group_edit_delete_and_cancel(hass, topology):
    """Referenced groups cannot be deleted and unsaved edits are discarded."""
    entry, result = await start_options(hass, topology)
    result = await edit(
        hass,
        result,
        "group",
        "outdoor_1",
        {"name": "Outdoor 1", "delete": True},
    )
    assert result["errors"] == {"base": "invalid_reference"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Renamed"}
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
        {
            **{
                key: value
                for key, value in topology["equipment"][0].items()
                if key != "id"
            },
            "delete": True,
        },
    )
    assert result["type"] == FlowResultType.MENU
    result = await edit(
        hass,
        result,
        "group",
        "outdoor_1",
        {"name": "Outdoor 1", "delete": True},
    )
    assert result["type"] == FlowResultType.MENU
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
    assert entry.options["equipment"] == []
    assert entry.options["groups"] == []


async def test_rename_preserves_existing_ids_and_links(hass, topology):
    """Rename every record through the UI without rewriting legacy references."""
    entry, result = await start_options(hass, topology)
    for category, record_id in (
        ("zone", "office"),
        ("group", "outdoor_1"),
        ("equipment", "indoor_1"),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": category}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"record": record_id}
        )
        assert "id" not in result["data_schema"].schema
        data = {"name": f"Renamed {category}"}
        if category == "equipment":
            data.update(
                kind="hvac",
                entity_id="climate.indoor_1",
                zone_id="office",
                group_id="outdoor_1",
            )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], data
        )
        assert result["type"] == FlowResultType.MENU
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
    assert entry.options["zones"][0]["id"] == "office"
    assert entry.options["groups"][0]["id"] == "outdoor_1"
    assert entry.options["equipment"][0] == dict(
        topology["equipment"][0], name="Renamed equipment"
    )
