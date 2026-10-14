"""Event-driven read-only bridge from HA states to pure building models."""

import logging
from dataclasses import asdict, replace
from datetime import timedelta

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .control import plan
from .decision import Observation, simulate
from .demand import calculate_demand, collect_zone, comfort_limits
from .engine import GroupMemory, evaluate, observe_mode
from .executor import (
    ModeCommand,
    PresetMemory,
    next_correction_check,
    plan_mode_commands,
)
from .indoor import compare_modes, observe_group, observe_unit
from .models import Building
from .observations import (
    ClimateAttributes,
    Reading,
    SourceState,
    max_age_for,
    read,
)
from .override import CommandTracker, classify_transition, update_override
from .presence import MotionMemory, Occupancy, motion_state, occupancy, read_presence
from .thermostat import (
    UNIT_MODES,
    RoomUnitControl,
    SetpointPlan,
    Thermostat,
    active_band,
    plan_fan,
    plan_room_mode,
    plan_room_unit,
    plan_setpoint,
    room_demand,
    safe_modes,
    update_thermostat,
)

_LOGGER = logging.getLogger(__name__)
# A setpoint change right after a Zonentra command is the unit settling (an
# integration may restore its own setpoint on switch-on), not a person.
SETPOINT_SETTLE_SECONDS = 60


def _setpoint(value) -> str | None:
    try:
        return f"{float(value):.1f}"
    except TypeError, ValueError:
        return None


def _origin(event) -> str:
    """Who caused a state change, as far as Home Assistant can tell.

    A KNX room controller produces a bare context; a service call from an
    automation or script carries a parent context; the HA UI carries a user.
    """
    context = getattr(event, "context", None)
    if context is not None and context.user_id:
        return "ha_user"
    if context is not None and context.parent_id:
        return "automation"
    return "device"


