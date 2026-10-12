"""Presets (QW12): named dial bundles through the same Target path as every other command."""
from __future__ import annotations

import json

from tests.cli_driver import Rig


def test_preset_show_lists_all_four_bundles(rig: Rig):
    rc, out, err = rig.run(["preset", "show"])
    assert rc == 0, err
    for name in ("auditor", "builder", "explorer", "surgical"):
        assert name in out


def test_preset_builder_sets_the_four_dials(rig: Rig):
    rc, out, err = rig.run(["--saved", "preset", "builder"])
    assert rc == 0, err
    assert "builder" in out
    data = json.loads(rig.settings_file.read_text())
    assert data == {"edits": "auto", "scope": [], "lines": 0, "deps": "allow"}


def test_preset_surgical_sets_scope_lines_and_ask(rig: Rig):
    rc, _, err = rig.run(["--saved", "preset", "surgical"])
    assert rc == 0, err
    data = json.loads(rig.settings_file.read_text())
    assert data["scope"] == ["src/**", "tests/**"]
    assert data["lines"] == 30
    assert data["deps"] == "ask"
    assert data["edits"] == "auto"


def test_preset_on_a_session_not_saved(rig: Rig):
    rc, _, err = rig.run(["--session", "P1", "preset", "auditor"])
    assert rc == 0, err
    # the saved file must stay untouched; the change lives in the session
    assert not rig.settings_file.exists()
    # and the hook path sees the session dial
    payload = {"session_id": "P1", "prompt_id": "p1", "cwd": str(rig.proj), "permission_mode": "default",
               "hook_event_name": "PreToolUse", "tool_name": "Write", "tool_use_id": "t",
               "tool_input": {"file_path": str(rig.proj / "src" / "a.py"), "content": "x"}}
    rc2, data, _ = rig.hook("claude", payload)
    assert rc2 == 0
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "plan mode" in data["hookSpecificOutput"]["permissionDecisionReason"].lower()


def test_unknown_preset_changes_nothing(rig: Rig):
    rc, out, _ = rig.run(["--saved", "preset", "nonsense"])
    assert "unknown preset" in out.lower()
    assert not rig.settings_file.exists()
    # a valid preset still works afterwards
    rc, out, _ = rig.run(["--saved", "preset", "builder"])
    assert rc == 0


def test_preset_is_case_insensitive(rig: Rig):
    rc, out, _ = rig.run(["--saved", "preset", "SURGICAL"])
    assert rc == 0 and "surgical" in out


def test_preset_reply_names_only_changed_dials_values(rig: Rig):
    _rc, out, _ = rig.run(["--session", "P2", "preset", "auditor"])
    assert "edits=plan" in out and "scope=(no limit)" in out and "lines=off" in out
    # session note appears once, not four times
    assert out.count("this session only") == 1


def test_preset_show_via_bare_word(rig: Rig):
    rc, out, _ = rig.run(["preset"])
    assert rc == 0 and "Presets" in out


def test_board_after_preset_shows_sources(rig: Rig):
    rig.run(["--session", "P3", "preset", "surgical"])
    _rc, board, _ = rig.run(["--session", "P3", "board"])
    assert "surgical" not in board  # presets are not a source; the dials are
    assert "session" in board
    assert "src/**, tests/**" in board
