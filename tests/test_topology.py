"""0.6.0 pure tests: central configuration + zone entries -> one building."""

import pytest

from custom_components.zonentra.models import build_model
from custom_components.zonentra.topology import assemble, equipment_id

CENTRAL = {
    "building": {"heating_limit": 22, "cooling_limit": 24, "hysteresis": 0.3},
    "groups": [{"id": "outdoor_1", "name": "Outdoor 1"}],
}


def zone(zone_id, *units, **fields):
    return {
        "id": zone_id,
        "name": zone_id.title(),
        "temperature_entity": f"sensor.{zone_id}",
        "group_id": "outdoor_1",
        "indoor_units": list(units),
        "use_building_limits": True,
        "use_building_parameters": True,
        **fields,
    }


def test_central_and_zones_become_one_building():
    topology = assemble(
        CENTRAL,
        [
            zone("west", "climate.west_1", "climate.west_2"),
            zone("meeting", "climate.meeting", shading_entities=["cover.meeting"]),
        ],
    )
    building = build_model("central", "Building", topology)
    assert [z.id for z in building.zones] == ["west", "meeting"]
    assert building.zones[0].heating_limit == 22  # Central limits.
    hvac = [item for item in building.equipment if item.kind == "hvac"]
    assert [(item.id, item.zone_id, item.group_id) for item in hvac] == [
        ("hvac_west_1", "west", "outdoor_1"),
        ("hvac_west_2", "west", "outdoor_1"),
        ("hvac_meeting", "meeting", "outdoor_1"),
    ]
    shading = [item for item in building.equipment if item.kind == "shading"]
    assert shading[0].group_id is None and shading[0].entity_id == "cover.meeting"
    assert "indoor_units" not in topology["zones"][0]


def test_local_zone_values_and_no_group():
    topology = assemble(
        CENTRAL,
        [
            zone(
                "lab",
                "climate.lab",
                group_id=None,
                use_building_limits=False,
                heating_limit=19,
                cooling_limit=26,
            )
        ],
    )
    building = build_model("central", "Building", topology)
    assert (building.zones[0].heating_limit, building.zones[0].cooling_limit) == (
        19,
        26,
    )
    assert building.equipment[0].group_id is None


def test_indoor_unit_belongs_to_one_zone():
    with pytest.raises(ValueError, match="duplicate_equipment_entity"):
        assemble(CENTRAL, [zone("west", "climate.ac"), zone("east", "climate.ac")])


def test_same_entity_as_two_kinds_is_rejected():
    topology = assemble(
        CENTRAL, [zone("west", "climate.ac", floor_heating_entities=["climate.floor"])]
    )
    build_model("central", "Building", topology)
    with pytest.raises(ValueError, match="duplicate_equipment_entity"):
        assemble(
            CENTRAL, [zone("west", "climate.ac", floor_heating_entities=["climate.ac"])]
        )


def test_unknown_group_is_rejected():
    topology = assemble(CENTRAL, [zone("west", "climate.ac", group_id="missing")])
    with pytest.raises(ValueError, match="invalid_reference"):
        build_model("central", "Building", topology)


def test_equipment_ids_are_stable_and_valid():
    assert equipment_id("hvac", "climate.open_office_ac") == "hvac_open_office_ac"
    assert equipment_id("shading", "cover.x") == "shade_x"
    long_id = equipment_id("hvac", "climate." + "a" * 80)
    assert len(long_id) == 64


def test_empty_central_configuration():
    building = build_model("central", "Building", assemble({}, []))
    assert building.zones == () and building.groups == ()
