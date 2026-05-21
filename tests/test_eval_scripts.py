"""Regression tests for eval script improvements in task templates.

Verifies that all 4 builtin task templates have:
1. Complete event sequence (focus, beforeinput, input, keyup, change, blur)
   in both fill_password and fill_username steps.
2. Hidden password field scoring fix (!vis(el)) s-=5 and filter(el=>ok(el))).
3. Valid JSON structure.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

TASKS_DIR = Path(__file__).resolve().parents[1] / "tasks"
TEMPLATE_FILES = ["default.json", "select_isp.json", "click_isp.json", "no_isp.json"]

REQUIRED_EVENTS = ["focus", "beforeinput", "input", "keyup", "change", "blur"]


def _load_templates() -> dict[str, dict]:
    """Load all task template files and return {filename: parsed_dict}."""
    templates = {}
    for name in TEMPLATE_FILES:
        path = TASKS_DIR / name
        with open(path, encoding="utf-8") as f:
            templates[name] = json.load(f)
    return templates


def _get_step_script(template: dict, step_id: str) -> str:
    """Extract the script string for a given step id from a template."""
    for step in template["steps"]:
        if step["id"] == step_id:
            return step["script"]
    raise KeyError(f"Step '{step_id}' not found in template")


@pytest.fixture(scope="module")
def templates():
    """Load all templates once for the module."""
    return _load_templates()


# --- JSON validity tests ---

class TestJsonValidity:
    """All 4 template files must parse as valid JSON."""

    @pytest.mark.parametrize("filename", TEMPLATE_FILES)
    def test_valid_json(self, filename):
        path = TASKS_DIR / filename
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), f"{filename} root is not a dict"
        assert "steps" in data, f"{filename} missing 'steps' key"


# --- Event sequence tests ---

class TestEventSequence:
    """fill_password and fill_username must dispatch all 6 events."""

    @pytest.mark.parametrize("filename", TEMPLATE_FILES)
    def test_fill_username_has_all_events(self, templates, filename):
        script = _get_step_script(templates[filename], "fill_username")
        for event in REQUIRED_EVENTS:
            assert f"'{event}'" in script, (
                f"{filename} fill_username missing event: {event}"
            )

    @pytest.mark.parametrize("filename", TEMPLATE_FILES)
    def test_fill_password_has_all_events(self, templates, filename):
        script = _get_step_script(templates[filename], "fill_password")
        for event in REQUIRED_EVENTS:
            assert f"'{event}'" in script, (
                f"{filename} fill_password missing event: {event}"
            )


# --- Hidden password field scoring fix tests ---

class TestHiddenPasswordScoring:
    """fill_password must have hidden field penalty and correct filter."""

    @pytest.mark.parametrize("filename", TEMPLATE_FILES)
    def test_hidden_password_penalty(self, templates, filename):
        """fill_password must penalize hidden password fields: !vis(el)) s-=5."""
        script = _get_step_script(templates[filename], "fill_password")
        assert "!vis(el)) s-=5" in script, (
            f"{filename} fill_password missing hidden password penalty (!vis(el)) s-=5"
        )

    @pytest.mark.parametrize("filename", TEMPLATE_FILES)
    def test_filter_uses_ok_not_vis_and_ok(self, templates, filename):
        """fill_password must use filter(el=>ok(el)), not filter(el=>vis(el)&&ok(el))."""
        script = _get_step_script(templates[filename], "fill_password")
        assert "filter(el=>ok(el))" in script, (
            f"{filename} fill_password should use filter(el=>ok(el))"
        )
        # Ensure the old pattern is NOT present
        assert "filter(el=>vis(el)&&ok(el))" not in script, (
            f"{filename} fill_password still uses old filter(el=>vis(el)&&ok(el))"
        )
