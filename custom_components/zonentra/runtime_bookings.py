"""Room booking retrieval, adaptive preparation and persisted thermal learning."""

import asyncio
from dataclasses import asdict, replace
from datetime import timedelta

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .bookings import (
    BookingPlan,
    ThermalRates,
    learn_rate,
    outdoor_band,
    parse_bookings,
    plan_booking,
)
from .demand import comfort_limits
from .observations import max_age_for, read
from .temperature import convert_temperature

CALENDAR_REFRESH_MINUTES = 5
CALENDAR_MAX_AGE_MINUTES = 10
CALENDAR_HORIZON_HOURS = 24


class BookingRuntimeMixin:
    """Calendars request comfort; existing room and group controls authorize HVAC."""

    def load_thermal_rates(self, data):
        if not isinstance(data, dict):
            return
        for zone in self.building.zones:
            stored = data.get(zone.id)
            if isinstance(stored, dict):
                self.thermal_rates[zone.id] = {
                    band: ThermalRates.restore(values)
                    for band, values in stored.items()
                    if band in ("unknown", "freezing", "cold", "mild", "warm", "hot")
                }

    def _save_thermal_rates(self):
        if self.thermal_store is None:
            return
        self.thermal_store.async_delay_save(
            lambda: {
                zone: {band: asdict(rates) for band, rates in values.items()}
                for zone, values in self.thermal_rates.items()
            },
            5,
        )

    async def async_update_bookings(self, _now=None):
        if self._closed or self._calendar_refreshing:
            return
        entities = {z.calendar_entity for z in self.building.zones if z.calendar_entity}
        if not entities:
            return
        self._calendar_refreshing = True
        now = dt_util.utcnow()

        async def fetch(entity):
            try:
                async with asyncio.timeout(30):
                    response = await self.hass.services.async_call(
                        "calendar",
                        "get_events",
                        {
                            "entity_id": entity,
                            "start_date_time": now.isoformat(),
                            "end_date_time": (
                                now + timedelta(hours=CALENDAR_HORIZON_HOURS)
                            ).isoformat(),
                        },
                        blocking=True,
                        return_response=True,
                    )
            except HomeAssistantError, TimeoutError:
                return entity, None, "service_error"
            record = response.get(entity) if isinstance(response, dict) else None
            events = parse_bookings(
                record.get("events") if isinstance(record, dict) else None,
                dt_util.DEFAULT_TIME_ZONE,
            )
            return entity, events, None if events is not None else "invalid_response"

        try:
            records = await asyncio.gather(*(fetch(entity) for entity in entities))
            if self._closed:
                return  # A response must not revive an unloaded runtime.
            for entity, events, error in records:
                self.booking_events[entity] = events
                self.booking_updated[entity] = now
                self.booking_errors[entity] = error
            self.refresh()
        finally:
            self._calendar_refreshing = False

    def _booking_occupancy(self, zone, occupancy, sources, now):
        if not zone.calendar_entity:
            self.booking_plans[zone.id] = BookingPlan("not_configured")
            return occupancy
        source = sources.get(zone.calendar_entity)
        updated = self.booking_updated.get(zone.calendar_entity)
        fresh = updated is not None and now < updated + timedelta(
            minutes=CALENDAR_MAX_AGE_MINUTES
        )
        events = (
            self.booking_events.get(zone.calendar_entity)
            if fresh
            and source is not None
            and source.trustworthy
            and source.state in ("on", "off")
            else None
        )
        temperature = read(
            sources.get(zone.temperature_entity),
            "temperature",
            now,
            max_age_for(zone.sensor_validation, zone.max_age_seconds),
        )
        thermostat = self.thermostat(zone.id)
        own_band = (
            (thermostat.heating_limit, thermostat.cooling_limit)
            if thermostat.has_band and not zone.use_building_limits
            else None
        )
        heat, cool = comfort_limits(zone, sources, now, own_band)
        outside = self._booking_outdoor_temperature()
        rates = self.thermal_rates.get(zone.id, {}).get(
            outdoor_band(outside), ThermalRates()
        )
        plan = plan_booking(
            events,
            now,
            temperature.value if temperature.quality == "valid" else None,
            heat.value if heat.quality == "valid" else None,
            cool.value if cool.quality == "valid" else None,
            zone.hysteresis,
            rates,
            heating_rate=zone.preconditioning_heating_rate,
            cooling_rate=zone.preconditioning_cooling_rate,
            buffer_minutes=zone.preconditioning_buffer_minutes,
            max_minutes=zone.preconditioning_max_minutes,
            previous=self.booking_plans.get(zone.id),
            outdoor=outside,
        )
        self.booking_plans[zone.id] = plan
        if plan.next_check:
            self._booking_checks.append(plan.next_check)
        if updated and fresh:
            self._booking_checks.append(
                updated + timedelta(minutes=CALENDAR_MAX_AGE_MINUTES)
            )
        if plan.active:
            # Bookings need comfort before people arrive, even if the building
            # presence is still absent. Explicit thermostat off/away wins later.
            return replace(occupancy, mode="comfort", reason=f"booking_{plan.status}")
        if (
            plan.status != "unknown"
            and occupancy.mode == "comfort"
            and occupancy.motion == "not_configured"
        ):
            # A room with a calendar but no motion sensor uses eco between meetings.
            return replace(occupancy, mode="eco", reason="no_booking")
        return occupancy

    def _booking_outdoor_temperature(self):
        if self.building.settings.outdoor_temperature_entity:
            return (
                self.outdoor_temperature.value
                if self.outdoor_temperature.quality == "valid"
                else None
            )
        # An existing weather entity can provide current outdoor temperature
        # when no dedicated outdoor sensor was configured.
        entity_id = self.building.settings.weather_entity
        state = self.hass.states.get(entity_id) if entity_id else None
        if (
            state is None
            or state.state in ("unknown", "unavailable")
            or state.attributes.get("restored")
            or state.attributes.get("assumed_state")
        ):
            return None
        return convert_temperature(
            state.attributes.get("temperature"),
            state.attributes.get("temperature_unit")
            or self.hass.config.units.temperature_unit,
        )

    def _learn_booking_rates(self, now):
        for zone in self.building.zones:
            if not zone.calendar_entity:
                continue
            temperature = self.zone_snapshots[zone.id].temperature
            units = [
                u
                for u in self.indoor_units.values()
                if u.zone_id == zone.id and u.available
            ]
            modes = {
                u.activity
                if u.activity is not None
                else {"heat": "heating", "cool": "cooling"}.get(u.selected_mode)
                for u in units
            }
            mode = next(iter(modes)) if len(modes) == 1 else None
            eligible = (
                mode in ("heating", "cooling")
                and self.regulated(zone.id)
                and self.thermostat(zone.id).hvac_mode != "off"
                and self.windows.get(zone.id) not in ("open", "opening", "unknown")
                and temperature.quality == "valid"
                and all(
                    not self._group_block(item.group_id)
                    and item.id not in self.overrides
                    for item in self.building.equipment
                    if item.kind == "hvac" and item.zone_id == zone.id
                )
            )
            outside = self._booking_outdoor_temperature()
            band = outdoor_band(outside)
            by_band = self.thermal_rates.setdefault(zone.id, {})
            rates = by_band.get(band, ThermalRates())
            context = (mode if eligible else None, band)
            if self.thermal_context.get(zone.id) != context:
                self.thermal_context[zone.id] = context
                self.thermal_samples[zone.id] = None
                self.thermal_reports.pop(zone.id, None)
                self.thermal_started[zone.id] = now
            reported = temperature.reported_at
            if not eligible:
                self.thermal_samples[zone.id] = None
                continue
            if reported is None or reported < self.thermal_started.get(zone.id, now):
                continue
            if reported <= self.thermal_reports.get(
                zone.id, reported - timedelta(microseconds=1)
            ):
                continue
            self.thermal_reports[zone.id] = reported
            learned, sample = learn_rate(
                rates,
                self.thermal_samples.get(zone.id),
                temperature.reported_at or now,
                temperature.value if eligible else None,
                mode,
                outside,
            )
            self.thermal_samples[zone.id] = sample
            if learned != rates:
                by_band[band] = learned
                self._save_thermal_rates()
