"""Use real Home Assistant fixtures and enable local custom integrations."""

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def topology():
    return {
        "zones": [
            {
                "id": "office",
                "name": "Office",
                "temperature_entity": "sensor.office_temperature",
            }
        ],
        "groups": [{"id": "outdoor_1", "name": "Outdoor 1"}],
        "equipment": [
            {
                "id": "indoor_1",
                "name": "Indoor 1",
                "kind": "hvac",
                "entity_id": "climate.indoor_1",
                "zone_id": "office",
                "group_id": "outdoor_1",
            }
        ],
    }
