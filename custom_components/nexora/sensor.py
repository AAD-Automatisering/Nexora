"""Read-only diagnostic status sensor."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from . import NexoraConfigEntry
from .const import DOMAIN


async def async_setup_entry(hass, entry: NexoraConfigEntry, async_add_entities) -> None:
    async_add_entities([NexoraStatusSensor(entry)])


class NexoraStatusSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:office-building-cog"

    def __init__(self, entry: NexoraConfigEntry) -> None:
        self.runtime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data["name"],
            manufacturer="Nexora",
        )

    @property
    def native_value(self):
        return self.runtime.status

    @property
    def extra_state_attributes(self):
        return self.runtime.summary()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.runtime.signal, self._updated)
        )

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()
