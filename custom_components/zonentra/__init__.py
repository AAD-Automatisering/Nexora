"""Zonentra — read-only intelligent building management foundation.

Entry layout (0.6, like Versatile Thermostat): one central configuration entry
owns the building runtime; each zone entry adds a room. Zone entries never
calculate anything themselves: their sensors read the central runtime. The
pre-0.6 single entry ("legacy") keeps working, is deprecated and raises a
repair issue asking to recreate it as central configuration plus zones.
"""

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_STATE_REPORTED, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .migration import migrate_options
from .models import build_model
from .runtime import BuildingRuntime
from .topology import CENTRAL, ENTRY_TYPE, ZONE, assemble

ZonentraConfigEntry = ConfigEntry[BuildingRuntime]
PLATFORMS = [Platform.SENSOR]
CENTRAL_PLATFORMS = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]
# 0.9: every zone gets a Zonentra thermostat, like Versatile Thermostat.
ZONE_PLATFORMS = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


def platforms(entry: ConfigEntry) -> list[Platform]:
    return {CENTRAL: CENTRAL_PLATFORMS, ZONE: ZONE_PLATFORMS}.get(
        entry_type(entry), PLATFORMS
    )


async def _thermostat_state(hass: HomeAssistant, entry: ConfigEntry):
    """Store and in-memory copy of the room thermostats of one central entry.

    The copy lives in hass.data so a central reload (for example after a zone
    change) never loses a just-made change that is still being written.
    """
    data = hass.data.setdefault(DOMAIN, {})
    stores = data.setdefault("thermostat_stores", {})
    caches = data.setdefault("thermostats", {})
    if entry.entry_id not in stores:
        stores[entry.entry_id] = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.thermostats"
        )
    if entry.entry_id not in caches:
        stored = await stores[entry.entry_id].async_load()
        caches[entry.entry_id] = dict((stored or {}).get("zones") or {})
    return stores[entry.entry_id], caches[entry.entry_id]


def entry_type(entry: ConfigEntry) -> str:
    return entry.data.get(ENTRY_TYPE, "legacy")


def central_entry(hass: HomeAssistant) -> ConfigEntry | None:
    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry_type(entry) == CENTRAL
        ),
        None,
    )


def central_device_entry(hass: HomeAssistant, central: ConfigEntry):
    """The central device, looked up within its own config entry."""
    return next(
        (
            device
            for device in dr.async_entries_for_config_entry(
                dr.async_get(hass), central.entry_id
            )
            if (DOMAIN, central.entry_id) in device.identifiers
        ),
        None,
    )


def zone_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry_type(entry) == ZONE and entry.disabled_by is None
    ]


def central_topology(
    hass: HomeAssistant, central: ConfigEntry, options: dict | None = None
) -> dict:
    return assemble(
        dict(central.options if options is None else options),
        [dict(entry.options) for entry in zone_entries(hass)],
    )


async def async_setup_entry(hass: HomeAssistant, entry: ZonentraConfigEntry) -> bool:
    """Set up a central, zone or legacy entry."""
    kind = entry_type(entry)
    if kind == ZONE:
        return await _async_setup_zone(hass, entry)
    try:
        topology = (
            central_topology(hass, entry) if kind == CENTRAL else dict(entry.options)
        )
        building = build_model(entry.entry_id, entry.data["name"], topology)
    except (ValueError, KeyError, TypeError) as err:
        raise ConfigEntryError("Invalid Zonentra topology") from err
    if kind == "legacy":
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"legacy_configuration_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="legacy_configuration",
            translation_placeholders={"name": entry.title},
        )
    registry = er.async_get(hass)
    for entity_id in building.entity_ids:
        source = registry.async_get(entity_id)
        if source and source.platform == DOMAIN:
            raise ConfigEntryError(
                "Zonentra diagnostic entities cannot be source inputs"
            )
    runtime = entry.runtime_data = BuildingRuntime(
        hass, building, active=kind == CENTRAL
    )
    if kind == CENTRAL:
        # The last applied outdoor-stand per group survives restarts.
        runtime.mode_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.mode_control")
        runtime.load_presets(await runtime.mode_store.async_load())
        store, cache = await _thermostat_state(hass, entry)
        runtime.thermostat_store, runtime.thermostat_cache = store, cache
        runtime.load_thermostats({"zones": cache})
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
    await hass.config_entries.async_forward_entry_setups(entry, platforms(entry))
    return True


async def _async_setup_zone(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """A zone attaches to the loaded central runtime; it owns no listeners."""
    central = central_entry(hass)
    if central is None:
        raise ConfigEntryError("Create the Zonentra central configuration first")
    if central.state is not ConfigEntryState.LOADED:
        raise ConfigEntryNotReady("Waiting for the Zonentra central configuration")
    if entry.options.get("id") not in {
        zone.id for zone in central.runtime_data.building.zones
    }:
        # A newly created zone: let the central runtime include it.
        hass.config_entries.async_schedule_reload(central.entry_id)
    # The zone device hangs below the central device (via_device_id).
    devices = dr.async_get(hass)
    central_device = central_device_entry(hass, central)
    devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Zonentra",
        model="Zone",
        via_device_id=central_device.id if central_device else None,
    )
    entry.async_on_unload(entry.add_update_listener(_async_zone_updated))
    await hass.config_entries.async_forward_entry_setups(entry, ZONE_PLATFORMS)
    return True


async def _async_zone_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Zone options changed: rebuild the building, then the zone's entities."""
    if central := central_entry(hass):
        await hass.config_entries.async_reload(central.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ZonentraConfigEntry) -> bool:
    """Unload diagnostic entities; HA removes entry callbacks on success."""
    return await hass.config_entries.async_unload_platforms(entry, platforms(entry))


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """A removed zone leaves the building; a removed legacy entry its issue."""
    kind = entry_type(entry)
    if kind == ZONE:
        central = central_entry(hass)
        if central and central.state is ConfigEntryState.LOADED:
            hass.config_entries.async_schedule_reload(central.entry_id)
    elif kind == CENTRAL:
        data = hass.data.get(DOMAIN, {})
        data.get("thermostats", {}).pop(entry.entry_id, None)
        if store := data.get("thermostat_stores", {}).pop(entry.entry_id, None):
            await store.async_remove()
    elif kind == "legacy":
        ir.async_delete_issue(hass, DOMAIN, f"legacy_configuration_{entry.entry_id}")


async def async_migrate_entry(hass: HomeAssistant, entry: ZonentraConfigEntry) -> bool:
    """Upgrade 0.1/0.2 config entries without changing room policy or identities."""
    if entry.version > 3:
        return False
    if entry.version < 3:
        hass.config_entries.async_update_entry(
            entry, options=migrate_options(dict(entry.options)), version=3
        )
    return True
