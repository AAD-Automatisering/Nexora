"""Zonentra — read-only intelligent building management foundation."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_REPORTED, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .models import build_model
from .runtime import BuildingRuntime

ZonentraConfigEntry = ConfigEntry[BuildingRuntime]
PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ZonentraConfigEntry) -> bool:
    """Load topology, subscribe to inputs and create diagnostic entities."""
    try:
        building = build_model(entry.entry_id, entry.data["name"], dict(entry.options))
    except (ValueError, KeyError, TypeError) as err:
        raise ConfigEntryError("Invalid Zonentra topology") from err
    registry = er.async_get(hass)
    for entity_id in building.entity_ids:
        source = registry.async_get(entity_id)
        if source and source.platform == "zonentra":
            raise ConfigEntryError(
                "Zonentra diagnostic entities cannot be source inputs"
            )
    runtime = entry.runtime_data = BuildingRuntime(hass, building)
    tracked_entity_ids = building.entity_ids
    if tracked_entity_ids:
        entry.async_on_unload(
            async_track_state_change_event(hass, tracked_entity_ids, runtime.refresh)
        )

        # Unchanged-value reports refresh freshness too. HA requires a filter.
        @callback
        def reported_filter(data):
            return data["entity_id"] in tracked_entity_ids

        entry.async_on_unload(
            hass.bus.async_listen(
                EVENT_STATE_REPORTED, runtime.refresh, event_filter=reported_filter
            )
        )
    entry.async_on_unload(runtime.close)
    runtime.refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZonentraConfigEntry) -> bool:
    """Unload diagnostic entities; HA removes entry callbacks on success."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
