"""Pure indoor unit observation and outdoor-group mode detection.

Three things are kept strictly apart:

* selected mode: the HVAC mode an indoor unit is set to (the HA entity state);
* reported action: the HA ``hvac_action`` attribute, only as good as the
  integration behind it, and never assumed to be physical feedback;
* physical outdoor mode: only the explicitly configured, trusted group
  ``mode_entity`` (see engine.observe_mode). Nothing here ever fills it in.

The derived group mode is an interpretation of indoor units. It is never a
confirmed outdoor unit mode and never releases a mode switch.
"""

import math
from dataclasses import dataclass, replace
from typing import Mapping

from .models import Building, Equipment, EquipmentGroup
from .observations import SourceState

SELECTED_MODES = ("heat", "cool", "heat_cool", "auto", "dry", "fan_only", "off")
# HA HVACAction values grouped by what they say about heat or cool activity.
HEATING_ACTIONS = ("heating", "preheating", "defrosting")
COOLING_ACTIONS = ("cooling",)
DRYING_ACTIONS = ("drying",)
INACTIVE_ACTIONS = ("idle", "off", "fan")
KNOWN_ACTIONS = HEATING_ACTIONS + COOLING_ACTIONS + DRYING_ACTIONS + INACTIVE_ACTIONS


@dataclass(frozen=True)
class IndoorUnitObservation:
    equipment_id: str
    zone_id: str
    group_id: str | None
    availability: str  # available / unavailable / unknown / missing / untrusted
    selected_mode: str  # SELECTED_MODES, unknown (not available) or unsupported
    reported_action: str  # KNOWN_ACTIONS, missing or unsupported
    current_temperature: float | None
    target_temperature: float | None
    temperature_unit: str | None
    fan_mode: str | None
    observed_at: str | None
    quality: str  # complete / no_action / unsupported_mode / unavailable
    mismatch: bool  # selected mode contradicts reported action

    @property
    def available(self) -> bool:
        return self.availability == "available"

    @property
    def activity(self) -> str | None:
        """heating / cooling / drying / inactive, or None when not reported."""
        if self.reported_action in HEATING_ACTIONS:
            return "heating"
        if self.reported_action in COOLING_ACTIONS:
            return "cooling"
        if self.reported_action in DRYING_ACTIONS:
            return "drying"
        if self.reported_action in INACTIVE_ACTIONS:
            return "inactive"
        return None


@dataclass(frozen=True)
class GroupModeObservation:
    group_id: str
    member_units: int
    available_units: int
    usable_modes: int
    usable_actions: int
    selected_modes: tuple[tuple[str, int], ...]  # (mode, count) for available units
    selected_consensus: str  # heat / cool / off / mixed / unknown / none
    reported_activity: str  # heating / cooling / drying / inactive / mixed / unknown
    derived_mode: str  # heat / cool / inactive / mixed / unknown
    modes_agree: bool
    actions_agree: bool
    conflict: bool
    conflicts: tuple[str, ...]
    completeness: str  # complete / partial / none
    quality: str  # consistent / selected_only / partial / conflict / none
    reason: str
    notes: tuple[str, ...]


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def observe_unit(item: Equipment, source: SourceState | None) -> IndoorUnitObservation:
    """Interpret one linked climate entity without guessing missing attributes."""
    climate = source.climate if source else None
    if source is None:
        availability = "missing"
    elif source.state in (None, "unknown", "unavailable"):
        availability = source.state or "unknown"
    elif not source.trustworthy:
        availability = "untrusted"  # restored or assumed state
    else:
        availability = "available"
    if availability != "available":
        selected, action = "unknown", "missing"
    else:
        selected = source.state if source.state in SELECTED_MODES else "unsupported"
        raw = climate.hvac_action if climate else None
        action = (
            "missing" if raw is None else raw if raw in KNOWN_ACTIONS else "unsupported"
        )
    unit = IndoorUnitObservation(
        item.id,
        item.zone_id,
        item.group_id,
        availability,
        selected,
        action,
        _number(climate.current_temperature) if climate else None,
        _number(climate.target_temperature) if climate else None,
        climate.temperature_unit if climate else None,
        climate.fan_mode if climate and climate.fan_mode is not None else None,
        climate.observed_at.isoformat() if climate and climate.observed_at else None,
        "",
        False,
    )
    mismatch = _mismatch(unit.selected_mode, unit.activity)
    quality = (
        "unavailable"
        if availability != "available"
        else "unsupported_mode"
        if selected == "unsupported"
        else "no_action"
        if unit.activity is None
        else "complete"
    )
    return replace(unit, quality=quality, mismatch=mismatch)


