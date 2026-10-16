"""Active timing gates shared by group presets and the final service guard."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .executor import COMPATIBLE, CORRECTION_DELAY_SECONDS, ModeCommand, ModeControl
from .thermostat import RoomUnitControl

THERMAL_MODES = ("heat", "cool", "dry", "auto", "heat_cool")


@dataclass
class GroupSwitch:
    target: str
    stopped_at: datetime | None = None
    resume_units: set[str] = field(default_factory=set)
    ready: bool = False


class TimingRuntimeMixin:
    def _start_block(self, entity_id, target, now):
        """Last-moment check, including changes since a command was planned."""
        state = self.hass.states.get(entity_id)
        if (
            state is None
            or state.state in ("unknown", "unavailable")
            or state.attributes.get("restored")
            or state.attributes.get("assumed_state")
        ):
            return "indoor_unit_unavailable", None
        if state.state == "off":
            until = state.last_changed + timedelta(
                seconds=self.building.settings.min_off_seconds
            )
            if now < until:
                return "minimum_off_time", until
        elif target in ("heat", "cool", "dry"):
            current = "cool" if state.state == "dry" else state.state
            requested = "cool" if target == "dry" else target
            if current in ("heat", "cool") and current != requested:
                return "changeover_required", None
        return None, None

    def _group_timing(self, group, target, previous, now):
        """Stop, observe stopped units, wait, then permit the new preset."""
        progress = self.group_switches.get(group.id)
        if not self.mode_active.get(group.id):
            self.group_switches.pop(group.id, None)
            return None
        if target not in COMPATIBLE:
            if target == "unknown" and progress:
                progress.stopped_at = None
                progress.ready = False
            else:
                self.group_switches.pop(group.id, None)
            return None
        if progress and progress.target != target:
            progress.target = target
            progress.ready = False
        units = self._group_units(group)
        entities = {item.id: item.entity_id for item in self.building.equipment}

        def blocked(status, until=None, commands=()):
            return ModeControl(
                group.id, target, previous.mode, status, until, tuple(commands)
            )

        if (
            previous.mode is not None
            and previous.mode != target
            and previous.changed_at
        ):
            until = previous.changed_at + timedelta(seconds=group.min_switch_seconds)
            if now < until:
                return blocked("minimum_switch_interval", until)
        incompatible = [
            u
            for u in units
            if u.available
            and u.selected_mode in THERMAL_MODES
            and u.selected_mode not in COMPATIBLE[target]
        ]
        if progress and progress.ready:
            if not incompatible:
                return None
            progress.ready = False
        # A preset memory changing while every unit is already off also needs
        # a changeover pause, measured from observed stops rather than requests.
        switching = (
            progress is not None
            or bool(incompatible)
            or previous.mode in COMPATIBLE
            and previous.mode != target
        )
        if switching:
            progress = progress or GroupSwitch(target)
            self.group_switches[group.id] = progress
            if any(not u.available for u in units):
                return blocked("changeover_unit_unavailable")
            running = [u for u in units if u.selected_mode in THERMAL_MODES]
            if running:
                progress.resume_units.update(u.equipment_id for u in running)
                ids = {u.equipment_id for u in units}
                self.pending_offs = [
                    p for p in self.pending_offs if p[1].equipment_id not in ids
                ]
                progress.stopped_at = None
                stops, deadlines = [], []
                for unit in running:
                    entity_id = entities[unit.equipment_id]
                    state = self.hass.states.get(entity_id)
                    minimum = self.building.settings.min_on_seconds
                    if previous.mode == target and unit in incompatible:
                        minimum = max(minimum, CORRECTION_DELAY_SECONDS)
                    until = state.last_changed + timedelta(seconds=minimum)
                    if now < until:
                        deadlines.append(until)
                    elif not self.command_tracker.is_pending(entity_id, now):
                        stops.append(
                            ModeCommand(
                                unit.equipment_id,
                                entity_id,
                                "turn_off",
                                None,
                                0,
                                "group_changeover_stop",
                            )
                        )
                return blocked(
                    "stopping_for_changeover",
                    min(deadlines) if deadlines else None,
                    stops,
                )
            if progress.stopped_at is None:
                stops = [
                    self.hass.states.get(entities[u.equipment_id]).last_changed
                    for u in units
                    if u.selected_mode == "off"
                ]
                progress.stopped_at = max(stops, default=now)
            until = progress.stopped_at + timedelta(
                seconds=self.building.settings.changeover_wait_seconds
            )
            if now < until:
                return blocked("changeover_wait", until)
        deadlines = []
        for unit in units:
            if unit.available and unit.selected_mode == "off":
                _, until = self._start_block(entities[unit.equipment_id], target, now)
                if until:
                    deadlines.append(until)
        if deadlines:
            return blocked("minimum_off_time", max(deadlines))
        if progress:
            progress.ready = True
        return None

    def _room_changeover(self, item, unit, target, now):
        progress = self.room_switches.get(item.id)
        requested = "cool" if target == "dry" else target
        current = "cool" if unit.selected_mode == "dry" else unit.selected_mode
        if requested not in ("heat", "cool"):
            self.room_switches.pop(item.id, None)
            return None, None
        opposite = current in ("heat", "cool") and current != requested
        if not opposite and progress is None:
            return None, None
        progress = progress or GroupSwitch(target)
        if progress.target != target:
            progress.target = target
        self.room_switches[item.id] = progress
        state = self.hass.states.get(item.entity_id)
        if unit.selected_mode in THERMAL_MODES:
            until = state.last_changed + timedelta(
                seconds=self.building.settings.min_on_seconds
            )
            if now < until:
                return RoomUnitControl(item.id, "minimum_on_time"), until
            progress.stopped_at = None
            command = (
                None
                if self.command_tracker.is_pending(item.entity_id, now)
                else ModeCommand(
                    item.id, item.entity_id, "turn_off", None, 0, "room_changeover_stop"
                )
            )
            return RoomUnitControl(item.id, "stopping_for_changeover", command), None
        if unit.selected_mode != "off":
            return RoomUnitControl(item.id, "changeover_unconfirmed"), None
        progress.stopped_at = progress.stopped_at or state.last_changed
        until = max(
            progress.stopped_at
            + timedelta(seconds=self.building.settings.changeover_wait_seconds),
            state.last_changed
            + timedelta(seconds=self.building.settings.min_off_seconds),
        )
        if now < until:
            return RoomUnitControl(item.id, "changeover_wait"), until
        self.room_switches.pop(item.id, None)
        return None, None
