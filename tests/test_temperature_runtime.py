"""Temperature boundaries exercised through actual HA climate services."""

import pytest
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.setup import async_setup_component
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM

from tests.test_entry_layout import CELSIUS, add_zone, setup_central, zone_options

C = UnitOfTemperature.CELSIUS
F = UnitOfTemperature.FAHRENHEIT


class ReportingClimate(ClimateEntity):
    _attr_should_poll = False
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_name = "Source AC"

    def __init__(self, native_unit, step, minimum, maximum):
        self.entity_id = "climate.source_ac"
        self._attr_temperature_unit = native_unit
        self._attr_target_temperature_step = step
        self._attr_min_temp = minimum
        self._attr_max_temp = maximum
        self._attr_current_temperature = 20 if native_unit == C else 68
        self._attr_target_temperature = self._attr_current_temperature
        self.received = []

    async def async_set_temperature(self, **kwargs):
        self.received.append(kwargs["temperature"])
        self._attr_target_temperature = kwargs["temperature"]
        self.async_write_ha_state()


@pytest.mark.parametrize(
    "system", [METRIC_SYSTEM, US_CUSTOMARY_SYSTEM], ids=["system_C", "system_F"]
)
@pytest.mark.parametrize(
    ("native_unit", "step", "minimum", "maximum", "expected"),
    [
        (C, 0.5, 16, 30, 24.5),
        (F, 1, 60, 86, 76),
        (F, 5, 60, 86, 75),
        (F, 1, 60, 72, 72),
        (F, 1, 78.1, 86, 78.1),
    ],
)
async def test_regulation_converts_steps_bounds_service_and_confirmation(
    hass, system, native_unit, step, minimum, maximum, expected
):
    hass.config.units = system
    assert await async_setup_component(hass, "climate", {})
    source = ReportingClimate(native_unit, step, minimum, maximum)
    component = hass.data[DATA_INSTANCES]["climate"]
    await component.async_add_entities([source])
    await hass.async_block_till_done()
    hass.states.async_set("sensor.west_temperature", "20", CELSIUS)
    central = await setup_central(hass)
    await add_zone(hass, zone_options("west", source.entity_id))
    runtime = central.runtime_data
    runtime.set_thermostat("west", regulation=True)
    await hass.async_block_till_done()
    assert source.received == [pytest.approx(expected, abs=0.00001)]
    equipment_id = "hvac_source_ac"
    assert runtime.last_transitions[equipment_id][0] == "zonentra_setpoint"
    assert not runtime.setpoint_tracker.pending
    assert not runtime.overrides
    runtime.refresh()
    await hass.async_block_till_done()
    assert len(source.received) == 1
    assert runtime.setpoint_plans[equipment_id].status == "in_sync"
