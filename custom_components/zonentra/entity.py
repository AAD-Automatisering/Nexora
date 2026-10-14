"""Shared plumbing for zone-device entities that read the central runtime."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from . import central_entry
from .const import DOMAIN


def zone_context(hass, entry) -> dict:
    """Provider of the central runtime, its update signal and the zone device."""
    central = central_entry(hass)

    def provider():
        # The central runtime already notifies while its setup is in progress.
        if central and central.state in (
            ConfigEntryState.LOADED,
            ConfigEntryState.SETUP_IN_PROGRESS,
        ):
            return getattr(central, "runtime_data", None)
        return None

    return {
        "provider": provider,
        "signal": f"{DOMAIN}_{central.entry_id}_updated",
        "device": DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Zonentra",
            model="Zone",
        ),
    }


class ZoneEntity(Entity):
    """A zone thermostat control: state lives in the central runtime."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry, provider, signal, device) -> None:
        self._entry = entry
        self._zone_id = entry.options["id"]
        self._provider = provider
        self._signal = signal
        self._attr_device_info = device

    @property
    def runtime(self):
        return self._provider()

    @property
    def available(self) -> bool:
        runtime = self.runtime
        return runtime is not None and self._zone_id in runtime.zone_demands

    @property
    def thermostat(self):
        return self.runtime.thermostat(self._zone_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._updated)
        )

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()

    def _change(self, **changes) -> None:
        runtime = self.runtime
        if runtime is None or self._zone_id not in runtime.zone_demands:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="zone_not_loaded"
            )
        try:
            runtime.set_thermostat(self._zone_id, **changes)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=str(err)
            ) from err
