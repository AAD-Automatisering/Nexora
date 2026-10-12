"""Zonentra — read-only intelligent building management foundation."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
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
    runtime = entry.runtime_data = BuildingRuntime(hass, building)
    if building.entity_ids:
        entry.async_on_unload(
            async_track_state_change_event(hass, building.entity_ids, runtime.refresh)
        )
    runtime.refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZonentraConfigEntry) -> bool:
    """Unload diagnostic entities; HA removes entry callbacks on success."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
