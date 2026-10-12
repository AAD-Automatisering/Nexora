"""Deterministic zone snapshots and hysteretic temperature demand."""

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .models import Building, Zone
from .observations import (
    Reading,
    SourceState,
    configured_limit,
    max_age_for,
    read,
)


@dataclass(frozen=True)
class ZoneSnapshot:
    zone_id: str
    temperature: Reading
    heating_limit: Reading
    cooling_limit: Reading
    humidity: Reading
    co2: Reading
    outdoor_temperature: Reading
    occupancy: Reading
    contacts: tuple[Reading, ...]
    hvac_ids: tuple[str, ...]
    floor_heating_ids: tuple[str, ...]
    shading_ids: tuple[str, ...]


@dataclass(frozen=True)
class ZoneDemand:
    zone_id: str
    demand: str
    heating_score: float | None
    cooling_score: float | None
    reason: str
    sensor_health: str


def collect_zone(
    building: Building,
    zone: Zone,
    sources: Mapping[str, SourceState],
    now: datetime,
    outdoor_temperature: Reading | None = None,
) -> ZoneSnapshot:
    # Measurements follow the zone strategy; state_based applies no age limit.
    max_age = max_age_for(zone.sensor_validation, zone.max_age_seconds)

    def numeric(field, kind):
        entity = getattr(zone, field)
        if entity is None:
            return Reading(None, "missing", reason="not_configured")
        return read(sources.get(entity), kind, now, max_age)

    def limits(entity, static):
        # Limit entities are settings (number/input_number) that only change on
        # demand; their age is never evidence of a fault.
        return (
            read(sources.get(entity), "limit", now)
            if entity
            else configured_limit(static)
        )

    def equipment(kind):
        return tuple(
            item.id
            for item in building.equipment
            if item.zone_id == zone.id and item.kind == kind
        )

    return ZoneSnapshot(
        zone.id,
        numeric("temperature_entity", "temperature"),
        limits(zone.heating_limit_entity, zone.heating_limit),
        limits(zone.cooling_limit_entity, zone.cooling_limit),
        numeric("humidity_entity", "humidity"),
        numeric("co2_entity", "co2"),
        outdoor_temperature
        if outdoor_temperature is not None
        else read(
            sources.get(building.settings.outdoor_temperature_entity),
            "temperature",
            now,
            building.settings.outdoor_max_age_seconds,
        ),
        read(sources.get(zone.occupancy_entity), "occupancy", now),
        tuple(
            read(sources.get(entity), "contact", now)
            for entity in zone.contact_entities
        ),
        equipment("hvac"),
        equipment("floor_heating"),
        equipment("shading"),
    )


def calculate_demand(
    zone: Zone, snapshot: ZoneSnapshot, previous: str = "unknown"
) -> ZoneDemand:
    """A configured missing/stale/invalid required input produces unknown, not zero."""
    required = (snapshot.temperature, snapshot.heating_limit, snapshot.cooling_limit)
    bad = next((reading for reading in required if reading.quality != "valid"), None)
    if bad:
        return ZoneDemand(
            zone.id, "unknown", None, None, "insufficient_data", bad.quality
        )
    temperature = snapshot.temperature.value
    heat, cool, hysteresis = (
        snapshot.heating_limit.value,
        snapshot.cooling_limit.value,
        zone.hysteresis,
    )
    if heat + 2 * hysteresis >= cool:
        return ZoneDemand(
            zone.id, "unknown", None, None, "invalid_limits", "unreliable"
        )
    if previous == "heating_demand" and temperature < heat + hysteresis:
        demand, reason = "heating_demand", "heating_hysteresis"
    elif previous == "cooling_demand" and temperature > cool - hysteresis:
        demand, reason = "cooling_demand", "cooling_hysteresis"
    elif temperature < heat - hysteresis:
        demand, reason = "heating_demand", "below_heating_limit"
    elif temperature > cool + hysteresis:
        demand, reason = "cooling_demand", "above_cooling_limit"
    else:
        demand, reason = "neutral", "within_comfort_band"
    # Saturate each zone's contribution at 5 K before weighting.
    heating_score = (
        zone.weight * min(5, max(0, heat - temperature))
        if demand == "heating_demand"
        else 0.0
    )
    cooling_score = (
        zone.weight * min(5, max(0, temperature - cool))
        if demand == "cooling_demand"
        else 0.0
    )
    return ZoneDemand(
        zone.id,
        demand,
        round(heating_score, 4),
        round(cooling_score, 4),
        reason,
        "valid",
    )
