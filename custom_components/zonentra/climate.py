"""Zonentra thermostat per zone (0.9), like Versatile Thermostat.

* Standard Home Assistant modes: ``heat`` (target = heating limit; the room
  only asks for heating), ``cool`` (target = cooling limit; only cooling),
  ``heat_cool`` (target range = the comfort band; both) and ``off`` (the room
  asks for nothing). A mode never forces the outdoor unit: the group weighs
  all rooms, and a heat-only room waits while its group cools.
* Like the room's own indoor units (the thermostat replaces them in HomeKit and
  dashboards): when every unit offers ``auto``, the both-ways mode is shown
  as ``auto``; ``dry`` and ``fan_only`` and the fan speeds that every unit
  supports are offered too. With room regulation on, Zonentra runs the units
  in dry / fan_only and passes the fan speed on.
* Presets: ``comfort`` (presence and motion may lower it to eco/away) or a
  fixed eco / away. The thermostat shows the band that applies now: its
  preset becomes away when the building is absent and eco without motion, and
  its targets are that band's limits (the choice is kept as an attribute).
* Whether Zonentra really switches the room's indoor units is the separate
  "Room regulation" switch (off by default: simulation only).
"""

from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .entity import ZoneEntity, zone_context
from .roomstate import AUTO_FAN, fan_names, thermostat_fan
from .thermostat import PRESETS, UNIT_MODES, single_target

BASE_FEATURES = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
    | ClimateEntityFeature.PRESET_MODE
    | ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
)


def _zone_units(runtime, zone_id):
    return tuple(
        unit
        for item in runtime.building.equipment
        if item.zone_id == zone_id
        and item.kind == "hvac"
        and (unit := runtime.indoor_units.get(item.id))
        and unit.available
    )


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([ZonentraThermostat(entry, **zone_context(hass, entry))])


