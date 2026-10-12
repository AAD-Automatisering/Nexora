"""Event-driven read-only bridge from HA states to pure building models."""

import logging
from dataclasses import asdict

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .decision import Observation, simulate
from .models import Building

_LOGGER = logging.getLogger(__name__)


class BuildingRuntime:
    """Own one building's observations; no service or hardware access."""

    def __init__(self, hass: HomeAssistant, building: Building) -> None:
        self.hass = hass
        self.building = building
        self.signal = f"nexora_{building.id}_updated"
        self.observations: dict[str, Observation] = {}
        self.decisions = ()

    @callback
    def refresh(self, event=None) -> None:
        """Refresh configured state values on an input event, without polling."""
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
        decisions = simulate(self.building, observations)
        if decisions != self.decisions:
            _LOGGER.debug(
                "Read-only simulation updated: %s", [d.reason for d in decisions]
            )
        self.observations = observations
        self.decisions = decisions
        async_dispatcher_send(self.hass, self.signal)

    @property
    def status(self) -> str:
        if any(d.reason == "observed_group_conflict" for d in self.decisions):
            return "conflict"
        if any(o.quality != "observed" for o in self.observations.values()):
            return "degraded"
        return "read_only"

    def summary(self) -> dict:
        """Return bounded metadata; do not expose alarm states or raw attributes."""
        return {
            "read_only": True,
            "zones": len(self.building.zones),
            "groups": len(self.building.groups),
            "equipment": len(self.building.equipment),
            "unavailable_inputs": sum(
                o.quality != "observed" for o in self.observations.values()
            ),
            "decisions": [asdict(d) for d in self.decisions],
        }
