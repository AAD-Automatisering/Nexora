"""Compact read-only diagnostics for the building, zones, indoor units and groups."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from . import ZonentraConfigEntry, central_entry, entry_type
from .const import DOMAIN
from .models import Equipment, Zone
from .observations import describe
from .topology import ZONE, zone_equipment


async def async_setup_entry(
    hass, entry: ZonentraConfigEntry, async_add_entities
) -> None:
    if entry_type(entry) == ZONE:
        entities = _zone_entities(hass, entry)
    else:
        entities = _building_entities(entry)
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


def _building_entities(entry) -> list:
    """Legacy entries keep every entity; central entries keep building/groups."""
    runtime = entry.runtime_data
    legacy = entry_type(entry) == "legacy"
    hvac = [item for item in runtime.building.equipment if item.kind == "hvac"]
    groups = runtime.building.groups
    entities = [ZonentraStatusSensor(entry)]
    if legacy:
        entities.extend(
            ZoneDemandSensor(entry, zone) for zone in runtime.building.zones
        )
    entities.extend(GroupModeSensor(entry, group) for group in groups)
    if legacy:
        entities.extend(IndoorUnitSensor(entry, item) for item in hvac)
    entities.extend(DerivedGroupModeSensor(entry, group) for group in groups)
    if legacy:
        entities.extend(UnitControlSensor(entry, item) for item in hvac)
    entities.extend(GroupCoordinationSensor(entry, group) for group in groups)
    return entities


def _zone_entities(hass, entry) -> list:
    """A zone device with its demand and indoor-unit sensors (central runtime)."""
    central = central_entry(hass)

    def provider():
        return (
            central.runtime_data
            if central and central.state is ConfigEntryState.LOADED
            else None
        )

    options = dict(entry.options)
    shared = {
        "provider": provider,
        "signal": f"{DOMAIN}_{central.entry_id}_updated",
        "device": DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Zonentra",
            model="Zone",
            via_device=(DOMAIN, central.entry_id),
        ),
    }
    entities = [
        ZoneDemandSensor(
            entry,
            Zone(options["id"], options.get("name", entry.title)),
            unique_id=f"{entry.entry_id}_demand",
            translation_key="room_demand",
            **shared,
        )
    ]
    for record in zone_equipment(options):
        if record["kind"] != "hvac":
            continue
        state = hass.states.get(record["entity_id"])
        item = Equipment(**{**record, "name": state.name if state else record["name"]})
        entities.append(
            IndoorUnitSensor(
                entry,
                item,
                unique_id=f"{entry.entry_id}_{item.id}_indoor_unit",
                **shared,
            )
        )
        entities.append(
            UnitControlSensor(
                entry, item, unique_id=f"{entry.entry_id}_{item.id}_control", **shared
            )
        )
    return entities


class ZonentraDiagnosticSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry, provider=None, signal=None, device=None):
        self._provider = provider or (lambda: entry.runtime_data)
        self._signal = signal or f"{DOMAIN}_{entry.entry_id}_updated"
        self._attr_device_info = device or DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data["name"],
            manufacturer="Zonentra",
        )

    @property
    def runtime(self):
        """The building runtime; a zone reads the central one (None if unloaded)."""
        return self._provider()

    def _present(self, runtime) -> bool:
        return True

    @property
    def available(self) -> bool:
        runtime = self.runtime
        return runtime is not None and self._present(runtime)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._updated)
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

    def __init__(self, entry, zone, unique_id=None, translation_key=None, **shared):
        super().__init__(entry, **shared)
        self._zone = zone
        self._attr_translation_placeholders = {"zone": zone.name}
        self._attr_unique_id = unique_id or f"{entry.entry_id}_zone_{zone.id}_demand"
        if translation_key:
            self._attr_translation_key = translation_key

    @property
    def zone(self) -> Zone:
        """The effective zone from the current building (after reloads)."""
        runtime = self.runtime
        zones = runtime.building.zones if runtime else ()
        return next((zone for zone in zones if zone.id == self._zone.id), self._zone)

    def _present(self, runtime) -> bool:
        return self._zone.id in runtime.zone_demands

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
            "limits_source": "building" if self.zone.use_building_limits else "zone",
            "parameters_source": "building"
            if self.zone.use_building_parameters
            else "zone",
            "sensor_validation": self.zone.sensor_validation,
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
            # Health, strategy, ages and whether freshness is actually verifiable.
            "temperature_validation": describe(
                snapshot.temperature, self.runtime.evaluated_at
            ),
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
            # Physical mode only comes from the configured, trusted feedback.
            "physical_mode": decision.current_mode,
            "mode_feedback_quality": decision.mode_quality,
            "physical_mode_feedback_available": decision.mode_quality == "valid",
            "derived_group_mode": self.runtime.group_observations[
                self.group.id
            ].derived_mode,
            "observation_reason": self.runtime.mode_comparisons[self.group.id],
        }


class IndoorUnitSensor(ZonentraDiagnosticSensor):
    """Selected mode of one linked indoor unit, as reported by Home Assistant."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "heat",
        "cool",
        "heat_cool",
        "auto",
        "dry",
        "fan_only",
        "off",
        "unknown",
    ]
    _attr_icon = "mdi:air-conditioner"
    _attr_translation_key = "indoor_unit"

    def __init__(self, entry, item, unique_id=None, **shared):
        super().__init__(entry, **shared)
        self.item = item
        self._attr_translation_placeholders = {"unit": item.name}
        self._attr_unique_id = (
            unique_id or f"{entry.entry_id}_equipment_{item.id}_indoor_unit"
        )

    def _present(self, runtime) -> bool:
        return self.item.id in runtime.indoor_units

    @property
    def native_value(self):
        unit = self.runtime.indoor_units[self.item.id]
        return (
            unit.selected_mode
            if unit.selected_mode in self._attr_options
            else "unknown"
        )

    @property
    def extra_state_attributes(self):
        unit = self.runtime.indoor_units[self.item.id]
        return {
            "read_only": True,
            "indoor_unit_entity": self.item.entity_id,
            "selected_mode": unit.selected_mode,
            "reported_action": unit.reported_action,
            "current_temperature": unit.current_temperature,
            "target_temperature": unit.target_temperature,
            "temperature_unit": unit.temperature_unit,
            "fan_mode": unit.fan_mode,
            "availability": unit.availability,
            "observation_quality": unit.quality,
            "selected_action_mismatch": unit.mismatch,
            "observed_at": unit.observed_at,
        }


