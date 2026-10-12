"""Every UI identifier used in code has a non-empty label in every language.

Pure file checks (no Home Assistant instance): a missing translation renders as
an empty menu entry, field or state in the frontend without any error.
"""

import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "zonentra"
FILES = {
    "strings": ROOT / "strings.json",
    "en": ROOT / "translations" / "en.json",
    "nl": ROOT / "translations" / "nl.json",
}
TRANSLATIONS = {name: json.loads(path.read_text()) for name, path in FILES.items()}
FLOW = ast.parse((ROOT / "config_flow.py").read_text())
CATEGORIES = ("zone", "group", "equipment")


def leaves(tree, prefix=()):
    if isinstance(tree, dict):
        for key, value in tree.items():
            yield from leaves(value, (*prefix, key))
    else:
        yield prefix, tree


def label(language, *path):
    node = TRANSLATIONS[language]
    for key in path:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, str) else ""


def keyword(call, name):
    return next((k.value for k in call.keywords if k.arg == name), None)


def menus():
    """(step_id, option) for every async_show_menu call in config_flow.py."""
    for node in ast.walk(FLOW):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == (
            "async_show_menu"
        ):
            step = keyword(node, "step_id").value
            for option in keyword(node, "menu_options").elts:
                yield step, option.value


def options_steps():
    """Literal step IDs plus the generated category/details steps."""
    steps = {"init", *CATEGORIES, *(f"{c}_details" for c in CATEGORIES)}
    for node in ast.walk(FLOW):
        if isinstance(node, ast.Call):
            step = keyword(node, "step_id")
            if isinstance(step, ast.Constant) and step.value != "user":
                steps.add(step.value)
    return sorted(steps)


def schema_fields():
    """Every vol.Required/vol.Optional field name used in a form."""
    return sorted(
        {
            node.args[0].value
            for node in ast.walk(FLOW)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") in ("Required", "Optional")
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }
    )


def sensor_translations():
    tree = ast.parse((ROOT / "sensor.py").read_text())
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        values = {
            target.id: statement.value
            for statement in cls.body
            if isinstance(statement, ast.Assign)
            for target in statement.targets
            if isinstance(target, ast.Name)
        }
        if "_attr_translation_key" in values:
            yield (
                values["_attr_translation_key"].value,
                [item.value for item in values["_attr_options"].elts],
            )


def error_codes():
    source = (ROOT / "models.py").read_text() + (ROOT / "config_flow.py").read_text()
    codes = set(re.findall(r'ValueError\("(\w+)"\)', source))
    codes |= set(re.findall(r'errors=\{"base": "(\w+)"\}', source))
    return sorted(codes)


def test_strings_and_english_are_identical():
    assert TRANSLATIONS["strings"] == TRANSLATIONS["en"]


@pytest.mark.parametrize("language", ["en", "nl"])
def test_languages_have_identical_keys_and_no_empty_labels(language):
    reference = {path for path, _ in leaves(TRANSLATIONS["strings"])}
    assert {path for path, _ in leaves(TRANSLATIONS[language])} == reference
    empty = [path for path, value in leaves(TRANSLATIONS[language]) if not value]
    assert not empty


@pytest.mark.parametrize("language", list(FILES))
@pytest.mark.parametrize(("step", "option"), list(menus()))
def test_every_menu_option_has_a_label(language, step, option):
    assert label(language, "options", "step", step, "menu_options", option)


def test_menu_contains_central_configuration():
    assert ("init", "building") in list(menus())
    assert label("nl", "options", "step", "init", "menu_options", "building") == (
        "Centrale configuratie"
    )


@pytest.mark.parametrize("language", list(FILES))
@pytest.mark.parametrize("step", options_steps())
def test_every_options_step_has_a_title(language, step):
    assert label(language, "options", "step", step, "title")


@pytest.mark.parametrize("language", list(FILES))
@pytest.mark.parametrize("field", schema_fields())
def test_every_form_field_has_a_label(language, field):
    sections = TRANSLATIONS[language]["options"]["step"].values()
    config = TRANSLATIONS[language]["config"]["step"].values()
    assert any(field in step.get("data", {}) for step in (*sections, *config))


@pytest.mark.parametrize("language", list(FILES))
@pytest.mark.parametrize("code", error_codes())
def test_every_error_has_a_message(language, code):
    assert label(language, "options", "error", code)


@pytest.mark.parametrize("language", list(FILES))
@pytest.mark.parametrize(("key", "states"), list(sensor_translations()))
def test_every_sensor_state_has_a_label(language, key, states):
    assert label(language, "entity", "sensor", key, "name")
    for state in states:
        assert label(language, "entity", "sensor", key, "state", state)
