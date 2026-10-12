"""Pure, idempotent configuration normalization for central building settings."""

from copy import deepcopy

LIMIT_FIELDS = (
    "heating_limit",
    "cooling_limit",
    "heating_limit_entity",
    "cooling_limit_entity",
)
PARAMETER_FIELDS = ("hysteresis", "max_age_seconds")
NEW_BUILDING_DEFAULTS = {
    "heating_limit": 21.0,
    "cooling_limit": 24.0,
    "hysteresis": 0.3,
    "max_age_seconds": 1800.0,
}


def migrate_options(options: dict) -> dict:
    """Keep existing room policy explicit; never guess a shared weather source."""
    result = deepcopy(options)
    settings = result.get("building", {})
    outside = set(settings.get("outdoor_temperature_candidates", []))
    ages = []
    for zone in result.get("zones", []):
        zone.pop("controller_entity", None)
        entity = zone.pop("outdoor_temperature_entity", None)
        if entity:
            outside.add(entity)
            ages.append(zone.get("max_age_seconds", 1800))
        zone.setdefault(
            "use_building_limits",
            not any(zone.get(key) is not None for key in LIMIT_FIELDS),
        )
        zone.setdefault(
            "use_building_parameters", not any(key in zone for key in PARAMETER_FIELDS)
        )
    if outside and not settings.get("outdoor_temperature_entity"):
        if len(outside) == 1:
            settings["outdoor_temperature_entity"] = next(iter(outside))
            settings.setdefault(
                "outdoor_max_age_seconds",
                min((age for age in ages if age > 0), default=0 if ages else 1800),
            )
            settings.pop("outdoor_temperature_candidates", None)
        else:
            settings["outdoor_temperature_candidates"] = sorted(outside)
    elif settings.get("outdoor_temperature_entity"):
        settings.pop("outdoor_temperature_candidates", None)
    if settings or "building" in result:
        result["building"] = settings
    return result
