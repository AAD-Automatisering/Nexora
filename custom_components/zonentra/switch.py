"""Per outdoor unit group: switch for ACTIVE outdoor-stand (mode) control.

On by default (as decided for this installation). Turning it off stops every
command for that group immediately; the plan stays visible as simulation. The
state is restored after a restart; until then no command is sent.
"""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities) -> None:
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
