"""Switches for ACTIVE control.

* Central device, per outdoor unit group: active outdoor-stand (mode) control
  (0.7). On by default (as decided for this installation). Turning it off
  stops every command for that group immediately; the plan stays visible as
  simulation. The state is restored after a restart; until then no command is
  sent.
* Zone device: room regulation (0.9). Off by default: the room is only
  simulated. On, Zonentra switches the room's indoor units on and off and
  steers their setpoints. Stored with the room thermostat.
* Zone device: window bypass (0.10): an open window is ignored.
"""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import ZoneEntity, zone_context
from .topology import ENTRY_TYPE, ZONE


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    if entry.data.get(ENTRY_TYPE) == ZONE:
        context = zone_context(hass, entry)
        async_add_entities(
            [
                RoomRegulationSwitch(entry, **context),
                WindowBypassSwitch(entry, **context),
            ]
        )
        return
    runtime = entry.runtime_data
    async_add_entities(
        ActiveModeControlSwitch(entry, group) for group in runtime.building.groups
    )


class ActiveModeControlSwitch(SwitchEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:hvac"
    _attr_translation_key = "active_mode_control"

    def __init__(self, entry, group):
        self._entry = entry
        self._group_id = group.id
        self._attr_translation_placeholders = {"group": group.name}
        self._attr_unique_id = f"{entry.entry_id}_group_{group.id}_active_mode_control"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data["name"],
            manufacturer="Zonentra",
        )
        self._attr_is_on = True

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        self._attr_is_on = last.state != "off" if last else True
        self._entry.runtime_data.set_mode_active(self._group_id, self._attr_is_on)

    async def async_turn_on(self, **kwargs) -> None:
        self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        self._set(False)

    def _set(self, value: bool) -> None:
        self._attr_is_on = value
        self.async_write_ha_state()
        self._entry.runtime_data.set_mode_active(self._group_id, value)


class RoomRegulationSwitch(ZoneEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:thermostat-auto"
    _attr_translation_key = "room_regulation"

    def __init__(self, entry, provider, signal, device) -> None:
        super().__init__(entry, provider, signal, device)
        self._attr_unique_id = f"{entry.entry_id}_room_regulation"

    @property
    def is_on(self) -> bool:
        return self.thermostat.regulation

    async def async_turn_on(self, **kwargs) -> None:
        self._change(regulation=True)

    async def async_turn_off(self, **kwargs) -> None:
        self._change(regulation=False)


class WindowBypassSwitch(ZoneEntity, SwitchEntity):
    """Ignore an open window in this room (like VTherm's window bypass)."""

    _attr_icon = "mdi:window-shutter-open"
    _attr_translation_key = "window_bypass"

    def __init__(self, entry, provider, signal, device) -> None:
        super().__init__(entry, provider, signal, device)
        self._attr_unique_id = f"{entry.entry_id}_window_bypass"

    @property
    def is_on(self) -> bool:
        return self.thermostat.window_bypass

    async def async_turn_on(self, **kwargs) -> None:
        self._change(window_bypass=True)

    async def async_turn_off(self, **kwargs) -> None:
        self._change(window_bypass=False)
