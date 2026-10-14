"""Immutable building topology and additive 0.1-compatible configuration."""

import math
import re
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import Any

from .const import KINDS
from .migration import LIMIT_FIELDS, PARAMETER_FIELDS, migrate_options
from .observations import STATE_BASED, UPDATE_BASED, VALIDATION_STRATEGIES
from .presence import PRESENCE_DOMAINS

ZONE_ENTITY_FIELDS = (
    "temperature_entity",
    "occupancy_entity",
    "heating_limit_entity",
    "cooling_limit_entity",
    "humidity_entity",
    "co2_entity",
    "vane_entity",
)
VANE_DOMAINS = (
    "select",
    "input_select",
    "number",
    "input_number",
    "switch",
    "input_boolean",
)


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    temperature_entity: str | None = None
    occupancy_entity: str | None = None
    heating_limit: float | None = None
    cooling_limit: float | None = None
    heating_limit_entity: str | None = None
    cooling_limit_entity: str | None = None
    humidity_entity: str | None = None
    co2_entity: str | None = None
    contact_entities: tuple[str, ...] = ()
    group_id: str | None = None
    weight: float = 1.0
    hysteresis: float = 0.3
    # Only enforced with update_based; state_based never ages out a valid value.
    max_age_seconds: float = 1800.0
    sensor_validation: str = STATE_BASED
    use_building_limits: bool = False
    use_building_parameters: bool = False
    # 0.10 vane: position for cooling (up) and heating (down) of the room's
    # indoor units, set through a separate entity (select or number).
    vane_entity: str | None = None
    vane_cool_value: str | None = None
    vane_heat_value: str | None = None


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
class BuildingSettings:
    outdoor_temperature_entity: str | None = None
    outdoor_max_age_seconds: float = 1800.0
    heating_limit: float | None = None
    cooling_limit: float | None = None
    heating_limit_entity: str | None = None
    cooling_limit_entity: str | None = None
    hysteresis: float = 0.3
    max_age_seconds: float = 1800.0
    sensor_validation: str = STATE_BASED
    outdoor_temperature_candidates: tuple[str, ...] = ()
    # 0.5 simulated control. Building-wide now; per-zone overrides could later
    # be resolved like effective_zone() without changing these names.
    manual_override_enabled: bool = True
    manual_override_duration_minutes: float = 30.0
    min_on_seconds: float = 600.0  # comfort: avoid short runs
    min_off_seconds: float = 180.0  # safety: restart protection (verify per make)
    changeover_wait_seconds: float = 300.0  # safety: stop -> other mode delay
    # 0.8 presence and motion (like Versatile Thermostat).
    presence_entity: str | None = None
    eco_heating_limit: float = 19.0
    eco_cooling_limit: float = 26.0
    away_heating_limit: float = 16.0
    away_cooling_limit: float = 30.0
    motion_delay_seconds: float = 30.0
    motion_off_delay_minutes: float = 30.0
    # 0.9 room regulation: self-regulating setpoint of running indoor units.
    setpoint_max_offset: float = 2.0
    setpoint_interval_seconds: float = 300.0
    # 0.10 open window: the room stops after this delay (like VTherm).
    window_delay_seconds: float = 30.0


def effective_zone(zone: Zone, settings: BuildingSettings) -> Zone:
    values = {}
    if zone.use_building_limits:
        values.update({key: getattr(settings, key) for key in LIMIT_FIELDS})
    if zone.use_building_parameters:
        values.update({key: getattr(settings, key) for key in PARAMETER_FIELDS})
    return replace(zone, **values)


