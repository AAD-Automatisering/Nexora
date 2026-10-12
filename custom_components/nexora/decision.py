"""Pure observation simulator. No actuator commands or thermal demand calculation."""

from dataclasses import dataclass
from typing import Mapping

from .models import Building


@dataclass(frozen=True)
class Observation:
    state: str | None
    quality: (
        str  # missing / unavailable / unknown / observed (not guaranteed trustworthy)
    )


@dataclass(frozen=True)
class Decision:
    equipment_id: str
    action: str
    reason: str


def simulate(
    building: Building, observations: Mapping[str, Observation]
) -> tuple[Decision, ...]:
    """Explain hold decisions and detect already observed heat/cool conflicts."""
    modes: dict[str, set[str]] = {group.id: set() for group in building.groups}
    for item in building.equipment:
        observation = observations.get(item.entity_id)
        if item.group_id and observation and observation.state in ("heat", "cool"):
            modes[item.group_id].add(observation.state)
    constrained = {group.id for group in building.groups if group.single_hvac_mode}
    decisions = []
    for item in building.equipment:
        observation = observations.get(item.entity_id)
        if item.group_id in constrained and len(modes[item.group_id]) > 1:
            reason = "observed_group_conflict"
        elif not observation or observation.quality != "observed":
            reason = "source_unavailable"
        else:
            reason = "foundation_read_only"
        decisions.append(Decision(item.id, "hold", reason))
    return tuple(decisions)
