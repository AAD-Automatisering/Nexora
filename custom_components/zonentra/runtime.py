"""Event-driven read-only bridge from HA states to pure building models."""

import logging
from dataclasses import asdict
from datetime import timedelta

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .control import plan
from .decision import Observation, simulate
from .demand import calculate_demand, collect_zone
from .engine import GroupMemory, evaluate, observe_mode
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

_LOGGER = logging.getLogger(__name__)


class BuildingRuntime:
    """Own one building's observations; no service or hardware access."""

    def __init__(self, hass: HomeAssistant, building: Building) -> None:
        self.hass = hass
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
        self.zone_snapshots = {
            zone.id: collect_zone(
                self.building, zone, sources, now, self.outdoor_temperature
            )
            for zone in self.building.zones
        }
        self.zone_demands = {
            zone.id: calculate_demand(
                zone,
                self.zone_snapshots[zone.id],
                self.zone_demands[zone.id].demand
                if zone.id in self.zone_demands
                else "unknown",
            )
            for zone in self.building.zones
        }
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
        future = [deadline for deadline in deadlines if deadline > now]
        if future:
            self._cancel_deadline = async_track_point_in_utc_time(
                self.hass, self.refresh, min(future)
            )
        async_dispatcher_send(self.hass, self.signal)

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
            transitions[item.id] = classify_transition(
                old_value,
                new_value,
                old_present=old is not None,
                trusted=new is not None
                and not (
                    new.attributes.get("restored")
                    or new.attributes.get("assumed_state")
                ),
                zonentra_initiated=initiated,
            )
            self.last_transitions[item.id] = (transitions[item.id], now)
        return transitions

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
