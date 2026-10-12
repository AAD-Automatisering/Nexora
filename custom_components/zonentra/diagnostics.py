"""Privacy-conscious diagnostics, with no raw source states."""

from dataclasses import asdict

from homeassistant.components.diagnostics import async_redact_data

from . import ZonentraConfigEntry
from .models import ZONE_ENTITY_FIELDS


async def async_get_config_entry_diagnostics(hass, entry: ZonentraConfigEntry) -> dict:
    return async_redact_data(
        {
            "configuration": {"data": dict(entry.data), "options": dict(entry.options)},
            "status": entry.runtime_data.status,
            "summary": entry.runtime_data.summary(),
            "zone_demands": [
                asdict(item) for item in entry.runtime_data.zone_demands.values()
            ],
            "group_decisions": [
                {
                    **asdict(item),
                    "blocked_until": item.blocked_until.isoformat()
                    if item.blocked_until
                    else None,
                }
                for item in entry.runtime_data.group_decisions.values()
            ],
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
            "mode_entity",
            "contact_entities",
            "member_zone_ids",
            *ZONE_ENTITY_FIELDS,
        },
    )
