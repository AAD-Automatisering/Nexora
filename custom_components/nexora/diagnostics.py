"""Privacy-conscious diagnostics, with no raw source states."""

from homeassistant.components.diagnostics import async_redact_data

from . import NexoraConfigEntry


async def async_get_config_entry_diagnostics(hass, entry: NexoraConfigEntry) -> dict:
    return async_redact_data(
        {
            "configuration": {"data": dict(entry.data), "options": dict(entry.options)},
            "status": entry.runtime_data.status,
            "summary": entry.runtime_data.summary(),
        },
        {
            "name",
            "id",
            "entity_id",
            "zone_id",
            "group_id",
            "equipment_id",
            "temperature_entity",
            "controller_entity",
            "occupancy_entity",
        },
    )
