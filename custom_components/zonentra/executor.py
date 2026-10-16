"""Group preset and correction plans for active outdoor-unit mode control.

Installation fact (Mitsubishi via Intesis/KNX): the first indoor unit that
switches on decides the outdoor unit mode; a unit in the opposite mode then
does nothing. There is no physical feedback of the outdoor mode.

Zonentra therefore keeps every indoor unit of a group *preset* in the group
mode, replacing a manual "airco stand" automation:

* on a group mode change, every available indoor unit gets the new mode:
  running units are stopped and wait through the runtime timing gate before
  they restart; units that were already off get a short preset
  pulse (``set_hvac_mode`` -> a few seconds -> ``turn_off``), so the next
  person who switches a unit on starts it in the right mode;
* a running unit in a mode that does not fit the group mode is corrected
  after a short delay (people may still be adjusting it).

This module describes commands and pending preset applications. The runtime
sends the commands and also handles room regulation, setpoints, fans, vanes
and shading through their own planners.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Mapping

from .indoor import IndoorUnitObservation

COMPATIBLE = {"heat": ("heat", "fan_only"), "cool": ("cool", "dry", "fan_only")}
PULSE_SECONDS = 3
CORRECTION_DELAY_SECONDS = 30  # Let people finish adjusting a unit first.
CORRECTION_REPEAT_SECONDS = 120  # Never fight a unit in a tight loop.
PRESET_RETRY_SECONDS = 120  # Retry failed service calls without a tight loop.


@dataclass(frozen=True)
class PresetMemory:
    """Last group mode Zonentra applied; persisted across restarts."""

    mode: str | None = None
    changed_at: datetime | None = None
    corrected: tuple[tuple[str, datetime], ...] = ()  # (equipment_id, at)


@dataclass(frozen=True)
class ModeCommand:
    equipment_id: str
    entity_id: str
    service: str  # HA service name; the runtime dispatches through domain.
    hvac_mode: str | None
    delay_seconds: int  # 0 = now; turn_off of a preset pulse is delayed
    reason: str  # preset_pulse / switch_running_unit / correct_running_unit
    temperature: float | None = None  # set_temperature only (0.9 room regulation)
    fan_mode: str | None = None  # set_fan_mode only (0.9 room thermostat)
    domain: str = "climate"  # HA service domain, also used by dispatch.
    value: str | float | None = None  # 0.10 vane position


@dataclass
class PresetApplication:
    """A group preset awaiting successful service calls, one per indoor unit."""

    memory: PresetMemory
    commands: dict[str, ModeCommand]
    in_flight: set[str]
    retry_at: datetime | None = None


@dataclass(frozen=True)
class ModeControl:
    group_id: str
    target_mode: str | None  # heat / cool, or None when nothing is decided
    preset_mode: str | None
    status: str
    blocked_until: datetime | None
    commands: tuple[ModeCommand, ...]


def plan_mode_commands(
    group_id: str,
    group_mode: str,
    units: tuple[IndoorUnitObservation, ...],
    entity_ids: Mapping[str, str],
    changed_at: Mapping[str, datetime | None],
    memory: PresetMemory,
    min_switch_seconds: float,
    now: datetime,
    *,
    enabled: bool | None,
) -> tuple[ModeControl, PresetMemory]:
    """Decide which mode commands are needed for one outdoor unit group."""
    target = group_mode if group_mode in COMPATIBLE else None

    def result(status, commands=(), until=None, new_memory=memory):
        return (
            ModeControl(
                group_id, target, new_memory.mode, status, until, tuple(commands)
            ),
            new_memory,
        )

    if enabled is None:
        return result("waiting_for_switch_state")
    if not enabled:
        return result("disabled")
    if target is None:
        # Neutral or unknown: never invent a mode; keep the last preset.
        return result("no_group_mode" if group_mode == "unknown" else "neutral")
    available = [unit for unit in units if unit.available]
    if memory.mode != target:
        if memory.mode is not None and memory.changed_at is not None:
            allowed = memory.changed_at + timedelta(seconds=min_switch_seconds)
            if now < allowed:
                return result("minimum_switch_interval", until=allowed)
        commands = []
        for unit in available:
            entity_id = entity_ids[unit.equipment_id]
            if unit.selected_mode == "off":
                commands.append(
                    ModeCommand(
                        unit.equipment_id,
                        entity_id,
                        "set_hvac_mode",
                        target,
                        0,
                        "preset_pulse",
                    )
                )
                commands.append(
                    ModeCommand(
                        unit.equipment_id,
                        entity_id,
                        "turn_off",
                        None,
                        PULSE_SECONDS,
                        "preset_pulse",
                    )
                )
            elif unit.selected_mode not in COMPATIBLE[target]:
                commands.append(
                    ModeCommand(
                        unit.equipment_id,
                        entity_id,
                        "set_hvac_mode",
                        target,
                        0,
                        "switch_running_unit",
                    )
                )
        return result(
            "group_mode_applied", commands, new_memory=PresetMemory(target, now, ())
        )
    # In sync: correct running units whose mode does not fit the group mode.
    corrected = {key: at for key, at in memory.corrected}
    commands = []
    for unit in available:
        if unit.selected_mode in ("off", *COMPATIBLE[target]):
            continue
        since = changed_at.get(unit.equipment_id)
        if since is None or (now - since).total_seconds() < CORRECTION_DELAY_SECONDS:
            continue
        last = corrected.get(unit.equipment_id)
        if last and (now - last).total_seconds() < CORRECTION_REPEAT_SECONDS:
            continue
        corrected[unit.equipment_id] = now
        commands.append(
            ModeCommand(
                unit.equipment_id,
                entity_ids[unit.equipment_id],
                "set_hvac_mode",
                target,
                0,
                "correct_running_unit",
            )
        )
    new_memory = replace(memory, corrected=tuple(sorted(corrected.items())))
    return result(
        "corrected" if commands else "in_sync", commands, new_memory=new_memory
    )


def next_correction_check(
    units: tuple[IndoorUnitObservation, ...],
    changed_at: Mapping[str, datetime | None],
    memory: PresetMemory,
    target: str | None,
    now: datetime,
) -> datetime | None:
    """When a pending correction becomes due, so a timer can re-evaluate."""
    if target not in COMPATIBLE:
        return None
    corrected = dict(memory.corrected)
    due = []
    for unit in units:
        if not unit.available or unit.selected_mode in ("off", *COMPATIBLE[target]):
            continue
        since = changed_at.get(unit.equipment_id)
        if since is None:
            continue
        moments = [since + timedelta(seconds=CORRECTION_DELAY_SECONDS)]
        if last := corrected.get(unit.equipment_id):
            moments.append(last + timedelta(seconds=CORRECTION_REPEAT_SECONDS))
        moment = max(moments)
        if moment > now:
            due.append(moment)
    return min(due) if due else None
