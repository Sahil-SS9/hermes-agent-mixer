"""Saved settings, the Desktop form and the board (B7, QW1, QW6, D6)."""
from __future__ import annotations

from pathlib import Path

import pytest
import tomllib
import yaml

from hermes_agent_mixer.core import settings
from tests.hermes_driver import mixer, tool, turn, verdict

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
SCHEMA = MANIFEST["config_schema"]


def test_manifest_is_version_2_with_tags_and_the_new_hooks():
    assert MANIFEST["manifest_version"] == 2
    assert MANIFEST["tags"] and all(isinstance(t, str) for t in MANIFEST["tags"])
    assert {"pre_tool_call", "pre_llm_call", "subagent_start", "subagent_stop"} <= set(MANIFEST["provides_hooks"])
    assert str(MANIFEST["version"]) == "0.2.0"


def test_versions_agree_everywhere():
    import hermes_agent_mixer

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == hermes_agent_mixer.__version__ == str(MANIFEST["version"])


def test_every_field_has_a_label_and_a_description():
    assert set(SCHEMA) == {"edits", "scope", "lines", "deps", "extra_write_tools"}
    for key, spec in SCHEMA.items():
        assert spec.get("label") and spec.get("description"), key


def test_edits_and_deps_are_dropdowns():
    assert SCHEMA["edits"]["type"] == "str" and set(SCHEMA["edits"]["choices"]) == {"ask", "auto", "plan"}
    assert SCHEMA["edits"]["default"] == "auto"
    assert SCHEMA["deps"]["type"] == "str" and set(SCHEMA["deps"]["choices"]) == {"allow", "ask", "block"}
    assert SCHEMA["deps"]["default"] == "ask"


def test_lines_is_an_int_with_zero_meaning_off():
    assert SCHEMA["lines"]["type"] == "int" and SCHEMA["lines"]["default"] == 0


def test_scope_and_extra_write_tools_are_lists():
    assert SCHEMA["scope"]["type"] == "list" and SCHEMA["extra_write_tools"]["type"] == "list"


def test_the_manifest_defaults_equal_the_engine_defaults():
    for key, spec in SCHEMA.items():
        assert spec["default"] == settings.DEFAULTS[key], key


def test_mixer_command_has_an_args_hint(fresh_plugin):
    ctx = fresh_plugin()
    assert ctx.commands["mixer"]["args_hint"]


# -- resolution --------------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [("off", 0), ("0", 0), ("50", 50), (50, 50), (0, 0), (" 12 ", 12), (50.0, 50)])
def test_lines_reads_int_and_legacy_text(raw, expected):
    assert settings.resolve({"lines": raw}).values["lines"] == expected


@pytest.mark.parametrize("raw", ["plna", "", 5, None, ["ask"], "PLAN "])
def test_invalid_edits_fall_back_to_ask_never_to_the_most_permissive(raw):
    eff = settings.resolve({"edits": raw})
    if raw is None:
        assert eff.values["edits"] == "auto" and eff.sources["edits"] == "default"
    elif raw == "PLAN ":
        assert eff.values["edits"] == "plan" and not eff.warnings
    else:
        assert eff.values["edits"] == "ask" and eff.warnings and "edits" in eff.warnings[0]


def test_invalid_deps_fall_back_to_ask():
    eff = settings.resolve({"deps": "alow"})
    assert eff.values["deps"] == "ask" and "alow" in eff.warnings[0]


def test_invalid_lines_become_off_with_a_warning():
    eff = settings.resolve({"lines": "lots"})
    assert eff.values["lines"] == 0 and eff.warnings


def test_a_session_override_wins_and_is_labelled():
    eff = settings.resolve({"edits": "ask", "deps": "block"}, {"edits": "plan"})
    assert eff.sources == {"edits": "session", "scope": "default", "lines": "default", "deps": "saved",
                           "extra_write_tools": "default"}


def test_a_saved_value_equal_to_the_default_is_labelled_default():
    assert settings.resolve({"edits": "auto"}).sources["edits"] == "default"


def test_scope_accepts_a_single_string():
    assert settings.resolve({"scope": "src/**"}).values["scope"] == ["src/**"]


# -- through the Hermes adapter ------------------------------------------------------------------


def test_a_saved_typo_asks_and_the_board_flags_it(fresh_plugin, monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_SESSION_ID", "s")
    monkeypatch.chdir(tmp_path)
    ctx = fresh_plugin({"edits": "plna"})
    turn(ctx, "s")
    assert verdict(tool(ctx, "write_file", {"path": "a.py", "content": "x\n"}, "s")) == "approve"
    board = mixer(ctx, "")
    assert "plna" in board and "not valid" in board


def test_the_board_labels_sources_and_lines_left(fresh_plugin, monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_SESSION_ID", "s")
    monkeypatch.chdir(tmp_path)
    ctx = fresh_plugin({"lines": 50})
    mixer(ctx, "deps block")
    turn(ctx, "s")
    tool(ctx, "write_file", {"path": "a.py", "content": "1\n2\n3\n"}, "s")
    board = mixer(ctx, "")
    assert "47 left" in board and "(session)" in board and "(saved)" in board and "(default)" in board


def test_extra_write_tools_are_treated_like_write_file(fresh_plugin, monkeypatch, tmp_path):
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HERMES_SESSION_ID", "s")
    ctx = fresh_plugin({"scope": ["src/**"], "extra_write_tools": ["mcp__fs__write*"]})
    turn(ctx, "s")
    assert verdict(tool(ctx, "mcp__fs__write_file", {"path": "README.md", "content": "x"}, "s")) == "block"
    assert verdict(tool(ctx, "mcp__fs__write_file", {"path": "src/a.py", "content": "x"}, "s")) == "allow"
    assert verdict(tool(ctx, "mcp__fs__read_file", {"path": "README.md"}, "s")) == "allow"
    for key in ("file_path", "filename", "target"):
        assert verdict(tool(ctx, "mcp__fs__write_x", {key: "README.md"}, "s")) == "block"
