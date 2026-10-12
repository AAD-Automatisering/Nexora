"""UI setup and transactional topology editing for one building."""

from copy import deepcopy
from typing import Any

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
from .models import build_model


def entity_selector(domain=None):
    config = {"filter": {"domain": domain}} if domain else {}
    return selector.EntitySelector(config)


def choice(options):
    return selector.SelectSelector({"options": options, "mode": "dropdown"})


class NexoraConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

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
                    options={key: [] for key in TOPOLOGY_KEYS},
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
        return NexoraOptionsFlow()


class NexoraOptionsFlow(OptionsFlowWithReload):
    """Collect edits in a private copy and save only via Finish."""

    def __init__(self):
        self.topology: dict[str, Any] | None = None
        self.selected: str | None = None

    async def async_step_init(self, user_input=None):
        if self.topology is None:
            self.topology = deepcopy(dict(self.config_entry.options))
            for key in TOPOLOGY_KEYS:
                self.topology.setdefault(key, [])
        return self.async_show_menu(
            step_id="init", menu_options=["zone", "group", "equipment", "finish"]
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

    def _schema(self, category):
        fields = {
            vol.Required("id"): selector.TextSelector(),
            vol.Required("name"): selector.TextSelector(),
        }
        if category == "zone":
            fields.update(
                {
                    vol.Optional("temperature_entity"): entity_selector("sensor"),
                    vol.Optional("controller_entity"): entity_selector("climate"),
                    vol.Optional("occupancy_entity"): entity_selector("binary_sensor"),
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
                    vol.Optional("group_id"): choice(
                        [
                            {"value": "", "label": "No group"},
                            *[
                                {"value": item["id"], "label": item["name"]}
                                for item in self.topology["groups"]
                            ],
                        ]
                    ),
                }
            )
        if self.selected != "__new__":
            fields[vol.Optional("delete", default=False)] = selector.BooleanSelector()
        schema = vol.Schema(fields)
        key = {"zone": "zones", "group": "groups", "equipment": "equipment"}[category]
        current = next(
            (item for item in self.topology[key] if item["id"] == self.selected), {}
        )
        return self.add_suggested_values_to_schema(schema, current)

    async def _edit(self, category, user_input):
        errors = {}
        if user_input is not None:
            candidate = deepcopy(self.topology)
            key = {"zone": "zones", "group": "groups", "equipment": "equipment"}[
                category
            ]
            record = {k: v for k, v in user_input.items() if k != "delete" and v != ""}
            try:
                if self.selected != "__new__" and record["id"] != self.selected:
                    raise ValueError("id_immutable")
                candidate[key] = [
                    item for item in candidate[key] if item["id"] != self.selected
                ]
                if not user_input.get("delete", False):
                    candidate[key].append(record)
                building = build_model(
                    self.config_entry.entry_id,
                    self.config_entry.data["name"],
                    candidate,
                )
                # Existing absent inputs remain editable; new links must exist in HA.
                previous = build_model(
                    self.config_entry.entry_id,
                    self.config_entry.data["name"],
                    self.topology,
                )
                registry = er.async_get(self.hass)
                for entity_id in building.entity_ids:
                    registered = registry.async_get(entity_id)
                    if registered and registered.platform == DOMAIN:
                        raise ValueError("invalid_entity")
                    if (
                        entity_id not in previous.entity_ids
                        and not registered
                        and self.hass.states.get(entity_id) is None
                    ):
                        raise ValueError("entity_not_found")
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self.topology = candidate
                return await self.async_step_init()
        schema = self._schema(category)
        if user_input:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id=f"{category}_details", data_schema=schema, errors=errors
        )

    async def async_step_zone_details(self, user_input=None):
        return await self._edit("zone", user_input)

    async def async_step_group_details(self, user_input=None):
        return await self._edit("group", user_input)

    async def async_step_equipment_details(self, user_input=None):
        return await self._edit("equipment", user_input)
