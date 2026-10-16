"""Home Assistant command dispatch, final guards and command diagnostics."""

import logging

from homeassistant.const import UnitOfTemperature
from homeassistant.core import Context
from homeassistant.helpers.temperature import display_temp

from .runtime_helpers import _setpoint
from .temperature import convert_temperature

_LOGGER = logging.getLogger(__name__)


class CommandRuntimeMixin:
    """Dispatch controls through the owning building runtime."""

    def _execute(self, command, now, *, on_result=None) -> None:
        data = {"entity_id": command.entity_id}
        if command.domain != "climate":
            if command.service == "set_cover_position":
                data["position"] = command.value
            elif command.service == "select_option":
                data["option"] = command.value
            elif command.service == "set_value":
                data["value"] = command.value
        elif command.service == "set_fan_mode":
            data["fan_mode"] = command.fan_mode  # An attribute: nothing to track.
        elif command.service == "set_temperature":
            # HA interprets service temperatures in the configured system unit.
            temperature = convert_temperature(
                command.temperature,
                UnitOfTemperature.CELSIUS,
                self.hass.config.units.temperature_unit,
            )
            if temperature is None:
                self._log(command, now, "blocked: invalid_temperature")
                if on_result is not None:
                    self.hass.loop.call_soon(on_result, False)
                return
            entity = self._climate_entity(command.entity_id)
            if entity is not None:
                # Quantize and clamp in native units before the service's own
                # conversion. Rounding a converted boundary can fall just outside
                # the device's strict min/max checks.
                native = convert_temperature(
                    command.temperature,
                    UnitOfTemperature.CELSIUS,
                    entity.temperature_unit,
                )
                if native is not None:
                    step = convert_temperature(
                        entity.target_temperature_step,
                        entity.temperature_unit,
                        entity.temperature_unit,
                        interval=True,
                    )
                    if step is not None and step > 0:
                        native = round(native / step) * step
                    native = min(entity.max_temp, max(entity.min_temp, native))
                    temperature = convert_temperature(
                        native,
                        entity.temperature_unit,
                        self.hass.config.units.temperature_unit,
                    )
            data["temperature"] = (
                temperature if entity is not None else round(temperature, 6)
            )
            shown = (
                display_temp(
                    self.hass,
                    data["temperature"],
                    self.hass.config.units.temperature_unit,
                    entity.precision,
                )
                if entity is not None
                else data["temperature"]
            )
            expected = _setpoint(shown)
            self.setpoint_tracker.register(command.entity_id, expected, now)
        else:
            expected = (
                command.hvac_mode if command.service == "set_hvac_mode" else "off"
            )
            self.command_tracker.register(command.entity_id, expected, now)
        if command.hvac_mode:
            data["hvac_mode"] = command.hvac_mode
        entry = self._log(command, now, "sending")

        async def send():
            success = await self._call(command.service, data, entry, command.domain)
            if on_result is not None:
                self.hass.loop.call_soon(on_result, success)

        self.hass.async_create_task(send())

    async def _call(self, service, data, entry, domain="climate") -> bool:
        runtime = self._current_runtime()
        group_ids = {entry.get("group_id")}
        item = next(
            (
                item
                for item in runtime.building.equipment
                if item.id == entry.get("equipment_id")
            ),
            None,
        )
        if item is None:
            entry["result"] = "blocked: equipment_removed"
            return False
        if domain == "cover" and (guard := runtime._screen_guard(item)):
            entry["result"] = f"blocked: {guard}"
            return False
        group_ids.add(item.group_id)
        if entry.get("reason", "").startswith("vane_"):
            group_ids.update(
                unit.group_id
                for unit in runtime.building.equipment
                if unit.kind == "hvac" and unit.zone_id == item.zone_id
            )
        blocked = next(
            (
                reason
                for group_id in group_ids
                if (reason := runtime._group_block(group_id))
            ),
            None,
        )
        if blocked or runtime._closed:
            entry["result"] = f"blocked: {blocked or 'runtime_unloaded'}"
            return False
        try:
            await self.hass.services.async_call(
                domain, service, data, blocking=True, context=Context()
            )
        except Exception as err:  # noqa: BLE001 - report, never crash the runtime
            entry["result"] = f"failed: {type(err).__name__}"
            _LOGGER.warning("Zonentra %s on %s failed: %s", service, data, err)
            return False
        else:
            entry["result"] = "sent"
            return True

    def _log(self, command, now, result) -> dict:
        entry = {
            "at": now.isoformat(),
            "group_id": next(
                (
                    item.group_id
                    for item in self.building.equipment
                    if item.id == command.equipment_id
                ),
                None,
            ),
            "equipment_id": command.equipment_id,
            "entity_id": command.entity_id,
            "domain": command.domain,
            "service": command.service,
            "hvac_mode": command.hvac_mode,
            "temperature": command.temperature,
            "fan_mode": command.fan_mode,
            "value": command.value,
            "reason": command.reason,
            "result": result,
        }
        self.command_log = [*self.command_log, entry][-30:]
        _LOGGER.info("Zonentra mode control: %s", entry)
        return entry
