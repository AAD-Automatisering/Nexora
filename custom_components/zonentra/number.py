"""Comfort band of a zone thermostat as settings on the zone device (0.9)."""

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import EntityCategory

from .entity import ZoneEntity, zone_context

LIMITS = (("heating_limit", 0), ("cooling_limit", 1))


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    context = zone_context(hass, entry)
    async_add_entities(
        ComfortLimitNumber(entry, key, index, **context) for key, index in LIMITS
    )


class ComfortLimitNumber(ZoneEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 5
    _attr_native_max_value = 35
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, entry, key, index, provider, signal, device) -> None:
        super().__init__(entry, provider, signal, device)
        self._key = key
        self._index = index
        self._attr_translation_key = f"comfort_{key}"
        self._attr_unique_id = f"{entry.entry_id}_comfort_{key}"

    @property
    def native_value(self) -> float | None:
        return self.runtime.comfort[self._zone_id][self._index].value

    async def async_set_native_value(self, value: float) -> None:
        heating, cooling = (
            reading.value for reading in self.runtime.comfort[self._zone_id]
        )
        band = {"heating_limit": heating, "cooling_limit": cooling, self._key: value}
        if band["heating_limit"] is None or band["cooling_limit"] is None:
            # No band yet: open one 2 °C wide around the first value set.
            other = "cooling_limit" if self._key == "heating_limit" else "heating_limit"
            band[other] = value + (2 if other == "cooling_limit" else -2)
        self._change(**band)
