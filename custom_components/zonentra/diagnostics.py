"""Privacy-conscious diagnostics, with no raw source states."""

from dataclasses import asdict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntryState

from . import ZonentraConfigEntry, central_entry, entry_type
from .models import ZONE_ENTITY_FIELDS
from .observations import describe
from .topology import EQUIPMENT_FIELDS, ZONE

REDACT = {
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
    *(field for field, _ in EQUIPMENT_FIELDS),
}
# Interpretation only: no temperatures, fan modes or entity IDs leave the instance.
UNIT_FIELDS = (
    "equipment_id",
    "availability",
    "selected_mode",
    "reported_action",
    "quality",
    "mismatch",
)
SOURCE_FIELDS = (
    "temperature",
    "heating_limit",
    "cooling_limit",
    "humidity",
    "co2",
    "outdoor_temperature",
)


def _iso(value):
    return value.isoformat() if value else None


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
    if entry_type(entry) == ZONE:
        return _zone_diagnostics(hass, entry)
    runtime = entry.runtime_data
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
            "group_observations": [
                {
                    **asdict(observation),
                    "desired_mode": runtime.group_decisions[group_id].desired_mode,
                    "physical_mode": runtime.group_decisions[group_id].current_mode,
                    "physical_mode_feedback_available": (
                        runtime.group_decisions[group_id].mode_quality == "valid"
                    ),
                    "observation_reason": runtime.mode_comparisons[group_id],
                    "units": [
                        {
                            key: value
                            for key, value in asdict(unit).items()
                            if key in UNIT_FIELDS
                        }
                        for unit in runtime.indoor_units.values()
                        if unit.group_id == group_id
                    ],
                }
                for group_id, observation in runtime.group_observations.items()
            ],
            "mode_control": {
                "active_capable": runtime.active_capable,
                "groups": [
                    {
                        "group_id": group_id,
                        "active": runtime.mode_active.get(group_id),
                        "status": control.status,
                        "target_mode": control.target_mode,
                        "preset_mode": control.preset_mode,
                        "blocked_until": _iso(control.blocked_until),
                    }
                    for group_id, control in runtime.mode_controls.items()
                ],
                "command_log": list(runtime.command_log),
            },
            "control_simulation": {
                "simulation": True,
                "coordinations": [
                    {
                        **{
                            key: value
                            for key, value in asdict(item).items()
                            if key not in ("planned_actions", "waiting_until")
                        },
                        "waiting_until": _iso(item.waiting_until),
                        "planned_actions": [
                            action for _, action in item.planned_actions
                        ],
                    }
                    for item in runtime.coordinations.values()
                ],
                "unit_intents": [
                    {
                        **{
                            key: value
                            for key, value in asdict(intent).items()
                            if key not in ("blocked_until", "override_expires_at")
                        },
                        "blocked_until": _iso(intent.blocked_until),
                        "override_expires_at": _iso(intent.override_expires_at),
                    }
                    for intent in runtime.unit_intents.values()
                ],
            },
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
        REDACT,
    )


def _zone_diagnostics(hass, entry) -> dict:
    """A zone entry explains its observations, plans and enabled room control."""
    central = central_entry(hass)
    runtime = (
        central.runtime_data
        if central and central.state is ConfigEntryState.LOADED
        else None
    )
    zone_id = entry.options.get("id")
    data = {
        "entry_type": ZONE,
        "configuration": {"options": dict(entry.options)},
        "central_loaded": runtime is not None,
    }
    if runtime and zone_id in runtime.zone_demands:
        data["zone_demand"] = asdict(runtime.zone_demands[zone_id])
        data["unit_intents"] = [
            {
                **{
                    key: value
                    for key, value in asdict(intent).items()
                    if key not in ("blocked_until", "override_expires_at")
                },
                "blocked_until": _iso(intent.blocked_until),
                "override_expires_at": _iso(intent.override_expires_at),
            }
            for intent in runtime.unit_intents.values()
            if intent.zone_id == zone_id
        ]
        # 0.9 room thermostat and what room regulation does per unit.
        data["thermostat"] = runtime.thermostat(zone_id).as_dict()
        data["active_band"] = list(runtime.zone_bands.get(zone_id, ()))
        data["room_regulation"] = {
            item.id: {
                "status": control.status,
                "setpoint": {
                    **asdict(plan),
                    "next_check": _iso(plan.next_check),
                }
                if (plan := runtime.setpoint_plans.get(item.id))
                else None,
            }
            for item in runtime.building.equipment
            if item.zone_id == zone_id
            and (control := runtime.room_controls.get(item.id))
        }
    return async_redact_data(data, REDACT)