def _mismatch(selected: str, activity: str | None) -> bool:
    """A selected mode that cannot produce the reported activity is inconsistent.

    heat + idle is normal (set to heat, currently not heating); off + heating,
    heat + cooling or fan_only + cooling are not.
    """
    if activity not in ("heating", "cooling", "drying"):
        return False
    allowed = {
        "heat": ("heating",),
        "cool": ("cooling",),
        "dry": ("drying", "cooling"),
        "heat_cool": ("heating", "cooling", "drying"),
        "auto": ("heating", "cooling", "drying"),
    }
    return activity not in allowed.get(selected, ())


def group_units(building: Building, group: EquipmentGroup) -> tuple[Equipment, ...]:
    return tuple(
        item
        for item in building.equipment
        if item.kind == "hvac" and item.group_id == group.id
    )


def detect_group_mode(
    group_id: str, units: tuple[IndoorUnitObservation, ...]
) -> GroupModeObservation:
    """Combine selected modes and reported activity conservatively."""
    available = [unit for unit in units if unit.available]
    counts: dict[str, int] = {}
    for unit in available:
        counts[unit.selected_mode] = counts.get(unit.selected_mode, 0) + 1
    selected = set(counts)
    usable_modes = sum(
        count for mode, count in counts.items() if mode in SELECTED_MODES
    )
    activities = {unit.activity for unit in available if unit.activity}
    usable_actions = sum(1 for unit in available if unit.activity)
    conflicts: list[str] = []
    notes: list[str] = []

    if not units:
        return _result(
            group_id,
            units,
            counts,
            "none",
            "unknown",
            "unknown",
            conflicts,
            ["no_indoor_units"],
            "no_indoor_units",
            usable_modes,
            usable_actions,
        )
    if not available:
        return _result(
            group_id,
            units,
            counts,
            "unknown",
            "unknown",
            "unknown",
            conflicts,
            ["no_available_indoor_units"],
            "no_available_indoor_units",
            usable_modes,
            usable_actions,
        )

    # A. Selected mode consensus over available units.
    if {"heat", "cool"} <= selected:
        consensus = "mixed"
        conflicts.append("selected_heat_and_cool")
    elif "heat" in selected:
        consensus = "heat"
    elif "cool" in selected:
        consensus = "cool"
    elif selected & {"auto", "heat_cool", "dry", "unsupported"}:
        consensus = "unknown"
    else:
        consensus = "off"  # Only off and/or fan_only: no heat or cool selected.
    for mode, note in (
        ("auto", "auto_mode_unclassified"),
        ("heat_cool", "auto_mode_unclassified"),
        ("dry", "dry_mode_selected"),
        ("fan_only", "fan_only_selected"),
        ("unsupported", "unsupported_mode_selected"),
    ):
        if mode in selected and note not in notes:
            notes.append(note)

    # B. Reported activity (hvac_action) over available units that report it.
    if {"heating", "cooling"} <= activities:
        activity = "mixed"
        conflicts.append("reported_heating_and_cooling")
    elif "heating" in activities:
        activity = "heating"
    elif "cooling" in activities:
        activity = "cooling"
    elif "drying" in activities:
        activity = "drying"
    elif activities:
        activity = "inactive"
    else:
        activity = "unknown"
    if any(unit.mismatch for unit in available):
        conflicts.append("selected_mode_action_mismatch")
    if usable_actions < len(available):
        notes.append("hvac_action_missing")
    if len(available) < len(units):
        notes.append("indoor_units_unavailable")

    # C. Derived group mode. Conflicts are never resolved by preferring a unit.
    if conflicts:
        derived, reason = "mixed", conflicts[0]
    elif consensus == "heat":
        if activity == "cooling":
            derived, reason = "mixed", "selected_heat_reported_cooling"
            conflicts.append(reason)
        else:
            derived = "heat"
            reason = (
                "heat_selected_heating_reported"
                if activity == "heating"
                else "heat_selected"
            )
    elif consensus == "cool":
        if activity == "heating":
            derived, reason = "mixed", "selected_cool_reported_heating"
            conflicts.append(reason)
        else:
            derived = "cool"
            reason = (
                "cool_selected_cooling_reported"
                if activity == "cooling"
                else "cool_selected"
            )
    elif consensus == "off":
        derived = "inactive"
        reason = "all_units_off" if selected == {"off"} else "no_heat_or_cool_selected"
    elif activity == "heating":
        derived, reason = "heat", "ambiguous_mode_heating_reported"
    elif activity == "cooling":
        derived, reason = "cool", "ambiguous_mode_cooling_reported"
    else:
        derived, reason = "unknown", notes[0] if notes else "mode_unclassified"
    return _result(
        group_id,
        units,
        counts,
        consensus,
        activity,
        derived,
        conflicts,
        notes,
        reason,
        usable_modes,
        usable_actions,
    )


