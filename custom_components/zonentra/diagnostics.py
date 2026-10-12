"""Privacy-conscious diagnostics, with no raw source states."""

from dataclasses import asdict

from homeassistant.components.diagnostics import async_redact_data

from . import ZonentraConfigEntry
from .models import ZONE_ENTITY_FIELDS
from .observations import describe

SOURCE_FIELDS = (
    "temperature",
    "heating_limit",
    "cooling_limit",
    "humidity",
    "co2",
    "outdoor_temperature",
)


def _source_validation(runtime) -> list[dict]:
    """Per-zone validation explanations without values, entity IDs or names."""
    return [
        {
            "zone_id": zone_id,
            **{
                field: {
                    key: value
                    for key, value in describe(
                        getattr(snapshot, field), runtime.evaluated_at
                    ).items()
                    if key != "value"
                }
                for field in SOURCE_FIELDS
            },
        }
        for zone_id, snapshot in runtime.zone_snapshots.items()
    ]


async def async_get_config_entry_diagnostics(hass, entry: ZonentraConfigEntry) -> dict:
    return async_redact_data(
        {
            "configuration": {"data": dict(entry.data), "options": dict(entry.options)},
            "status": entry.runtime_data.status,
            "summary": {
                key: value
                for key, value in entry.runtime_data.summary().items()
                if key != "outdoor_temperature_c"
            },
            "zone_demands": [
                asdict(item) for item in entry.runtime_data.zone_demands.values()
            ],
            "source_validation": _source_validation(entry.runtime_data),
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
            "outdoor_temperature_entity",
            "outdoor_temperature_candidates",
            "contact_entities",
            "member_zone_ids",
            *ZONE_ENTITY_FIELDS,
        },
    )
