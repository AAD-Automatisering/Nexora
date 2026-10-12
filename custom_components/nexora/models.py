"""Immutable building topology; independent of Home Assistant."""

import re
from dataclasses import dataclass
from typing import Any

from .const import KINDS


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    temperature_entity: str | None = None
    controller_entity: str | None = None
    occupancy_entity: str | None = None


@dataclass(frozen=True)
class EquipmentGroup:
    id: str
    name: str
    single_hvac_mode: bool = True


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
        """Return only configured inputs, never Nexora's diagnostic outputs."""
        return frozenset(
            [item.entity_id for item in self.equipment]
            + [
                entity
                for zone in self.zones
                for entity in (
                    zone.temperature_entity,
                    zone.controller_entity,
                    zone.occupancy_entity,
                )
                if entity
            ]
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
    if value.startswith("nexora.") or (domains and value.split(".")[0] not in domains):
        raise ValueError("invalid_entity")


def build_model(building_id: str, name: str, topology: dict[str, Any]) -> Building:
    """Validate references and exclusive physical equipment ownership."""
    if not name.strip():
        raise ValueError("invalid_name")
    zones, groups, equipment = (
        topology.get(key, []) for key in ("zones", "groups", "equipment")
    )
    for records in (zones, groups, equipment):
        _records(records)
    zone_ids = {record["id"] for record in zones}
    group_ids = {record["id"] for record in groups}
    for zone in zones:
        _entity(zone.get("temperature_entity"), ("sensor",))
        _entity(zone.get("controller_entity"), ("climate",))
        _entity(zone.get("occupancy_entity"), ("binary_sensor",))
    physical_entities: set[str] = set()
    domains = {
        "hvac": ("climate",),
        "floor_heating": ("climate", "number"),
        "shading": ("cover",),
        "ventilation": ("fan", "switch"),
    }
    for item in equipment:
        if item["kind"] not in KINDS:
            raise ValueError("invalid_kind")
        if item["zone_id"] not in zone_ids or (
            item.get("group_id") and item["group_id"] not in group_ids
        ):
            raise ValueError("invalid_reference")
        if item.get("group_id") and item["kind"] != "hvac":
            raise ValueError("invalid_group")
        _entity(item["entity_id"], domains.get(item["kind"]))
        if item["entity_id"] in physical_entities:
            raise ValueError("duplicate_equipment_entity")
        physical_entities.add(item["entity_id"])
    return Building(
        building_id,
        name,
        tuple(Zone(**item) for item in zones),
        tuple(EquipmentGroup(**item) for item in groups),
        tuple(Equipment(**item) for item in equipment),
    )
