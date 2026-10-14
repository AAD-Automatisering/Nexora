"""Climate limits as settings on the devices (0.9 / 0.10), like VTherm presets.

* Central device: the building's comfort, eco and away limits. They are kept
  in the central configuration and applied without reloading.
* Zone device: the room's own comfort, eco and away limits. Until one is set,
  the central value applies; "Use central limits" (button) clears them.
"""

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from . import central_topology
from .const import DOMAIN
from .entity import ZoneEntity, zone_context
from .models import build_model
from .topology import ENTRY_TYPE, ZONE

LIMIT_KEYS = (
    "heating_limit",
    "cooling_limit",
    "eco_heating_limit",
    "eco_cooling_limit",
    "away_heating_limit",
    "away_cooling_limit",
)
PAIR = {
    "heating_limit": "cooling_limit",
    "cooling_limit": "heating_limit",
    "eco_heating_limit": "eco_cooling_limit",
    "eco_cooling_limit": "eco_heating_limit",
    "away_heating_limit": "away_cooling_limit",
    "away_cooling_limit": "away_heating_limit",
}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    if entry.data.get(ENTRY_TYPE) == ZONE:
        context = zone_context(hass, entry)
        async_add_entities(ZoneLimitNumber(entry, key, **context) for key in LIMIT_KEYS)
        return
    async_add_entities(CentralLimitNumber(entry, key) for key in LIMIT_KEYS)


class LimitNumber(NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 5
    _attr_native_max_value = 35
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX


class CentralLimitNumber(LimitNumber):
    """A building-wide limit on the central device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, key) -> None:
        self._entry = entry
        self._key = key
        self._attr_translation_key = f"central_{key}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data["name"],
            manufacturer="Zonentra",
        )

    @property
    def native_value(self) -> float | None:
        return getattr(self._entry.runtime_data.building.settings, self._key)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{DOMAIN}_{self._entry.entry_id}_updated", self._updated
            )
        )

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        entry = self._entry
        options = dict(entry.options)
        building = {**options.get("building", {}), self._key: value}
        options["building"] = building
        try:
            model = build_model(
                entry.entry_id,
                entry.data["name"],
                central_topology(self.hass, entry, options),
            )
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=str(err)
            ) from err
        # No reload: the runtime takes the new building model directly.
        self.hass.config_entries.async_update_entry(entry, options=options)
        entry.runtime_data.apply_building(model)


class ZoneLimitNumber(ZoneEntity, LimitNumber):
    """The room's own limit; shows the central value until one is set."""

    def __init__(self, entry, key, provider, signal, device) -> None:
        super().__init__(entry, provider, signal, device)
        self._key = key
        comfort = key in ("heating_limit", "cooling_limit")
        self._attr_translation_key = f"comfort_{key}" if comfort else key
        self._attr_unique_id = (
            f"{entry.entry_id}_comfort_{key}"
            if key in ("heating_limit", "cooling_limit")
            else f"{entry.entry_id}_{key}"
        )

    @property
    def native_value(self) -> float | None:
        runtime = self.runtime
        if self._key in ("heating_limit", "cooling_limit"):
            index = 0 if self._key == "heating_limit" else 1
            return runtime.comfort[self._zone_id][index].value
        own = getattr(self.thermostat, self._key)
        if own is not None:
            return own
        zone = next(z for z in runtime.building.zones if z.id == self._zone_id)
        return getattr(zone, self._key)

    @property
    def extra_state_attributes(self) -> dict:
        thermostat = self.thermostat
        own = (
            thermostat.has_band
            if self._key in ("heating_limit", "cooling_limit")
            else getattr(thermostat, self._key) is not None
        )
        return {"source": "zone" if own else "central"}

    async def async_set_native_value(self, value: float) -> None:
        if self._key in ("heating_limit", "cooling_limit"):
            heating, cooling = (
                reading.value for reading in self.runtime.comfort[self._zone_id]
            )
            band = {"heating_limit": heating, "cooling_limit": cooling}
            band[self._key] = value
            if band["heating_limit"] is None or band["cooling_limit"] is None:
                # No band yet: open one 2 °C wide around the first value set.
                other = PAIR[self._key]
                band[other] = value + (2 if other == "cooling_limit" else -2)
            self._change(**band)
            return
        self._change(**{self._key: value})