class DerivedGroupModeSensor(ZonentraDiagnosticSensor):
    """Group mode interpreted from indoor units — never physical outdoor feedback."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["heat", "cool", "inactive", "mixed", "unknown"]
    _attr_icon = "mdi:home-search-outline"
    _attr_translation_key = "derived_group_mode"

    def __init__(self, entry, group):
        super().__init__(entry)
        self.group = group
        self._attr_translation_placeholders = {"group": group.name}
        self._attr_unique_id = f"{entry.entry_id}_group_{group.id}_derived_mode"

    @property
    def native_value(self):
        return self.runtime.group_observations[self.group.id].derived_mode

    @property
    def extra_state_attributes(self):
        observation = self.runtime.group_observations[self.group.id]
        decision = self.runtime.group_decisions[self.group.id]
        return {
            "read_only": True,
            "derived_from": "indoor_units",
            "member_indoor_units": observation.member_units,
            "available_indoor_units": observation.available_units,
            "usable_selected_modes": observation.usable_modes,
            "usable_hvac_actions": observation.usable_actions,
            "selected_modes": dict(observation.selected_modes),
            "selected_mode_consensus": observation.selected_consensus,
            "selected_modes_agree": observation.modes_agree,
            "reported_activity": observation.reported_activity,
            "reported_actions_agree": observation.actions_agree,
            "conflict_detected": observation.conflict,
            "conflicts": list(observation.conflicts),
            "completeness": observation.completeness,
            "quality": observation.quality,
            "reason": observation.reason,
            "notes": list(observation.notes),
            "desired_mode": decision.desired_mode,
            "physical_mode": decision.current_mode,
            "physical_mode_feedback_available": decision.mode_quality == "valid",
            "observation_reason": self.runtime.mode_comparisons[self.group.id],
        }


def _iso(value):
    return value.isoformat() if value else None


class UnitControlSensor(ZonentraDiagnosticSensor):
    """Simulated next action for one indoor unit — never executed in 0.5."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "turn_on_heat",
        "turn_on_cool",
        "turn_off",
        "correct_mode",
        "hold",
        "blocked",
    ]
    _attr_icon = "mdi:play-box-outline"
    _attr_translation_key = "unit_control"

    def __init__(self, entry, item, unique_id=None, **shared):
        super().__init__(entry, **shared)
        self.item = item
        self._attr_translation_placeholders = {"unit": item.name}
        self._attr_unique_id = (
            unique_id or f"{entry.entry_id}_equipment_{item.id}_control"
        )

    def _present(self, runtime) -> bool:
        return self.item.id in runtime.unit_intents

    @property
    def native_value(self):
        return self.runtime.unit_intents[self.item.id].action

    @property
    def extra_state_attributes(self):
        intent = self.runtime.unit_intents[self.item.id]
        return {
            "simulation": True,
            "read_only": True,
            "zone": next(
                (z.name for z in self.runtime.building.zones if z.id == intent.zone_id),
                None,
            ),
            "observed_mode": intent.observed_mode,
            "desired_mode": intent.desired_mode,
            "zone_demand": intent.zone_demand,
            "intended_action": intent.action,
            "steps": list(intent.steps),
            "reason": intent.reason,
            "blocked_reason": intent.blocked_reason,
            "blocked_until": _iso(intent.blocked_until),
            "manual_override_active": intent.manual_override_active,
            "override_remaining_seconds": intent.override_remaining_seconds,
            "override_expires_at": _iso(intent.override_expires_at),
            "seconds_since_transition": intent.seconds_since_transition,
            "group_coordination_phase": intent.coordination_phase,
            "availability": intent.availability,
            "evaluated_at": _iso(self.runtime.evaluated_at),
        }


