"""Immutable building topology and additive 0.1-compatible configuration."""

import math
import re
from dataclasses import dataclass
from typing import Any

from .const import KINDS

ZONE_ENTITY_FIELDS = (
    "temperature_entity",
    "controller_entity",
    "occupancy_entity",
    "heating_limit_entity",
    "cooling_limit_entity",
    "humidity_entity",
    "co2_entity",
    "outdoor_temperature_entity",
)


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    temperature_entity: str | None = None
    controller_entity: str | None = None
    occupancy_entity: str | None = None
    heating_limit: float | None = None
    cooling_limit: float | None = None
    heating_limit_entity: str | None = None
    cooling_limit_entity: str | None = None
    humidity_entity: str | None = None
    co2_entity: str | None = None
    outdoor_temperature_entity: str | None = None
    contact_entities: tuple[str, ...] = ()
    group_id: str | None = None
    weight: float = 1.0
    hysteresis: float = 0.3
    max_age_seconds: float = 1800.0


@dataclass(frozen=True)
class EquipmentGroup:
    id: str
    name: str
    single_hvac_mode: bool = True
    mode_entity: str | None = None
    min_switch_seconds: float = 900.0
    min_demand_score: float = 0.5
    score_deadband: float = 0.5
    max_age_seconds: float = 1800.0


@dataclass(frozen=True)
class Equipment:
    id: str
    name: str
    kind: str
    entity_id: str
    zone_id: str
    group_id: str | None = None


@dataclass(frozen=True)
class Building:
    id: str
    name: str
    zones: tuple[Zone, ...]
    groups: tuple[EquipmentGroup, ...]
    equipment: tuple[Equipment, ...]

    @property
    def entity_ids(self) -> frozenset[str]:
        """Return configured inputs only, including optional future context."""
        return frozenset(
            [item.entity_id for item in self.equipment]
            + [
                entity
                for zone in self.zones
                for field in ZONE_ENTITY_FIELDS
                if (entity := getattr(zone, field))
            ]
            + [entity for zone in self.zones for entity in zone.contact_entities]
            + [group.mode_entity for group in self.groups if group.mode_entity]
        )


def _records(records: list[dict[str, Any]]) -> None:
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_id")
    for record in records:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", record["id"]):
            raise ValueError("invalid_id")
        if not record["name"].strip():
            raise ValueError("invalid_name")


def _entity(value: str | None, domains: tuple[str, ...] | None = None) -> None:
    if value is None:
        return
    if not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", value):
        raise ValueError("invalid_entity")
    if value.startswith("zonentra.") or (
        domains and value.split(".")[0] not in domains
    ):
        raise ValueError("invalid_entity")


def _range(value, low, high) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError("invalid_parameters")


def build_model(building_id: str, name: str, topology: dict[str, Any]) -> Building:
    """Validate references, parameters and exclusive physical equipment ownership."""
    if not name.strip():
        raise ValueError("invalid_name")
    zones, groups, equipment = (
        topology.get(key, []) for key in ("zones", "groups", "equipment")
    )
    for records in (zones, groups, equipment):
        _records(records)
    zone_models = tuple(
        Zone(**{**item, "contact_entities": tuple(item.get("contact_entities", ()))})
        for item in zones
    )
    group_models = tuple(EquipmentGroup(**item) for item in groups)
    zone_by_id = {zone.id: zone for zone in zone_models}
    group_ids = {group.id for group in group_models}
    for zone in zone_models:
        for field in ZONE_ENTITY_FIELDS:
            domains = (
                ("climate",)
                if field == "controller_entity"
                else ("binary_sensor",)
                if field == "occupancy_entity"
                else ("sensor", "number", "input_number")
                if field.endswith("limit_entity")
                else ("sensor",)
            )
            _entity(getattr(zone, field), domains)
        for entity in zone.contact_entities:
            _entity(entity, ("binary_sensor",))
        if zone.group_id and zone.group_id not in group_ids:
            raise ValueError("invalid_reference")
        _range(zone.weight, 0.1, 10)
        _range(zone.hysteresis, 0.1, 2)
        _range(zone.max_age_seconds, 0, 86400)
        for limit in (zone.heating_limit, zone.cooling_limit):
            if limit is not None:
                _range(limit, 5, 35)
        heat_configured = (
            zone.heating_limit is not None or zone.heating_limit_entity is not None
        )
        cool_configured = (
            zone.cooling_limit is not None or zone.cooling_limit_entity is not None
        )
        if heat_configured != cool_configured:
            raise ValueError("invalid_limits")
        if (
            zone.heating_limit is not None
            and zone.cooling_limit is not None
            and zone.heating_limit + 2 * zone.hysteresis >= zone.cooling_limit
        ):
            raise ValueError("invalid_limits")
    for group in group_models:
        _entity(group.mode_entity, ("sensor", "select", "climate"))
        _range(group.min_switch_seconds, 0, 86400)
        _range(group.min_demand_score, 0.1, 100)
        _range(group.score_deadband, 0.1, 100)
        _range(group.max_age_seconds, 0, 86400)
    physical_entities: set[str] = set()
    domains = {
        "hvac": ("climate",),
        "floor_heating": ("climate", "number"),
        "shading": ("cover",),
        "ventilation": ("fan", "switch"),
    }
    equipment_models = []
    for item in equipment:
        if item["kind"] not in KINDS:
            raise ValueError("invalid_kind")
        if item["zone_id"] not in zone_by_id or (
            item.get("group_id") and item["group_id"] not in group_ids
        ):
            raise ValueError("invalid_reference")
        if item.get("group_id") and item["kind"] != "hvac":
            raise ValueError("invalid_group")
        zone_group = (
            zone_by_id[item["zone_id"]].group_id if item["kind"] == "hvac" else None
        )
        if zone_group and item.get("group_id") and zone_group != item["group_id"]:
            raise ValueError("conflicting_group")
        _entity(item["entity_id"], domains.get(item["kind"]))
        if item["entity_id"] in physical_entities:
            raise ValueError("duplicate_equipment_entity")
        physical_entities.add(item["entity_id"])
        equipment_models.append(
            Equipment(**{**item, "group_id": item.get("group_id") or zone_group})
        )
    return Building(
        building_id, name, zone_models, group_models, tuple(equipment_models)
    )
