"""UI setup and transactional topology editing for one building."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

import probatio as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import DOMAIN, KINDS, TOPOLOGY_KEYS
from .migration import (
    LIMIT_FIELDS,
    NEW_BUILDING_DEFAULTS,
    PARAMETER_FIELDS,
    migrate_options,
)
from .models import BuildingSettings, EquipmentGroup, Zone, build_model
from .observations import VALIDATION_STRATEGIES


def entity_selector(domain=None):
    config = {"filter": {"domain": domain}} if domain else {}
    return selector.EntitySelector(config)


def numeric(low, high, step=0.1, unit=None):
    config = {"min": low, "max": high, "step": step, "mode": "box"}
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def choice(options):
    return selector.SelectSelector({"options": options, "mode": "dropdown"})


class ZonentraConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 3

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            name = user_input["name"].strip()
            if name:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={"name": name},
                    options={
                        **{key: [] for key in TOPOLOGY_KEYS},
                        "building": dict(NEW_BUILDING_DEFAULTS),
                    },
                )
            errors["name"] = "invalid_name"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): selector.TextSelector(),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return ZonentraOptionsFlow()


class ZonentraOptionsFlow(OptionsFlowWithReload):
    """Collect edits in a private copy and save only via Finish."""

    def __init__(self):
        self.topology: dict[str, Any] | None = None
        self.selected: str | None = None
        self.new_id: str | None = None
        self._visible_zone_blocks = {"limits": False, "parameters": False}

    async def async_step_init(self, user_input=None):
        if self.topology is None:
            self.topology = migrate_options(dict(self.config_entry.options))
            for key in TOPOLOGY_KEYS:
                self.topology.setdefault(key, [])
        return self.async_show_menu(
            step_id="init",
            menu_options=["building", "zone", "group", "equipment", "finish"],
        )

    async def async_step_building(self, user_input=None):
        errors = {}
        if user_input is not None:
            candidate = deepcopy(self.topology)
            settings = {key: value for key, value in user_input.items() if value != ""}
            candidates = self.topology.get("building", {}).get(
                "outdoor_temperature_candidates", []
            )
            if candidates and not settings.get("outdoor_temperature_entity"):
                settings["outdoor_temperature_candidates"] = candidates
            candidate["building"] = settings
            try:
                self._validate(candidate)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self.topology = candidate
                return await self.async_step_init()
        fields = {
            vol.Optional("outdoor_temperature_entity"): entity_selector("sensor"),
            vol.Optional("outdoor_max_age_seconds"): numeric(0, 86400, 1, "s"),
            vol.Optional("heating_limit"): numeric(5, 35, unit="°C"),
            vol.Optional("cooling_limit"): numeric(5, 35, unit="°C"),
            vol.Optional("heating_limit_entity"): entity_selector(
                ["sensor", "number", "input_number"]
            ),
            vol.Optional("cooling_limit_entity"): entity_selector(
                ["sensor", "number", "input_number"]
            ),
            vol.Optional("hysteresis"): numeric(0.1, 2, unit="°C"),
            vol.Optional("sensor_validation"): choice(list(VALIDATION_STRATEGIES)),
            vol.Optional("max_age_seconds"): numeric(0, 86400, 1, "s"),
        }
        defaults = {
            **NEW_BUILDING_DEFAULTS,
            "outdoor_max_age_seconds": BuildingSettings().outdoor_max_age_seconds,
        }
        current = self.topology.get("building", {})
        schema = self.add_suggested_values_to_schema(
            vol.Schema(fields), {**defaults, **current, **(user_input or {})}
        )
        return self.async_show_form(
            step_id="building",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "outdoor_candidates": ", ".join(
                    current.get("outdoor_temperature_candidates", [])
                )
                or "—"
            },
        )

    async def async_step_finish(self, user_input=None):
        # Revalidate at the transaction boundary.
        build_model(
            self.config_entry.entry_id, self.config_entry.data["name"], self.topology
        )
        return self.async_create_entry(title="", data=self.topology)

    async def _select(self, category, user_input):
        if user_input is not None:
            self.selected = user_input["record"]
            self.new_id = uuid4().hex if self.selected == "__new__" else None
            return await getattr(self, f"async_step_{category}_details")()
        records = self.topology[
            {"zone": "zones", "group": "groups", "equipment": "equipment"}[category]
        ]
        return self.async_show_form(
            step_id=category,
            data_schema=vol.Schema(
                {
                    vol.Required("record"): choice(
                        [
                            {"value": "__new__", "label": "Add new"},
                            *[
                                {"value": item["id"], "label": item["name"]}
                                for item in records
                            ],
                        ]
                    ),
                }
            ),
        )

    async def async_step_zone(self, user_input=None):
        return await self._select("zone", user_input)

    async def async_step_group(self, user_input=None):
        return await self._select("group", user_input)

    async def async_step_equipment(self, user_input=None):
        if not self.topology["zones"]:
            return self.async_show_form(
                step_id="equipment", errors={"base": "add_zone_first"}
            )
        return await self._select("equipment", user_input)

    def _schema(self, category, suggestions=None):
        fields = {
            vol.Required("name"): selector.TextSelector(),
        }
        if category == "zone":
            fields.update(
                {
                    vol.Optional("temperature_entity"): entity_selector("sensor"),
                    vol.Optional("use_building_limits"): selector.BooleanSelector(),
                    vol.Optional("use_building_parameters"): selector.BooleanSelector(),
                    vol.Optional("occupancy_entity"): entity_selector("binary_sensor"),
                    vol.Optional("heating_limit"): numeric(5, 35, unit="°C"),
                    vol.Optional("cooling_limit"): numeric(5, 35, unit="°C"),
                    vol.Optional("heating_limit_entity"): entity_selector(
                        ["sensor", "number", "input_number"]
                    ),
                    vol.Optional("cooling_limit_entity"): entity_selector(
                        ["sensor", "number", "input_number"]
                    ),
                    vol.Optional("humidity_entity"): entity_selector("sensor"),
                    vol.Optional("co2_entity"): entity_selector("sensor"),
                    vol.Optional("contact_entities"): selector.EntitySelector(
                        {"filter": {"domain": "binary_sensor"}, "multiple": True}
                    ),
                    vol.Optional("weight"): numeric(0.1, 10),
                    vol.Optional("hysteresis"): numeric(0.1, 2, unit="°C"),
                    vol.Optional("sensor_validation"): choice(
                        list(VALIDATION_STRATEGIES)
                    ),
                    vol.Optional("max_age_seconds"): numeric(0, 86400, 1, "s"),
                    vol.Optional("group_id"): self._group_selector(),
                }
            )
        elif category == "group":
            fields.update(
                {
                    vol.Optional("mode_entity"): entity_selector(
                        ["sensor", "select", "climate"]
                    ),
                    vol.Optional("min_switch_seconds"): numeric(0, 86400, 1, "s"),
                    vol.Optional("min_demand_score"): numeric(0.1, 100),
                    vol.Optional("score_deadband"): numeric(0.1, 100),
                    vol.Optional("max_age_seconds"): numeric(0, 86400, 1, "s"),
                }
            )
        elif category == "equipment":
            fields.update(
                {
                    vol.Required("kind"): choice(list(KINDS)),
                    vol.Required("entity_id"): entity_selector(),
                    vol.Required("zone_id"): choice(
                        [
                            {"value": item["id"], "label": item["name"]}
                            for item in self.topology["zones"]
                        ]
                    ),
                    vol.Optional("group_id"): self._group_selector(),
                }
            )
        if self.selected != "__new__":
            fields[vol.Optional("delete", default=False)] = selector.BooleanSelector()
        schema = vol.Schema(fields)
        key = {"zone": "zones", "group": "groups", "equipment": "equipment"}[category]
        current = next(
            (item for item in self.topology[key] if item["id"] == self.selected), {}
        )
        defaults = {}
        if category == "zone":
            zone = Zone(id="suggestion", name="suggestion")
            defaults = {
                "heating_limit": 21.0,
                "cooling_limit": 24.0,
                "weight": zone.weight,
                "hysteresis": zone.hysteresis,
                "max_age_seconds": zone.max_age_seconds,
                "sensor_validation": zone.sensor_validation,
                "use_building_limits": True,
                "use_building_parameters": True,
            }
        elif category == "group":
            group = EquipmentGroup(id="suggestion", name="suggestion")
            defaults = {
                key: getattr(group, key)
                for key in (
                    "min_switch_seconds",
                    "min_demand_score",
                    "score_deadband",
                    "max_age_seconds",
                )
            }
        if category == "zone":
            central = self.topology.get("building", {})
            defaults.update(
                {
                    key: central[key]
                    for key in (*LIMIT_FIELDS, *PARAMETER_FIELDS)
                    if key in central
                }
            )
        values = {**defaults, **current, **(suggestions or {})}
        if category == "zone" and suggestions is not None:
            for key in (
                "temperature_entity",
                "occupancy_entity",
                "humidity_entity",
                "co2_entity",
                "contact_entities",
                "group_id",
            ):
                if key not in suggestions:
                    values.pop(key, None)
        if category == "zone":
            for flag, block, keys in (
                ("use_building_limits", "limits", LIMIT_FIELDS),
                ("use_building_parameters", "parameters", PARAMETER_FIELDS),
            ):
                self._visible_zone_blocks[block] = not values[flag]
                if values[flag]:
                    fields = {
                        marker: value
                        for marker, value in fields.items()
                        if marker.schema not in keys
                    }
            schema = vol.Schema(fields)
        return self.add_suggested_values_to_schema(schema, values)

    def _group_selector(self):
        return choice(
            [
                {"value": "", "label": "No group"},
                *[
                    {"value": item["id"], "label": item["name"]}
                    for item in self.topology["groups"]
                ],
            ]
        )

    async def _edit(self, category, user_input):
        errors = {}
        if user_input is not None:
            candidate = deepcopy(self.topology)
            key = {"zone": "zones", "group": "groups", "equipment": "equipment"}[
                category
            ]
            record = {k: v for k, v in user_input.items() if k != "delete" and v != ""}
            record["id"] = self.new_id if self.selected == "__new__" else self.selected
            previous_record = next(
                (item for item in self.topology[key] if item["id"] == self.selected), {}
            )
            if category == "zone":
                for flag, block, keys in (
                    ("use_building_limits", "limits", LIMIT_FIELDS),
                    ("use_building_parameters", "parameters", PARAMETER_FIELDS),
                ):
                    record.setdefault(flag, previous_record.get(flag, True))
                    if (
                        not record[flag]
                        and not self._visible_zone_blocks[block]
                        and not user_input.get("delete")
                    ):
                        return self.async_show_form(
                            step_id="zone_details",
                            data_schema=self._schema(
                                category, {**user_input, **{flag: record[flag]}}
                            ),
                            errors={},
                        )
                    if record[flag]:
                        for field in keys:
                            record.pop(field, None)
                            if field in previous_record:
                                record[field] = previous_record[field]
            if category == "group":
                previous_record = next(
                    (
                        item
                        for item in self.topology[key]
                        if item["id"] == self.selected
                    ),
                    {},
                )
                if "single_hvac_mode" in previous_record:
                    record["single_hvac_mode"] = previous_record["single_hvac_mode"]
            try:
                candidate[key] = [
                    item for item in candidate[key] if item["id"] != self.selected
                ]
                if not user_input.get("delete", False):
                    candidate[key].append(record)
                self._validate(candidate)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self.topology = candidate
                return await self.async_step_init()
        schema = self._schema(category, user_input)
        return self.async_show_form(
            step_id=f"{category}_details", data_schema=schema, errors=errors
        )

    def _validate(self, candidate):
        building = build_model(
            self.config_entry.entry_id, self.config_entry.data["name"], candidate
        )
        previous = build_model(
            self.config_entry.entry_id, self.config_entry.data["name"], self.topology
        )
        known = previous.entity_ids | frozenset(
            previous.settings.outdoor_temperature_candidates
        )
        registry = er.async_get(self.hass)
        for entity_id in building.entity_ids:
            registered = registry.async_get(entity_id)
            if registered and registered.platform == DOMAIN:
                raise ValueError("invalid_entity")
            if (
                entity_id not in known
                and not registered
                and self.hass.states.get(entity_id) is None
            ):
                raise ValueError("entity_not_found")

    async def async_step_zone_details(self, user_input=None):
        return await self._edit("zone", user_input)

    async def async_step_group_details(self, user_input=None):
        return await self._edit("group", user_input)

    async def async_step_equipment_details(self, user_input=None):
        return await self._edit("equipment", user_input)
