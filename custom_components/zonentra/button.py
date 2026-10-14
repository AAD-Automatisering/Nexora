"""Zone device: return to the central comfort, eco and away limits (0.10)."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import ZoneEntity, zone_context
from .thermostat import BAND_KEYS


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([UseCentralLimitsButton(entry, **zone_context(hass, entry))])


class UseCentralLimitsButton(ZoneEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:backup-restore"
    _attr_translation_key = "use_central_limits"

    def __init__(self, entry, provider, signal, device) -> None:
        super().__init__(entry, provider, signal, device)
        self._attr_unique_id = f"{entry.entry_id}_use_central_limits"

    async def async_press(self) -> None:
        self._change(
            heating_limit=None,
            cooling_limit=None,
            **dict.fromkeys(BAND_KEYS),
        )