class GroupCoordinationSensor(ZonentraDiagnosticSensor):
    """Simulated group coordination and switch phase — never executed in 0.5."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "idle",
        "preparing",
        "stopping",
        "waiting",
        "applying",
        "verifying",
        "completed",
        "blocked",
        "failed",
    ]
    _attr_icon = "mdi:swap-horizontal-circle-outline"
    _attr_translation_key = "group_coordination"

    def __init__(self, entry, group):
        super().__init__(entry)
        self.group = group
        self._attr_translation_placeholders = {"group": group.name}
        self._attr_unique_id = f"{entry.entry_id}_group_{group.id}_coordination"

    @property
    def native_value(self):
        return self.runtime.coordinations[self.group.id].phase

    @property
    def extra_state_attributes(self):
        item = self.runtime.coordinations[self.group.id]
        names = {e.id: e.name for e in self.runtime.building.equipment}
        return {
            "simulation": True,
            "read_only": True,
            "desired_mode": item.desired_mode,
            "group_mode": item.group_mode,
            "group_mode_reason": item.group_mode_reason,
            "coordinated_mode": item.coordinated_mode,
            "derived_mode": item.derived_mode,
            "member_indoor_units": item.member_units,
            "available_indoor_units": item.available_units,
            "conflicts": list(item.conflicts),
            "switch_needed": item.switch_needed,
            "switch_from": item.switch_from,
            "switch_to": item.switch_to,
            "switch_allowed_in_simulation": item.switch_allowed_in_simulation,
            "active_switch_permitted": item.active_switch_permitted,
            "phase_reason": item.phase_reason,
            "waiting_until": _iso(item.waiting_until),
            "blockers": list(item.blockers),
            "planned_actions": {
                names.get(unit, unit): action for unit, action in item.planned_actions
            },
            "evaluated_at": _iso(self.runtime.evaluated_at),
        }
