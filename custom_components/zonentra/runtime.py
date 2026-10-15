"""Event-driven read-only bridge from HA states to pure building models."""

import logging
from dataclasses import asdict, replace
from datetime import timedelta

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_utc_time,
)
from homeassistant.util import dt as dt_util

from .control import plan
from .decision import Observation, simulate
from .demand import ZoneDemand, calculate_demand, collect_zone, comfort_limits
from .engine import GroupMemory, evaluate, observe_mode
from .executor import (
    ModeCommand,
    PresetMemory,
    next_correction_check,
    plan_mode_commands,
)
from .forecast import (
    REFRESH_MINUTES,
    RETRY_SECONDS,
    Forecast,
    day_type,
    demand_margins,
    summarize_forecast,
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
from .roomstate import (
    AUTO_FAN,
    Trend,
    auto_fan,
    fan_speeds,
    safety_state,
    update_trend,
    vane_command,
    vane_mode,
    window_state,
)
from .shading import (
    MIN_STEP,
    ScreenDecision,
    ScreenMove,
    SunMemory,
    decide_screen,
    plan_screen_move,
    sun_on_facade,
    sunny_state,
)
from .thermostat import (
    CLEAR_MANUAL,
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


def _cover_position(state) -> float | None:
    """A cover's position: 100 open, 0 closed (state only as a fallback)."""
    if state is None:
        return None
    position = state.attributes.get("current_position")
    if isinstance(position, (int, float)) and not isinstance(position, bool):
        return float(position)
    return {"open": 100.0, "closed": 0.0}.get(state.state)


def _power(source) -> float | None:
    """Solar power in W (kW is converted); None when not usable."""
    if source is None or not source.trustworthy:
        return None
    try:
        value = float(source.state)
    except TypeError, ValueError:
        return None
    return value * 1000 if source.unit == "kW" else value


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
        self._setpoint_checks: list = []
        self.mode_applied: dict[str, str] = {}  # dry / fan_only set per unit
        self.fan_applied: dict[str, str] = {}  # fan speed sent per unit
        # 0.10 room state (like VTherm's sensors): window, safety, trend, fan.
        self.windows: dict[str, str] = {}
        self.safety: dict[str, tuple[str, str]] = {}
        self.trends: dict[str, Trend] = {}
        self.auto_fans: dict[str, str | None] = {}
        self.fan_sent_at: dict = {}
        self._window_checks: list = []
        self._manual_checks: list = []
        self.vane_applied: dict[str, str] = {}  # zone -> heat / cool position set
        # 0.11 screens: sunshine memory, decisions, moves and manual overrides.
        self.sun_memory = SunMemory()
        self.sunny: bool | None = None
        self.sun_power: float | None = None
        self.screen_decisions: dict[str, ScreenDecision] = {}
        self.screen_moves: dict[str, ScreenMove] = {}
        self.screen_overrides: dict = {}  # equipment -> until
        self.screen_last_move: dict = {}
        self.cover_tracker = CommandTracker(confirmation_seconds=240)
        self._screen_checks: list = []
        # 0.12 weather forecast of the coming hours: warm / neutral / cold day.
        self.forecast: Forecast | None = None
        self.forecast_error: str | None = None
        self.day_type = "unknown"
        self._cancel_forecast_retry = None
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
        bands, comfort, manual, manual_checks = {}, {}, {}, []
        for zone in self.building.zones:
            thermostat = self.thermostat(zone.id)
            bands[zone.id] = active_band(
                thermostat.preset, self.zone_occupancy[zone.id]
            )
            until = self.manual_until(zone.id)
            if thermostat.manual and (
                thermostat.manual_band != bands[zone.id][0]
                or until is None
                or now >= until
            ):
                # Temporary, like a manual override at the room controller:
                # it ends after the override time, or when the band changes
                # (presence, motion).
                thermostat = replace(thermostat, **CLEAR_MANUAL)
                self.thermostats[zone.id] = thermostat
                self._save_thermostats()
            elif thermostat.manual:
                manual_checks.append(until)
            band = (thermostat.heating_limit, thermostat.cooling_limit)
            comfort[zone.id] = band if thermostat.has_band else None
            if thermostat.manual:
                manual[zone.id] = (
                    thermostat.manual_heating_limit,
                    thermostat.manual_cooling_limit,
                )
        self.zone_bands = bands
        self._manual_checks = manual_checks
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
                "comfort" if zone.id in manual else bands[zone.id][0],
                manual.get(zone.id, comfort[zone.id]),
                self.thermostat(zone.id).bands,
            )
            for zone in self.building.zones
        }
        self._room_state(now)
        settings = self.building.settings
        self.day_type = (
            day_type(
                self.forecast,
                now,
                settings.warm_day_temperature,
                settings.cold_day_temperature,
            )
            if settings.weather_entity
            else "unknown"
        )
        heating_margin, cooling_margin = demand_margins(
            self.day_type, settings.forecast_margin
        )
        demands = {}
        for zone in self.building.zones:
            demand = calculate_demand(
                zone,
                self.zone_snapshots[zone.id],
                self.zone_demands[zone.id].demand
                if zone.id in self.zone_demands
                else "unknown",
                heating_margin,
                cooling_margin,
            )
            # Thermostat mode: off asks nothing, heat/cool only one direction.
            demand = room_demand(self.thermostat(zone.id).hvac_mode, demand)
            if self.windows[zone.id] == "open" and demand.demand != "unknown":
                # An open window: the room asks for nothing (like VTherm).
                demand = ZoneDemand(
                    zone.id, "neutral", 0.0, 0.0, "window_open", demand.sensor_health
                )
            demands[zone.id] = demand
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
        deadlines.extend(self._window_checks)
        deadlines.extend(self._manual_checks)
        deadlines.extend(self._screen_checks)
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

    def _room_state(self, now) -> None:
        """Window, safety and temperature trend per zone (0.10)."""
        settings = self.building.settings
        checks = []
        for zone in self.building.zones:
            snapshot = self.zone_snapshots[zone.id]
            state, check = window_state(
                snapshot.contacts,
                settings.window_delay_seconds,
                self.thermostat(zone.id).window_bypass,
                now,
            )
            self.windows[zone.id] = state
            if check:
                checks.append(check)
            self.safety[zone.id] = safety_state(snapshot.temperature)
            reading = snapshot.temperature
            if reading.quality == "valid" and isinstance(reading.value, (int, float)):
                trend = update_trend(
                    self.trends.get(zone.id),
                    float(reading.value),
                    reading.reported_at or now,
                    now,
                )
                if trend is not None:
                    self.trends[zone.id] = trend
        self._window_checks = checks

    async def async_update_forecast(self, _now=None) -> None:
        """Fetch the hourly forecast of the coming hours (0.12), then refresh."""
        entity = self.building.settings.weather_entity
        if not entity:
            self.forecast = None
            return
        now = dt_util.utcnow()
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, ValueError) as err:
            # Weather not loaded yet or no hourly forecast: keep the last one
            # until it is too old; the next attempt follows on the interval.
            self.forecast_error = type(err).__name__
            _LOGGER.debug("Weather forecast of %s unavailable: %s", entity, err)
            if self.forecast is None and self._cancel_forecast_retry is None:
                # At startup the weather integration may not be loaded yet.
                self._cancel_forecast_retry = async_call_later(
                    self.hass, RETRY_SECONDS, self._retry_forecast
                )
        else:
            entries = ((response or {}).get(entity) or {}).get("forecast") or []
            self.forecast = summarize_forecast(entries, now)
            self.forecast_error = None if entries else "empty_forecast"
        self.refresh()

    async def _retry_forecast(self, _now=None) -> None:
        self._cancel_forecast_retry = None
        await self.async_update_forecast()

    @property
    def forecast_interval(self) -> timedelta:
        return timedelta(minutes=REFRESH_MINUTES)

    @callback
    def apply_building(self, building: Building) -> None:
        """New limits set on the central device: same inputs, no reload."""
        self.building = building
        self.refresh()

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
        if changes.get("manual_band") is not None:
            # A manual target is temporary: as long as a manual override.
            minutes = self.building.settings.manual_override_duration_minutes
            changes["manual_until"] = (
                dt_util.utcnow() + timedelta(minutes=minutes)
            ).isoformat()
        new = update_thermostat(self.thermostat(zone_id), zone.hysteresis, **changes)
        settings = self.building.settings
        for band in ("eco", "away"):
            # The room's eco/away band with the central value for unset limits.
            heat, cool = (
                getattr(new, key)
                if getattr(new, key) is not None
                else getattr(zone, key)
                if getattr(zone, key) is not None
                else getattr(settings, key)
                for key in (f"{band}_heating_limit", f"{band}_cooling_limit")
            )
            if heat + 2 * zone.hysteresis >= cool:
                raise ValueError("invalid_limits")
        self.thermostats[zone_id] = new
        self._save_thermostats()
        self.refresh()
        return new

    def manual_until(self, zone_id: str):
        value = self.thermostat(zone_id).manual_until
        return dt_util.parse_datetime(value) if value else None

    def _save_thermostats(self) -> None:
        if self.thermostat_cache is not None:
            for key, value in self.thermostats.items():
                self.thermostat_cache[key] = value.as_dict()
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
            if self.windows.get(item.zone_id) == "open" and enabled:
                # Open window: running units go off at once (no minimum run
                # time), nothing starts until it closes.
                running = unit is not None and unit.selected_mode not in (
                    "off",
                    "unknown",
                )
                if running and not unit_busy:
                    control = RoomUnitControl(
                        item.id,
                        "turn_off",
                        ModeCommand(
                            item.id, item.entity_id, "turn_off", None, 0, "window_open"
                        ),
                    )
                else:
                    control = RoomUnitControl(item.id, "window_open")
            elif thermostat.hvac_mode in UNIT_MODES:
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
                if check := self._fan(item, unit, thermostat, now, available):
                    checks.append(check)
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

    def _vanes(self, now) -> None:
        """Vane up when the room's units cool, down when they heat (0.10).

        Set once per start or mode change; a vane moved by hand afterwards is
        not fought. Works with the outdoor-stand control, also without room
        regulation, because it only follows what the units already do.
        """
        for zone in self.building.zones:
            if not zone.vane_entity:
                continue
            units = [
                item
                for item in self.building.equipment
                if item.kind == "hvac" and item.zone_id == zone.id
            ]
            modes = {
                unit.selected_mode
                for item in units
                if (unit := self.indoor_units.get(item.id)) and unit.available
            }
            mode = vane_mode(modes)
            if mode is None:
                self.vane_applied.pop(zone.id, None)  # Off: set again on start.
                continue
            if self.vane_applied.get(zone.id) == mode:
                continue
            command = vane_command(
                zone.vane_entity, mode, zone.vane_cool_value, zone.vane_heat_value
            )
            if command is None:
                continue
            domain, service, data = command
            if not self.hass.services.has_service(domain, service):
                continue
            self.vane_applied[zone.id] = mode
            entry = self._log(
                ModeCommand(
                    units[0].id if units else zone.id,
                    zone.vane_entity,
                    service,
                    None,
                    0,
                    f"vane_{mode}",
                    domain=domain,
                    value=data.get("option", data.get("value", service)),
                ),
                now,
                "sending",
            )
            self.hass.async_create_task(self._call(service, data, entry, domain))

    # --- Screens (0.11) ---------------------------------------------------------

    def _screen_transition(self, entity_id, old, new, event, now) -> None:
        """A screen moved by a person (HA or room controller) is respected."""
        for item in self.building.equipment:
            if item.kind != "shading" or item.entity_id != entity_id:
                continue
            if new is None or new.state in ("opening", "closing", "unavailable"):
                return  # Wait for the end position.
            position = _cover_position(new)
            pending = next(
                (p for p in self.cover_tracker.pending if p.entity_id == entity_id),
                None,
            )
            if pending is not None and self.cover_tracker.is_pending(entity_id, now):
                expected = float(pending.expected_state)
                if position is not None and abs(position - expected) < MIN_STEP:
                    self.cover_tracker.confirm(entity_id, pending.expected_state, now)
                    self.last_transitions[item.id] = ("zonentra_screen", now)
                return
            if old is None or (
                _cover_position(old) == position and old.state == new.state
            ):
                return
            if _origin(event) == "automation":
                self.last_transitions[item.id] = ("automation_screen", now)
                return
            minutes = self.building.settings.screen_override_minutes
            self.screen_overrides[item.id] = now + timedelta(minutes=minutes)
            self.last_transitions[item.id] = ("manual_screen", now)

    def _shading(self, sources, now) -> None:
        """Decide every screen; move it only with the room's screen regulation."""
        settings = self.building.settings
        checks = []
        self.sun_power = _power(sources.get(settings.sun_power_entity))
        if settings.sun_power_entity:
            self.sunny, self.sun_memory, check = sunny_state(
                self.sun_power, settings.sun_power_threshold, self.sun_memory, now
            )
            if check:
                checks.append(check)
        else:
            self.sunny = None
        sun = self.hass.states.get(settings.sun_entity)
        attributes = sun.attributes if sun else {}
        azimuth, elevation = attributes.get("azimuth"), attributes.get("elevation")
        block = sources.get(settings.screen_block_entity)
        blocked = block is not None and block.state == "on"
        available = self.hass.services.has_service("cover", "set_cover_position")
        zones = {zone.id: zone for zone in self.building.zones}
        decisions, moves = {}, {}
        for item in self.building.equipment:
            if item.kind != "shading":
                continue
            zone = zones[item.zone_id]
            snapshot = self.zone_snapshots[zone.id]
            previous = self.screen_decisions.get(item.id)
            decision = decide_screen(
                elevation=elevation,
                sunny=self.sunny,
                on_facade=sun_on_facade(azimuth, elevation, zone.facade),
                demand=self.zone_demands[zone.id].demand,
                room_temperature=snapshot.temperature.value
                if snapshot.temperature.quality == "valid"
                else None,
                heating_limit=snapshot.heating_limit.value,
                cooling_limit=snapshot.cooling_limit.value,
                shade_position=round(settings.screen_shade_position),
                previous=previous.target if previous else None,
                day=self.day_type,
                occupied=self.zone_bands[zone.id][0] == "comfort"
                or self.thermostat(zone.id).manual,
            )
            override = self.screen_overrides.get(item.id)
            if override is not None and now >= override:
                del self.screen_overrides[item.id]  # Manual time is over.
                override = None
            state = self.hass.states.get(item.entity_id)
            move = plan_screen_move(
                decision,
                _cover_position(state) if state else None,
                self.screen_last_move.get(item.id),
                now,
                enabled=self.active_capable
                and self.thermostat(zone.id).screen_regulation,
                blocked=blocked,
                override_until=override,
                busy=self.cover_tracker.is_pending(item.entity_id, now),
            )
            if move.status == "move" and not available:
                move = ScreenMove("cover_service_unavailable")
            if move.status == "move":
                self._move_screen(item, move.position, decision.reason, now)
            if move.next_check:
                checks.append(move.next_check)
            decisions[item.id], moves[item.id] = decision, move
        self.screen_decisions, self.screen_moves = decisions, moves
        self._screen_checks = checks

    def _move_screen(self, item, position, reason, now) -> None:
        self.screen_last_move[item.id] = now
        self.cover_tracker.register(item.entity_id, str(position), now)
        entry = self._log(
            ModeCommand(
                item.id,
                item.entity_id,
                "set_cover_position",
                None,
                0,
                f"screen_{reason}",
                domain="cover",
                value=position,
            ),
            now,
            "sending",
        )
        self.hass.async_create_task(
            self._call(
                "set_cover_position",
                {"entity_id": item.entity_id, "position": position},
                entry,
                "cover",
            )
        )

    def zone_auto_fan(self, zone_id: str) -> bool:
        """The thermostat runs Zonentra's automatic fan (units have no auto)."""
        return self.thermostat(zone_id).fan_mode == AUTO_FAN and (
            AUTO_FAN not in self.unit_options(zone_id)[1]
        )

    def _fan(self, item, unit, thermostat, now, available):
        """Pass the thermostat's fan speed to a running unit, once per change.

        With the automatic fan the speed follows the distance to the target,
        changed at most once per setpoint interval.
        """
        if thermostat.fan_mode is None:
            self.fan_applied.pop(item.id, None)
            return None
        state = self.hass.states.get(item.entity_id)
        supported = tuple((state.attributes.get("fan_modes") or ()) if state else ())
        desired = thermostat.fan_mode
        if self.zone_auto_fan(item.zone_id):
            snapshot = self.zone_snapshots[item.zone_id]
            zone = next(z for z in self.building.zones if z.id == item.zone_id)
            desired = auto_fan(
                fan_speeds(supported),
                unit.selected_mode,
                snapshot.temperature.value
                if snapshot.temperature.quality == "valid"
                else None,
                snapshot.heating_limit.value,
                snapshot.cooling_limit.value,
                zone.hysteresis,
            )
            self.auto_fans[item.zone_id] = desired
            last = self.fan_sent_at.get(item.id)
            interval = self.building.settings.setpoint_interval_seconds
            if last and (now - last).total_seconds() < interval:
                if desired != unit.fan_mode:
                    return last + timedelta(seconds=interval)
                return None
        fan = plan_fan(
            desired,
            unit.selected_mode,
            unit.fan_mode,
            self.fan_applied.get(item.id),
            supported,
        )
        if unit.fan_mode == desired:
            self.fan_applied[item.id] = desired
        if fan is None or not available:
            return None
        self.fan_applied[item.id] = fan
        self.fan_sent_at[item.id] = now
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
        self._vanes(now)
        self._shading(sources, now)

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
        if command.hvac_mode:
            data["hvac_mode"] = command.hvac_mode
        entry = self._log(command, now, "sending")
        self.hass.async_create_task(self._call(command.service, data, entry))

    async def _call(self, service, data, entry, domain="climate") -> None:
        try:
            await self.hass.services.async_call(
                domain, service, data, blocking=True, context=Context()
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
            "value": command.value,
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
        self._screen_transition(entity_id, old, new, event, now)
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
        """0.9: who changed a running unit's setpoint (attribute only).

        The room controllers of this installation only switch units on and
        off. A setpoint change with a bare context therefore comes from the
        unit or gateway itself (for example its own setpoint after switching
        on), not from a person: only a Home Assistant user counts as manual.
        """
        before = _setpoint(old.attributes.get("temperature"))
        after = _setpoint(new.attributes.get("temperature"))
        if before == after or after is None:
            return "attribute_update"
        if self.setpoint_tracker.confirm(entity_id, after, now):
            return "zonentra_setpoint"
        origin = _origin(event)
        if origin == "automation":
            return "automation_setpoint"
        if origin == "device":
            return "device_setpoint"
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
        if self._cancel_forecast_retry:
            self._cancel_forecast_retry()
            self._cancel_forecast_retry = None

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
            "sunny": self.sunny,
            "day_type": self.day_type,
            "forecast_maximum": self.forecast.maximum if self.forecast else None,
            "forecast_minimum": self.forecast.minimum if self.forecast else None,
            "sun_power": self.sun_power,
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
