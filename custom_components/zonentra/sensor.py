"""Compact read-only diagnostics: one building, one zone and one group sensor."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from . import ZonentraConfigEntry
from .const import DOMAIN


async def async_setup_entry(
    hass, entry: ZonentraConfigEntry, async_add_entities
) -> None:
    runtime = entry.runtime_data
    entities = [ZonentraStatusSensor(entry)]
    entities.extend(ZoneDemandSensor(entry, zone) for zone in runtime.building.zones)
    entities.extend(GroupModeSensor(entry, group) for group in runtime.building.groups)
    # Options reload removes obsolete diagnostics; renames retain stable IDs.
    expected = {entity.unique_id for entity in entities}
    registry = er.async_get(hass)
    for record in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            record.platform == DOMAIN
            and record.domain == "sensor"
            and record.unique_id not in expected
        ):
            registry.async_remove(record.entity_id)
    async_add_entities(entities)


class ZonentraDiagnosticSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry):
        self.runtime = entry.runtime_data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data["name"],
            manufacturer="Zonentra",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.runtime.signal, self._updated)
        )

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()


class ZonentraStatusSensor(ZonentraDiagnosticSensor):
    _attr_name = "Status"
    _attr_icon = "mdi:office-building-cog"

    def __init__(self, entry):
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_status"

    @property
    def native_value(self):
        return self.runtime.status

    @property
    def extra_state_attributes(self):
        return self.runtime.summary()


class ZoneDemandSensor(ZonentraDiagnosticSensor):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["heating_demand", "cooling_demand", "neutral", "unknown"]
    _attr_icon = "mdi:home-thermometer-outline"
    _attr_translation_key = "zone_demand"

    def __init__(self, entry, zone):
        super().__init__(entry)
        self.zone = zone
        self._attr_translation_placeholders = {"zone": zone.name}
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone.id}_demand"

    @property
    def native_value(self):
        return self.runtime.zone_demands[self.zone.id].demand

    @property
    def extra_state_attributes(self):
        demand = self.runtime.zone_demands[self.zone.id]
        snapshot = self.runtime.zone_snapshots[self.zone.id]
        health = {
            field: getattr(snapshot, field).quality
            for field in (
                "temperature",
                "heating_limit",
                "cooling_limit",
                "humidity",
                "co2",
                "outdoor_temperature",
                "occupancy",
            )
        }
        return {
            "read_only": True,
            "heating_score": demand.heating_score,
            "cooling_score": demand.cooling_score,
            "temperature_c": snapshot.temperature.value,
            "heating_limit_c": snapshot.heating_limit.value,
            "cooling_limit_c": snapshot.cooling_limit.value,
            "weight": self.zone.weight,
            "hysteresis_c": self.zone.hysteresis,
            "reason": demand.reason,
            "sensor_health": demand.sensor_health,
            "source_health": health,
            "occupancy": snapshot.occupancy.value or "unknown",
            "open_contacts": sum(
                contact.value == "open" for contact in snapshot.contacts
            ),
            "unknown_contacts": sum(
                contact.quality != "valid" for contact in snapshot.contacts
            ),
        }


class GroupModeSensor(ZonentraDiagnosticSensor):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["heat", "cool", "off", "unknown"]
    _attr_icon = "mdi:heat-pump-outline"
    _attr_translation_key = "group_mode"

    def __init__(self, entry, group):
        super().__init__(entry)
        self.group = group
        self._attr_translation_placeholders = {"group": group.name}
        self._attr_unique_id = f"{entry.entry_id}_group_{group.id}_mode"

    @property
    def native_value(self):
        return self.runtime.group_decisions[self.group.id].proposed_mode

    @property
    def extra_state_attributes(self):
        decision = self.runtime.group_decisions[self.group.id]
        return {
            "read_only": True,
            "current_mode": decision.current_mode,
            "desired_mode": decision.desired_mode,
            "heating_score": decision.heating_score,
            "cooling_score": decision.cooling_score,
            "reason": decision.reason,
            "blocked_reason": decision.blocked_reason,
            "mode_change_proposed": decision.mode_change_proposed,
            "blocked_until": decision.blocked_until.isoformat()
            if decision.blocked_until
            else None,
            "member_zones": len(decision.member_zone_ids),
            "reliable_zones": decision.reliable_zones,
            "mode_quality": decision.mode_quality,
        }