class BuildingRuntime:
    """Own one building's observations; no service or hardware access."""

    def __init__(
        self, hass: HomeAssistant, building: Building, *, active: bool = False
    ) -> None:
        self.hass = hass
        # Active outdoor-stand control exists only for the central layout.
        self.active_capable = active
        self.mode_active: dict[str, bool | None] = {}  # None until switch restored
        self.preset_memories: dict[str, PresetMemory] = {}
        self.mode_controls = {}
        self.pending_offs = []  # (due, ModeCommand, target mode)
        self.command_log: list[dict] = []
        self.mode_store = None
        self.building = building
        self.signal = f"zonentra_{building.id}_updated"
        self.observations: dict[str, Observation] = {}
        self.decisions = ()
        self.outdoor_temperature = Reading(None, "missing")
        self.zone_snapshots = {}
        self.zone_demands = {}
        self.group_decisions = {}
        # Indoor unit interpretation; diagnostic only, never physical feedback.
        self.indoor_units = {}
        self.group_observations = {}
        self.mode_comparisons = {}
        self.evaluated_at = dt_util.utcnow()
        # 0.8 presence (building) and motion (zone) select comfort/eco/away.
        self.presence = "not_configured"
        self.motion_memories: dict[str, MotionMemory] = {}
        self.zone_occupancy: dict[str, Occupancy] = {}
        self._motion_checks: list = []
        # 0.9 room thermostats (central layout). Persisted by the entry setup.
        self.thermostats: dict[str, Thermostat] = {}
        self.thermostat_store = None
        self.thermostat_cache: dict | None = None  # survives central reloads
        self.zone_bands: dict[str, tuple[str, str]] = {}
        self.comfort: dict[str, tuple[Reading, Reading]] = {}
        self.room_controls: dict[str, RoomUnitControl] = {}
        self.setpoint_plans: dict[str, SetpointPlan] = {}
        self.setpoint_sent: dict = {}
        self.setpoint_tracker = CommandTracker()
        self.last_command_at: dict = {}
        self._setpoint_checks: list = []
        self.mode_applied: dict[str, str] = {}  # dry / fan_only set per unit
        self.fan_applied: dict[str, str] = {}  # fan speed sent per unit
        # 0.5 simulated control. In memory only: nothing survives a restart.
        self.overrides = {}
        self.last_transitions = {}
        self.coordination_memories = {}
        self.coordinations = {}
        self.unit_intents = {}
        # Records Zonentra-initiated changes; stays empty while read-only.
        self.command_tracker = CommandTracker()
        self.memories = {
            group.id: GroupMemory("unknown", dt_util.utcnow())
            for group in building.groups
        }
        self._cancel_deadline = None

    @callback
    def refresh(self, event=None) -> None:
        """Refresh configured state values on an input event, without polling."""
        now = dt_util.utcnow()
        sources = {}
        observations = {}
        for entity_id in self.building.entity_ids:
            state = self.hass.states.get(entity_id)
            value = state.state if state else None
            quality = (
                "missing"
                if state is None
                else value
                if value in ("unknown", "unavailable")
                else "observed"
            )
            observations[entity_id] = Observation(value, quality)
            if state:
                sources[entity_id] = SourceState(
                    value,
                    state.attributes.get("unit_of_measurement"),
                    state.last_reported,
                    not (
                        state.attributes.get("restored")
                        or state.attributes.get("assumed_state")
                    ),
                    state.last_changed,
                    self._climate(state) if entity_id.startswith("climate.") else None,
                )
        transitions = self._transitions(event, now)
        decisions = simulate(self.building, observations)
        if decisions != self.decisions:
            _LOGGER.debug(
                "Read-only simulation updated: %s", [d.reason for d in decisions]
            )
        self.observations = observations
        self.decisions = decisions
        self.evaluated_at = now
        self.outdoor_temperature = read(
            sources.get(self.building.settings.outdoor_temperature_entity),
            "temperature",
            now,
            self.building.settings.outdoor_max_age_seconds,
        )
        self._occupancy(sources, now)
        bands, comfort = {}, {}
        for zone in self.building.zones:
            thermostat = self.thermostat(zone.id)
            bands[zone.id] = active_band(
                thermostat.preset, self.zone_occupancy[zone.id]
            )
            band = (thermostat.heating_limit, thermostat.cooling_limit)
            comfort[zone.id] = band if thermostat.has_band else None
        self.zone_bands = bands
        self.comfort = {
            zone.id: comfort_limits(zone, sources, now, comfort[zone.id])
            for zone in self.building.zones
        }
        self.zone_snapshots = {
            zone.id: collect_zone(
                self.building,
                zone,
                sources,
                now,
                self.outdoor_temperature,
                bands[zone.id][0],
                comfort[zone.id],
            )
            for zone in self.building.zones
        }
        demands = {}
        for zone in self.building.zones:
            demand = calculate_demand(
                zone,
                self.zone_snapshots[zone.id],
                self.zone_demands[zone.id].demand
                if zone.id in self.zone_demands
                else "unknown",
            )
            # Thermostat mode: off asks nothing, heat/cool only one direction.
            demands[zone.id] = room_demand(self.thermostat(zone.id).hvac_mode, demand)
        self.zone_demands = demands
        for group in self.building.groups:
            mode = observe_mode(group, sources, now)
            current = mode.value if mode.quality == "valid" else "unknown"
            if current != self.memories[group.id].current_mode:
                self.memories[group.id] = GroupMemory(current, now)
        previous_group_decisions = self.group_decisions
        self.group_decisions = {
            decision.group_id: decision
            for decision in evaluate(
                self.building, self.zone_demands, sources, self.memories, now
            )
        }
        indoor_units = {}
        group_observations = {}
        for group in self.building.groups:
            units, observation = observe_group(self.building, group, sources)
            indoor_units.update({unit.equipment_id: unit for unit in units})
            group_observations[group.id] = observation
        for item in self.building.equipment:
            if item.kind == "hvac" and item.id not in indoor_units:
                indoor_units[item.id] = observe_unit(item, sources.get(item.entity_id))
        self.indoor_units = indoor_units
        self.group_observations = group_observations
        self.mode_comparisons = {
            group_id: compare_modes(
                self.group_decisions[group_id].desired_mode, observation
            )
            for group_id, observation in group_observations.items()
        }
        if self.group_decisions != previous_group_decisions:
            _LOGGER.debug(
                "Climate simulation: %s",
                [
                    {
                        "current": d.current_mode,
                        "desired": d.desired_mode,
                        "proposed": d.proposed_mode,
                        "reason": d.reason,
                        "blocked": d.blocked_reason,
                    }
                    for d in self.group_decisions.values()
                ],
            )
        self._plan(transitions, sources, now)
        if self.active_capable:
            self._control(sources, now)
        if self._cancel_deadline:
            self._cancel_deadline()
            self._cancel_deadline = None
        deadlines = []
        for zone in self.building.zones:
            # Only update_based measurements can expire; limit entities never do.
            if max_age := max_age_for(zone.sensor_validation, zone.max_age_seconds):
                for field in ("temperature_entity", "humidity_entity", "co2_entity"):
                    source = sources.get(getattr(zone, field))
                    if source and source.reported_at:
                        deadlines.append(
                            source.reported_at + timedelta(seconds=max_age)
                        )
        outside = sources.get(self.building.settings.outdoor_temperature_entity)
        if (
            outside
            and outside.reported_at
            and self.building.settings.outdoor_max_age_seconds
        ):
            deadlines.append(
                outside.reported_at
                + timedelta(seconds=self.building.settings.outdoor_max_age_seconds)
            )
        for group in self.building.groups:
            source = sources.get(group.mode_entity)
            if group.max_age_seconds and source and source.reported_at:
                deadlines.append(
                    source.reported_at + timedelta(seconds=group.max_age_seconds)
                )
            if deadline := self.group_decisions[group.id].blocked_until:
                deadlines.append(deadline)
        # Override expiry and anti-cycling ends re-evaluate without new events.
        deadlines.extend(override.expires_at for override in self.overrides.values())
        deadlines.extend(
            intent.blocked_until
            for intent in self.unit_intents.values()
            if intent.blocked_until
        )
        deadlines.extend(
            item.waiting_until
            for item in self.coordinations.values()
            if item.waiting_until
        )
        deadlines.extend(due for due, _, _ in self.pending_offs)
        deadlines.extend(self._motion_checks)
        deadlines.extend(self._setpoint_checks)
        for group_id, control in self.mode_controls.items():
            if control.blocked_until:
                deadlines.append(control.blocked_until)
            group = next(g for g in self.building.groups if g.id == group_id)
            if check := next_correction_check(
                self._group_units(group),
                self._changed_at(sources),
                self.preset_memories.get(group_id, PresetMemory()),
                control.target_mode,
                now,
            ):
                deadlines.append(check)
        future = [deadline for deadline in deadlines if deadline > now]
        if future:
            self._cancel_deadline = async_track_point_in_utc_time(
                self.hass, self.refresh, min(future)
            )
        async_dispatcher_send(self.hass, self.signal)

    def _occupancy(self, sources, now) -> None:
        """Building presence and zone motion decide each zone's band."""
        settings = self.building.settings
        self.presence = read_presence(
            settings.presence_entity, sources.get(settings.presence_entity)
        )
        checks, result = [], {}
        for zone in self.building.zones:
            entity = zone.occupancy_entity
            motion, memory, check = motion_state(
                entity,
                sources.get(entity) if entity else None,
                self.motion_memories.get(zone.id, MotionMemory()),
                settings.motion_delay_seconds,
                settings.motion_off_delay_minutes,
                now,
            )
            self.motion_memories[zone.id] = memory
            if check:
                checks.append(check)
            result[zone.id] = occupancy(self.presence, motion)
        self.zone_occupancy = result
        self._motion_checks = checks

    # --- Room thermostats (0.9) -----------------------------------------------

    def thermostat(self, zone_id: str) -> Thermostat:
        return self.thermostats.get(zone_id) or Thermostat()

    def load_thermostats(self, data: dict | None) -> None:
        for zone_id, item in ((data or {}).get("zones") or {}).items():
            self.thermostats[zone_id] = Thermostat.from_dict(item)

    @callback
    def set_thermostat(self, zone_id: str, **changes) -> Thermostat:
        """Validated thermostat change (ValueError with a code), then refresh."""
        zone = next((z for z in self.building.zones if z.id == zone_id), None)
        if zone is None or not self.active_capable:
            raise ValueError("zone_not_loaded")
        new = update_thermostat(self.thermostat(zone_id), zone.hysteresis, **changes)
        self.thermostats[zone_id] = new
        if self.thermostat_cache is not None:
            self.thermostat_cache[zone_id] = new.as_dict()
        if self.thermostat_store is not None:
            self.hass.async_create_task(
                self.thermostat_store.async_save(
                    {
                        "zones": {
                            key: value.as_dict()
                            for key, value in self.thermostats.items()
                        }
                    }
                )
            )
        self.refresh()
        return new

    def regulated(self, zone_id: str | None) -> bool:
        """Room regulation really acts (central layout and switched on)."""
        return self.active_capable and self.thermostat(zone_id).regulation

    def _safe_modes(self, item) -> frozenset[str]:
        if item.group_id is None:
            return frozenset({"heat", "cool"})
        if self.mode_active.get(item.group_id):
            memory = self.preset_memories.get(item.group_id, PresetMemory())
            return safe_modes((), memory.mode)
        running = tuple(
            self.indoor_units[other.id].selected_mode
            for other in self.building.equipment
            if other.kind == "hvac"
            and other.id != item.id
            and other.group_id == item.group_id
            and other.id in self.indoor_units
            and self.indoor_units[other.id].available
        )
        return safe_modes(running, None)

    def _regulate(self, sources, now, busy: set[str], available: bool) -> None:
        """Switch regulated rooms' units on/off and steer their setpoints."""
        settings = self.building.settings
        zones = {zone.id: zone for zone in self.building.zones}
        controls, plans, checks = {}, {}, []
        for item in self.building.equipment:
            if item.kind != "hvac" or item.id not in self.unit_intents:
                continue
            intent = self.unit_intents[item.id]
            enabled = self.regulated(item.zone_id)
            thermostat = self.thermostat(item.zone_id)
            unit = self.indoor_units.get(item.id)
            unit_busy = item.id in busy or self.command_tracker.is_pending(
                item.entity_id, now
            )
            override = self.overrides.get(item.id)
            if thermostat.hvac_mode in UNIT_MODES:
                if enabled and override and override.active(now):
                    control = RoomUnitControl(item.id, "manual_override")
                elif unit is None or not unit.available:
                    control = RoomUnitControl(item.id, "indoor_unit_unavailable")
                elif enabled and (until := self._restart_blocked(item, unit, now)):
                    control = RoomUnitControl(item.id, "minimum_off_time")
                    checks.append(until)
                else:
                    control = plan_room_mode(
                        thermostat.hvac_mode,
                        unit.selected_mode,
                        item.id,
                        item.entity_id,
                        enabled=enabled,
                        safe_modes=self._safe_modes(item),
                        busy=unit_busy,
                        applied=self.mode_applied.get(item.id),
                    )
            else:
                self.mode_applied.pop(item.id, None)
                control = plan_room_unit(
                    intent.action,
                    intent.reason,
                    item.id,
                    item.entity_id,
                    enabled=enabled,
                    safe_modes=self._safe_modes(item),
                    busy=unit_busy,
                )
            if control.command and not available:
                control = RoomUnitControl(item.id, "climate_service_unavailable")
            controls[item.id] = control
            if control.command:
                if thermostat.hvac_mode in UNIT_MODES:
                    self.mode_applied[item.id] = thermostat.hvac_mode
                self._execute(control.command, now)
            elif enabled and unit and unit.available and not unit_busy:
                self._fan(item, unit, thermostat, now, available)
            plan = self._setpoint_plan(item, zones[item.zone_id], settings, now)
            if (
                plan.send
                and enabled
                and available
                and control.command is None
                and item.id not in busy
                and not self.setpoint_tracker.is_pending(item.entity_id, now)
            ):
                self.setpoint_sent[item.id] = now
                self._execute(
                    ModeCommand(
                        item.id,
                        item.entity_id,
                        "set_temperature",
                        None,
                        0,
                        "self_regulation",
                        plan.setpoint,
                    ),
                    now,
                )
            elif plan.send:
                plan = replace(plan, send=False)
            if plan.next_check and enabled:
                checks.append(plan.next_check)
            plans[item.id] = plan
        self.room_controls = controls
        self.setpoint_plans = plans
        self._setpoint_checks = checks

    def _restart_blocked(self, item, unit, now):
        """Restart protection for a unit that is off (dry / fan_only rooms)."""
        if unit.selected_mode != "off":
            return None
        state = self.hass.states.get(item.entity_id)
        if state is None or state.last_changed is None:
            return None
        until = state.last_changed + timedelta(
            seconds=self.building.settings.min_off_seconds
        )
        return until if now < until else None

    def _fan(self, item, unit, thermostat, now, available) -> None:
        """Pass the thermostat's fan speed to a running unit, once per change."""
        if thermostat.fan_mode is None:
            self.fan_applied.pop(item.id, None)
            return
        state = self.hass.states.get(item.entity_id)
        supported = tuple((state.attributes.get("fan_modes") or ()) if state else ())
        fan = plan_fan(
            thermostat.fan_mode,
            unit.selected_mode,
            unit.fan_mode,
            self.fan_applied.get(item.id),
            supported,
        )
        if unit.fan_mode == thermostat.fan_mode:
            self.fan_applied[item.id] = thermostat.fan_mode
        if fan is None or not available:
            return
        self.fan_applied[item.id] = fan
        self._execute(
            ModeCommand(
                item.id,
                item.entity_id,
                "set_fan_mode",
                None,
                0,
                "thermostat_fan_mode",
                fan_mode=fan,
            ),
            now,
        )

    def unit_options(self, zone_id: str) -> tuple[frozenset[str], tuple[str, ...]]:
        """HVAC modes and fan speeds that every indoor unit of a zone supports."""
        states = [
            self.hass.states.get(item.entity_id)
            for item in self.building.equipment
            if item.kind == "hvac" and item.zone_id == zone_id
        ]
        states = [state for state in states if state is not None]
        if not states:
            return frozenset(), ()
        modes = frozenset.intersection(
            *(frozenset(state.attributes.get("hvac_modes") or ()) for state in states)
        )
        fans = tuple(
            fan
            for fan in states[0].attributes.get("fan_modes") or ()
            if all(fan in (state.attributes.get("fan_modes") or ()) for state in states)
        )
        return modes, fans

    def _setpoint_plan(self, item, zone, settings, now) -> SetpointPlan:
        unit = self.indoor_units.get(item.id)
        override = self.overrides.get(item.id)
        if unit is None or not unit.available:
            return SetpointPlan("unit_unavailable")
        if override and override.active(now):
            return SetpointPlan("manual_override")
        snapshot = self.zone_snapshots[item.zone_id]
        state = self.hass.states.get(item.entity_id)
        attributes = state.attributes if state else {}
        return plan_setpoint(
            unit.selected_mode,
            snapshot.heating_limit.value,
            snapshot.cooling_limit.value,
            zone.hysteresis,
            snapshot.temperature.value
            if snapshot.temperature.quality == "valid"
            else None,
            unit.target_temperature,
            self.setpoint_sent.get(item.id),
            now,
            max_offset=settings.setpoint_max_offset,
            interval_seconds=settings.setpoint_interval_seconds,
            step=attributes.get("target_temp_step"),
            min_temp=attributes.get("min_temp"),
            max_temp=attributes.get("max_temp"),
        )

    # --- Active outdoor-stand control (0.7) -----------------------------------

    def load_presets(self, data: dict | None) -> None:
        """Restore the last applied group modes, so a restart does not pulse."""
        for group_id, item in ((data or {}).get("groups") or {}).items():
            changed = dt_util.parse_datetime(item.get("changed_at") or "")
            self.preset_memories[group_id] = PresetMemory(item.get("mode"), changed)

    @callback
    def set_mode_active(self, group_id: str, active: bool) -> None:
        self.mode_active[group_id] = active
        if not active:
            # Emergency stop: nothing more is sent, not even a pending pulse-off.
            group_units = {
                item.id for item in self.building.equipment if item.group_id == group_id
            }
            self.pending_offs = [
                item
                for item in self.pending_offs
                if item[1].equipment_id not in group_units
            ]
        self.refresh()

    def _group_units(self, group):
        return tuple(
            self.indoor_units[item.id]
            for item in self.building.equipment
            if item.kind == "hvac"
            and item.group_id == group.id
            and item.id in self.indoor_units
        )

    def _changed_at(self, sources):
        return {
            item.id: sources[item.entity_id].changed_at
            for item in self.building.equipment
            if item.kind == "hvac" and item.entity_id in sources
        }

    def _control(self, sources, now) -> None:
        """Plan and send mode commands; every command is tracked and logged."""
        available = self.hass.services.has_service("climate", "set_hvac_mode")
        changed_at = self._changed_at(sources)
        entity_ids = {item.id: item.entity_id for item in self.building.equipment}
        controls = {}
        for group in self.building.groups:
            previous = self.preset_memories.get(group.id, PresetMemory())
            control, memory = plan_mode_commands(
                group.id,
                self.coordinations[group.id].group_mode,
                self._group_units(group),
                entity_ids,
                changed_at,
                previous,
                group.min_switch_seconds,
                now,
                enabled=self.mode_active.get(group.id),
            )
            if control.commands and not available:
                control = replace(
                    control, status="climate_service_unavailable", commands=()
                )
                memory = previous
            controls[group.id] = control
            if memory != previous:
                self.preset_memories[group.id] = memory
                if memory.mode != previous.mode:
                    self._save_presets()
            for command in control.commands:
                if command.delay_seconds:
                    self.pending_offs.append(
                        (
                            now + timedelta(seconds=command.delay_seconds),
                            command,
                            control.target_mode,
                        )
                    )
                else:
                    self._execute(command, now)
        self.mode_controls = controls
        due = [item for item in self.pending_offs if item[0] <= now]
        self.pending_offs = [item for item in self.pending_offs if item[0] > now]
        busy = {
            command.equipment_id
            for control in controls.values()
            for command in control.commands
        }
        for _, command, target in due:
            source = sources.get(command.entity_id)
            if source is None or source.state != target:
                # Someone changed the unit during the pulse: leave it alone.
                self._log(command, now, "skipped_changed_during_pulse")
                continue
            intent = self.unit_intents.get(command.equipment_id)
            zone_id = intent.zone_id if intent else None
            if self.regulated(zone_id) and intent.desired_mode == target:
                # 0.9: the regulated room needs the unit on in this mode.
                self._log(command, now, "skipped_room_demand")
                continue
            busy.add(command.equipment_id)
            self._execute(command, now)
        busy |= {command.equipment_id for _, command, _ in self.pending_offs}
        self._regulate(sources, now, busy, available)

    def _execute(self, command, now) -> None:
        data = {"entity_id": command.entity_id}
        if command.service == "set_fan_mode":
            data["fan_mode"] = command.fan_mode  # An attribute: nothing to track.
        elif command.service == "set_temperature":
            expected = _setpoint(command.temperature)
            self.setpoint_tracker.register(command.entity_id, expected, now)
            data["temperature"] = command.temperature
        else:
            expected = (
                command.hvac_mode if command.service == "set_hvac_mode" else "off"
            )
            self.command_tracker.register(command.entity_id, expected, now)
        self.last_command_at[command.entity_id] = now
        if command.hvac_mode:
            data["hvac_mode"] = command.hvac_mode
        entry = self._log(command, now, "sending")
        self.hass.async_create_task(self._call(command.service, data, entry))

    async def _call(self, service, data, entry) -> None:
        try:
            await self.hass.services.async_call(
                "climate", service, data, blocking=True, context=Context()
            )
        except Exception as err:  # noqa: BLE001 - report, never crash the runtime
            entry["result"] = f"failed: {type(err).__name__}"
            _LOGGER.warning("Zonentra %s on %s failed: %s", service, data, err)
        else:
            entry["result"] = "sent"

    def _log(self, command, now, result) -> dict:
        entry = {
            "at": now.isoformat(),
            "group_id": next(
                (
                    item.group_id
                    for item in self.building.equipment
                    if item.id == command.equipment_id
                ),
                None,
            ),
            "equipment_id": command.equipment_id,
            "entity_id": command.entity_id,
            "service": command.service,
            "hvac_mode": command.hvac_mode,
            "temperature": command.temperature,
            "fan_mode": command.fan_mode,
            "reason": command.reason,
            "result": result,
        }
        self.command_log = [*self.command_log, entry][-30:]
        _LOGGER.info("Zonentra mode control: %s", entry)
        return entry

    def _save_presets(self) -> None:
        if self.mode_store is None:
            return
        data = {
            "groups": {
                group_id: {
                    "mode": memory.mode,
                    "changed_at": memory.changed_at.isoformat()
                    if memory.changed_at
                    else None,
                }
                for group_id, memory in self.preset_memories.items()
            }
        }
        self.hass.async_create_task(self.mode_store.async_save(data))

    def _transitions(self, event, now) -> dict[str, str]:
        """Classify a state_changed event of a linked indoor unit, if any."""
        if getattr(event, "event_type", None) != EVENT_STATE_CHANGED:
            return {}  # Setup, timers and same-value reports are no transitions.
        entity_id = event.data.get("entity_id")
        old, new = event.data.get("old_state"), event.data.get("new_state")
        transitions = {}
        for item in self.building.equipment:
            if item.kind != "hvac" or item.entity_id != entity_id:
                continue
            old_value = old.state if old else None
            new_value = new.state if new else None
            initiated = (
                old is not None
                and old_value != new_value
                and self.command_tracker.confirm(entity_id, new_value, now)
            )
            trusted = new is not None and not (
                new.attributes.get("restored") or new.attributes.get("assumed_state")
            )
            transition = classify_transition(
                old_value,
                new_value,
                old_present=old is not None,
                trusted=trusted,
                zonentra_initiated=initiated,
                origin=_origin(event),
            )
            if transition == "attribute_update" and trusted:
                transition = self._setpoint_transition(entity_id, old, new, event, now)
            transitions[item.id] = transition
            self.last_transitions[item.id] = (transitions[item.id], now)
        return transitions

    def _setpoint_transition(self, entity_id, old, new, event, now) -> str:
        """0.9: who changed a running unit's setpoint (attribute only)."""
        before = _setpoint(old.attributes.get("temperature"))
        after = _setpoint(new.attributes.get("temperature"))
        if before == after or after is None:
            return "attribute_update"
        if self.setpoint_tracker.confirm(entity_id, after, now):
            return "zonentra_setpoint"
        if _origin(event) == "automation":
            return "automation_setpoint"
        last = self.last_command_at.get(entity_id)
        if last and (now - last).total_seconds() < SETPOINT_SETTLE_SECONDS:
            return "setpoint_after_command"
        return "manual_setpoint"

    def _plan(self, transitions, sources, now) -> None:
        """Update manual overrides and simulate group coordination and intents."""
        settings = self.building.settings
        overrides, events = {}, {}
        for item in self.building.equipment:
            if item.kind != "hvac":
                continue
            source = sources.get(item.entity_id)
            override, event = update_override(
                self.overrides.get(item.id),
                transitions.get(item.id),
                item.id,
                source.state if source else None,
                now,
                enabled=settings.manual_override_enabled,
                duration_minutes=settings.manual_override_duration_minutes,
                regulated=self.regulated(item.zone_id),
            )
            if override:
                overrides[item.id] = override
            if event:
                events[item.id] = event
                _LOGGER.debug("Manual override %s: %s", item.id, event)
        self.overrides = overrides
        self.command_tracker.expire(now)
        changed_at = {
            item.id: sources[item.entity_id].changed_at
            for item in self.building.equipment
            if item.kind == "hvac" and item.entity_id in sources
        }
        self.coordinations, self.unit_intents, self.coordination_memories = plan(
            self.building,
            self.group_decisions,
            self.group_observations,
            self.indoor_units,
            changed_at,
            self.zone_demands,
            overrides,
            events,
            self.coordination_memories,
            now,
        )

    def _climate(self, state) -> ClimateAttributes:
        """Copy only the read-only climate attributes Zonentra explains."""
        attributes = state.attributes
        fan_mode = attributes.get("fan_mode")
        return ClimateAttributes(
            attributes.get("hvac_action"),
            attributes.get("current_temperature"),
            attributes.get("temperature"),
            str(fan_mode) if fan_mode is not None else None,
            self.hass.config.units.temperature_unit,
            state.last_updated,
        )

    @callback
    def close(self):
        """Cancel the single next-deadline timer on unload."""
        if self._cancel_deadline:
            self._cancel_deadline()
            self._cancel_deadline = None

    @property
    def status(self) -> str:
        if any(d.reason == "observed_group_conflict" for d in self.decisions):
            return "conflict"
        if any(o.quality != "observed" for o in self.observations.values()):
            return "degraded"
        if any(
            (zone.heating_limit is not None or zone.heating_limit_entity)
            and self.zone_demands[zone.id].demand == "unknown"
            for zone in self.building.zones
        ):
            return "degraded"
        return "read_only"

    def summary(self) -> dict:
        """Return bounded metadata; do not expose alarm states or raw attributes."""
        return {
            "read_only": True,
            "outdoor_temperature_c": self.outdoor_temperature.value,
            "outdoor_temperature_quality": self.outdoor_temperature.quality,
            "building_presence": self.presence,
            "regulated_zones": sum(
                self.regulated(zone.id) for zone in self.building.zones
            ),
            "outdoor_temperature_validation": self.outdoor_temperature.strategy,
            "outdoor_temperature_freshness_verified": (
                self.outdoor_temperature.freshness_verified
            ),
            "outdoor_temperature_selection_required": bool(
                self.building.settings.outdoor_temperature_candidates
            ),
            "zones": len(self.building.zones),
            "groups": len(self.building.groups),
            "equipment": len(self.building.equipment),
            "unavailable_inputs": sum(
                o.quality != "observed" for o in self.observations.values()
            ),
            "decisions": [asdict(d) for d in self.decisions[:20]],
            "decision_count": len(self.decisions),
            "unknown_zone_demands": sum(
                d.demand == "unknown" for d in self.zone_demands.values()
            ),
        }