@dataclass(frozen=True)
class Building:
    id: str
    name: str
    zones: tuple[Zone, ...]
    groups: tuple[EquipmentGroup, ...]
    equipment: tuple[Equipment, ...]
    settings: BuildingSettings = dataclass_field(default_factory=BuildingSettings)

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
            + [
                entity
                for key in (
                    "outdoor_temperature_entity",
                    "heating_limit_entity",
                    "cooling_limit_entity",
                    "presence_entity",
                )
                if (entity := getattr(self.settings, key))
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
    topology = migrate_options(topology)
    settings_data = topology.get("building", {})
    settings = BuildingSettings(
        **{
            **settings_data,
            "outdoor_temperature_candidates": tuple(
                settings_data.get("outdoor_temperature_candidates", ())
            ),
        }
    )
    _entity(settings.outdoor_temperature_entity, ("sensor",))
    for key in ("heating_limit_entity", "cooling_limit_entity"):
        _entity(getattr(settings, key), ("sensor", "number", "input_number"))
    _range(settings.hysteresis, 0.1, 2)
    _range(settings.max_age_seconds, 0, 86400)
    _range(settings.outdoor_max_age_seconds, 0, 86400)
    if not isinstance(settings.manual_override_enabled, bool):
        raise ValueError("invalid_parameters")
    _range(settings.manual_override_duration_minutes, 5, 120)
    for key in ("min_on_seconds", "min_off_seconds", "changeover_wait_seconds"):
        _range(getattr(settings, key), 0, 3600)
    _entity(settings.presence_entity, PRESENCE_DOMAINS)
    for band in ("eco", "away"):
        heat = getattr(settings, f"{band}_heating_limit")
        cool = getattr(settings, f"{band}_cooling_limit")
        _range(heat, 5, 35)
        _range(cool, 5, 35)
        if heat + 2 * settings.hysteresis >= cool:
            raise ValueError("invalid_limits")
    _range(settings.motion_delay_seconds, 0, 600)
    _range(settings.motion_off_delay_minutes, 1, 240)
    _range(settings.setpoint_max_offset, 0, 5)
    _range(settings.setpoint_interval_seconds, 60, 3600)
    _range(settings.window_delay_seconds, 0, 3600)
    _validate_sensor_validation(settings)
    _validate_limits(settings)
    zones, groups, equipment = (
        topology.get(key, []) for key in ("zones", "groups", "equipment")
    )
    for records in (zones, groups, equipment):
        _records(records)
    zone_models = tuple(
        Zone(**{**item, "contact_entities": tuple(item.get("contact_entities", ()))})
        for item in zones
    )
    for zone in zone_models:
        if not isinstance(zone.use_building_limits, bool) or not isinstance(
            zone.use_building_parameters, bool
        ):
            raise ValueError("invalid_parameters")
    zone_models = tuple(effective_zone(zone, settings) for zone in zone_models)
    group_models = tuple(EquipmentGroup(**item) for item in groups)
    zone_by_id = {zone.id: zone for zone in zone_models}
    group_ids = {group.id for group in group_models}
    for zone in zone_models:
        for field in ZONE_ENTITY_FIELDS:
            domains = (
                VANE_DOMAINS
                if field == "vane_entity"
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
        _validate_sensor_validation(zone)
        _validate_limits(zone)
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
        building_id, name, zone_models, group_models, tuple(equipment_models), settings
    )


def _validate_sensor_validation(config) -> None:
    if config.sensor_validation not in VALIDATION_STRATEGIES:
        raise ValueError("invalid_parameters")
    if config.sensor_validation == UPDATE_BASED and not config.max_age_seconds:
        raise ValueError("invalid_parameters")  # update_based needs a maximum age


def _validate_limits(config) -> None:
    for limit in (config.heating_limit, config.cooling_limit):
        if limit is not None:
            _range(limit, 5, 35)
    heat = config.heating_limit is not None or config.heating_limit_entity is not None
    cool = config.cooling_limit is not None or config.cooling_limit_entity is not None
    if heat != cool:
        raise ValueError("invalid_limits")
    if (
        config.heating_limit is not None
        and config.cooling_limit is not None
        and config.heating_limit + 2 * config.hysteresis >= config.cooling_limit
    ):
        raise ValueError("invalid_limits")
