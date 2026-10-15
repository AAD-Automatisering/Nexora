"""Pure weighted climate arbitration producing diagnostic group proposals."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

from .demand import ZoneDemand
from .models import Building, EquipmentGroup
from .observations import Reading, SourceState, read


@dataclass(frozen=True)
class GroupMemory:
    current_mode: str
    changed_at: datetime


@dataclass(frozen=True)
class GroupDecision:
    group_id: str
    current_mode: str
    desired_mode: str
    proposed_mode: str
    heating_score: float
    cooling_score: float
    reason: str
    blocked_reason: str | None
    mode_change_proposed: bool
    blocked_until: datetime | None
    member_zone_ids: tuple[str, ...]
    reliable_zones: int
    mode_quality: str


def observe_mode(
    group: EquipmentGroup, sources: Mapping[str, SourceState], now: datetime
) -> Reading:
    """An explicitly configured mode feedback source is required; never infer off."""
    return read(sources.get(group.mode_entity), "mode", now, group.max_age_seconds)


def decide_group(
    building: Building,
    group: EquipmentGroup,
    demands: Mapping[str, ZoneDemand],
    sources: Mapping[str, SourceState],
    memory: GroupMemory,
    now: datetime,
) -> GroupDecision:
    members = tuple(
        item
        for item in building.equipment
        if item.kind == "hvac" and item.group_id == group.id
    )
    # A zone with multiple indoor units contributes exactly once.
    zone_ids = tuple(sorted({item.zone_id for item in members}))
    known = [
        demands[zone_id]
        for zone_id in zone_ids
        if zone_id in demands and demands[zone_id].demand != "unknown"
    ]
    heating = round(sum(item.heating_score for item in known), 4)
    cooling = round(sum(item.cooling_score for item in known), 4)
    mode = observe_mode(group, sources, now)
    current = mode.value if mode.quality == "valid" else "unknown"
    desired, reason, blocked, deadline = "unknown", "insufficient_data", None, None
    equipment_available = all(
        item.entity_id in sources
        and sources[item.entity_id].trustworthy
        and sources[item.entity_id].state not in (None, "unknown", "unavailable")
        for item in members
    )
    reported_modes = {
        sources[item.entity_id].state
        for item in members
        if item.entity_id in sources
        and sources[item.entity_id].trustworthy
        and sources[item.entity_id].state in ("heat", "cool")
    }
    if not zone_ids:
        reason = "no_members"
        blocked = "insufficient_data"
    elif len(known) != len(zone_ids) or not equipment_available:
        blocked = "insufficient_data"
    elif group.single_hvac_mode and len(reported_modes) > 1:
        reason, blocked = "observed_group_conflict", "observed_group_conflict"
    else:
        delta = heating - cooling
        if max(heating, cooling) < group.min_demand_score:
            desired, reason = "off", "no_significant_demand"
        elif abs(delta) < group.score_deadband:
            # Do not retain an unrelated mode; keep only a mode with real demand.
            desired = (
                current
                if current in ("heat", "cool")
                and (heating if current == "heat" else cooling)
                >= group.min_demand_score
                else "unknown"
            )
            reason = "score_deadband"
            if desired == "unknown":
                blocked = "balanced_demand"
        else:
            desired, reason = (
                ("heat", "weighted_heating_demand")
                if delta > 0
                else ("cool", "weighted_cooling_demand")
            )
        if current == "unknown":
            blocked = blocked or "current_mode_unknown"
        elif desired != "unknown" and desired != current:
            elapsed = (now - memory.changed_at).total_seconds()
            if elapsed < group.min_switch_seconds:
                blocked, deadline = (
                    "minimum_switch_interval",
                    memory.changed_at + timedelta(seconds=group.min_switch_seconds),
                )
    proposed = (
        "unknown"
        if desired == "unknown" or current == "unknown"
        else current
        if blocked
        else desired
    )
    return GroupDecision(
        group.id,
        current,
        desired,
        proposed,
        heating,
        cooling,
        reason,
        blocked,
        bool(
            not blocked
            and current != "unknown"
            and desired != "unknown"
            and desired != current
        ),
        deadline,
        zone_ids,
        len(known),
        mode.quality,
    )


def evaluate(
    building: Building,
    demands: Mapping[str, ZoneDemand],
    sources: Mapping[str, SourceState],
    memories: Mapping[str, GroupMemory],
    now: datetime,
) -> tuple[GroupDecision, ...]:
    return tuple(
        decide_group(building, group, demands, sources, memories[group.id], now)
        for group in building.groups
    )