class ZonentraThermostat(ZoneEntity, ClimateEntity):
    _attr_name = None  # The thermostat carries the zone (device) name.
    _attr_translation_key = "thermostat"
    _attr_icon = "mdi:home-thermometer"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_preset_modes = list(PRESETS)
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_target_temperature_step = 0.5

    def __init__(self, entry, provider, signal, device) -> None:
        super().__init__(entry, provider, signal, device)
        self._attr_unique_id = f"{entry.entry_id}_thermostat"

    def _options(self) -> tuple[frozenset[str], tuple[str, ...]]:
        runtime = self.runtime
        if runtime is None:
            return frozenset(), ()
        return runtime.unit_options(self._zone_id)

    def _both(self, modes: frozenset[str]) -> HVACMode:
        """The both-ways mode under the name the room's units use."""
        if HVACMode.AUTO in modes and HVACMode.HEAT_COOL not in modes:
            return HVACMode.AUTO
        return HVACMode.HEAT_COOL

    @property
    def hvac_modes(self) -> list[HVACMode]:
        modes, _ = self._options()
        return [
            self._both(modes),
            HVACMode.HEAT,
            HVACMode.COOL,
            *(HVACMode(mode) for mode in UNIT_MODES if mode in modes),
            HVACMode.OFF,
        ]

    @property
    def hvac_mode(self) -> HVACMode:
        mode = self.thermostat.hvac_mode
        if mode == "heat_cool":
            return self._both(self._options()[0])
        return HVACMode(mode)

    @property
    def fan_modes(self) -> list[str] | None:
        if not self.thermostat.fan_control:
            return None  # 0.13.5: the fan is left to the room controller.
        return self._fan_modes()

    def _fan_modes(self) -> list[str] | None:
        """``auto`` plus the units' speeds under Home Assistant's standard
        names (low, middle, medium, high), so HomeKit shows a fan with a speed
        slider. ``auto`` is the units' own or Zonentra's automatic fan."""
        names = list(fan_names(self._options()[1]))
        return [AUTO_FAN, *names] if names else None

    @property
    def fan_mode(self) -> str | None:
        if not self.fan_modes:
            return None
        # 0.13.5: none chosen is the automatic fan.
        return thermostat_fan(
            self.runtime.fan_choice(self._zone_id), self._options()[1]
        )

    @property
    def supported_features(self) -> ClimateEntityFeature:
        if self.fan_modes:
            return BASE_FEATURES | ClimateEntityFeature.FAN_MODE
        return BASE_FEATURES

    @property
    def preset_mode(self) -> str:
        """The active band, also while a temporary manual target applies."""
        return self.runtime.zone_bands[self._zone_id][0]

    def _band(self) -> str:
        return self.runtime.zone_bands[self._zone_id][0]

    @property
    def current_temperature(self) -> float | None:
        return self.runtime.zone_snapshots[self._zone_id].temperature.value

    @property
    def current_humidity(self) -> float | None:
        return self.runtime.zone_snapshots[self._zone_id].humidity.value

    @property
    def target_temperature(self) -> float | None:
        """Single target in heat or cool mode: the limit that applies."""
        mode = self.thermostat.hvac_mode
        if mode == "heat":
            return self.target_temperature_low
        if mode == "cool":
            return self.target_temperature_high
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Heating limit of the band that applies now (comfort, eco, away)."""
        return self.runtime.zone_snapshots[self._zone_id].heating_limit.value

    @property
    def target_temperature_high(self) -> float | None:
        return self.runtime.zone_snapshots[self._zone_id].cooling_limit.value

    @property
    def hvac_action(self) -> HVACAction:
        mode = self.thermostat.hvac_mode
        if mode == "off":
            return HVACAction.OFF
        runtime = self.runtime
        units = _zone_units(runtime, self._zone_id)
        actions = {
            unit.reported_action
            if unit.activity is not None
            else {
                "heat": "heating",
                "cool": "cooling",
                "dry": "drying",
                "fan_only": "fan",
                "off": "off",
            }.get(unit.selected_mode, "idle")
            for unit in units
        }
        if actions & {"heating", "preheating", "defrosting"}:
            return HVACAction.HEATING
        if "cooling" in actions:
            return HVACAction.COOLING
        if "drying" in actions:
            return HVACAction.DRYING
        if "fan" in actions:
            return HVACAction.FAN
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict:
        runtime = self.runtime
        band, reason = runtime.zone_bands[self._zone_id]
        snapshot = runtime.zone_snapshots[self._zone_id]
        demand = runtime.zone_demands[self._zone_id]
        zone = next(z for z in runtime.building.zones if z.id == self._zone_id)
        thermostat = self.thermostat
        units = _zone_units(runtime, self._zone_id)
        reported = sum(unit.activity is not None for unit in units)
        return {
            "activity_source": (
                "thermostat_off"
                if thermostat.hvac_mode == "off"
                else "unavailable"
                if not units
                else "reported"
                if reported == len(units)
                else "mixed"
                if reported
                else "selected_mode"
            ),
            "active_band": band,
            "active_band_reason": reason,
            "chosen_preset": thermostat.preset,
            "manual": thermostat.manual,
            "manual_until": thermostat.manual_until,
            "fan_until": thermostat.fan_until,
            "comfort_heating_limit": runtime.comfort[self._zone_id][0].value,
            "comfort_cooling_limit": runtime.comfort[self._zone_id][1].value,
            "active_heating_limit": snapshot.heating_limit.value,
            "active_cooling_limit": snapshot.cooling_limit.value,
            "comfort_source": "building"
            if zone.use_building_limits
            else "thermostat"
            if thermostat.has_band
            else "zone",
            "zone_demand": demand.demand,
            "zone_demand_reason": demand.reason,
            "room_regulation": runtime.regulated(self._zone_id),
            "window": runtime.windows.get(self._zone_id),
            "safety": runtime.safety.get(self._zone_id, ("unknown",))[0],
        }

    async def async_set_temperature(self, **kwargs) -> None:
        changes = {}
        if hvac_mode := kwargs.get("hvac_mode"):
            changes["hvac_mode"] = self._stored(hvac_mode)
        mode = changes.get("hvac_mode", self.thermostat.hvac_mode)
        low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        if low is None and high is None and ATTR_TEMPERATURE in kwargs:
            # heat sets the heating limit, cool the cooling limit; in heat_cool
            # a single target is taken as the heating limit.
            zone = next(z for z in self.runtime.building.zones if z.id == self._zone_id)
            low, high = single_target(
                "cool" if mode == "cool" else "heat",
                kwargs[ATTR_TEMPERATURE],
                self.target_temperature_low,
                self.target_temperature_high,
                zone.hysteresis,
            )
        low = self.target_temperature_low if low is None else low
        high = self.target_temperature_high if high is None else high
        # A one-off manual deviation, not configuration (that is on the
        # device): it holds until a preset is chosen or the band changes.
        changes |= {
            "manual_heating_limit": low,
            "manual_cooling_limit": high,
            "manual_band": self._band(),
        }
        self._change(**changes)

    @staticmethod
    def _stored(hvac_mode) -> str:
        mode = str(hvac_mode)
        return "heat_cool" if mode == HVACMode.AUTO else mode

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._change(hvac_mode=self._stored(hvac_mode))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self._change(fan_mode=fan_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self._change(preset=preset_mode)

    async def async_turn_on(self) -> None:
        self._change(hvac_mode="heat_cool")

    async def async_turn_off(self) -> None:
        self._change(hvac_mode="off")