def _result(
    group_id,
    units,
    counts,
    consensus,
    activity,
    derived,
    conflicts,
    notes,
    reason,
    usable_modes,
    usable_actions,
) -> GroupModeObservation:
    available = sum(unit.available for unit in units)
    active_modes = {mode for mode in counts if mode != "off"}
    activities = {
        unit.activity for unit in units if unit.available and unit.activity
    } - {"inactive"}
    completeness = (
        "none"
        if not units or not available
        else "complete"
        if available == len(units) and usable_modes == available
        else "partial"
    )
    quality = (
        "none"
        if completeness == "none"
        else "conflict"
        if conflicts
        else "partial"
        if completeness == "partial"
        else "consistent"
        if usable_actions == available
        else "selected_only"
    )
    return GroupModeObservation(
        group_id,
        len(units),
        available,
        usable_modes,
        usable_actions,
        tuple(sorted(counts.items())),
        consensus,
        activity,
        derived,
        len(active_modes) <= 1,
        len(activities) <= 1,
        bool(conflicts),
        tuple(conflicts),
        completeness,
        quality,
        reason,
        tuple(notes),
    )


def observe_group(
    building: Building, group: EquipmentGroup, sources: Mapping[str, SourceState]
) -> tuple[tuple[IndoorUnitObservation, ...], GroupModeObservation]:
    units = tuple(
        observe_unit(item, sources.get(item.entity_id))
        for item in group_units(building, group)
    )
    return units, detect_group_mode(group.id, units)


def compare_modes(desired: str, observation: GroupModeObservation) -> str:
    """Explain desired (demand) versus derived (indoor units) — diagnosis only."""
    derived = observation.derived_mode
    if observation.member_units == 0:
        return "no_indoor_units"
    if derived == "mixed":
        return "indoor_units_conflict"
    if derived == "unknown":
        return "indoor_observation_unknown"
    if desired == "unknown":
        return "desired_mode_unknown"
    if desired == derived or (desired == "off" and derived == "inactive"):
        return "observed_matches_desired"
    if desired in ("heat", "cool") and derived == "inactive":
        return f"{desired}_requested_units_inactive"
    if desired == "off":
        return "units_active_without_demand"
    return "mode_mismatch_observed"
