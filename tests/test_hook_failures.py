"""Failure behaviour (D12): unreadable input blocks, internal errors fail closed only off defaults."""
from __future__ import annotations

import json

import pytest

from hermes_agent_mixer.core import store as store_mod
from tests.cli_driver import rig  # noqa: F401


@pytest.mark.parametrize("harness", ["claude", "codex", "gemini"])
@pytest.mark.parametrize("raw", ["this is not json", "", "[1]", "42", '"str"'])
def test_unreadable_input_exits_2_with_a_reason_on_stderr(rig, harness, raw):
    rc, out, err = rig.run(["hook", harness], raw)
    assert rc == 2 and err.strip() and out == ""


def test_an_unknown_harness_is_a_usage_error(rig):
    rc, out, err = rig.run(["hook", "vim"], "{}")
    assert rc != 0 and "claude" in (out + err)


def payload(rig):
    return {"session_id": "S1", "prompt_id": "p1", "cwd": str(rig.proj), "hook_event_name": "PreToolUse",
            "tool_name": "Write", "tool_input": {"file_path": str(rig.proj / "a.py"), "content": "x"}}


def break_store(monkeypatch):
    def boom(self):
        raise store_mod.StoreLockTimeout("could not lock (test)")
    monkeypatch.setattr(store_mod.FileStore, "transaction", boom)


def test_an_internal_error_with_a_dial_off_its_default_denies_and_names_doctor(rig, monkeypatch):
    rig.run(["--saved", "edits", "plan"])
    break_store(monkeypatch)
    rc, data, _ = rig.hook("claude", payload(rig))
    out = data["hookSpecificOutput"]
    assert rc == 0 and out["permissionDecision"] == "deny"
    assert "agent-mixer doctor" in out["permissionDecisionReason"] and "could not lock" in out["permissionDecisionReason"]


def test_an_internal_error_with_all_defaults_stays_silent(rig, monkeypatch):
    break_store(monkeypatch)
    rc, out, err = rig.run(["hook", "claude"], json.dumps(payload(rig)))
    assert rc == 0 and out == ""


def test_an_internal_error_when_the_session_has_state_denies(rig, monkeypatch):
    rig.run(["--session", "S1", "edits", "plan"])
    break_store(monkeypatch)
    _, data, _ = rig.hook("claude", payload(rig))
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_unreadable_saved_settings_fail_closed(rig):
    rig.settings_file.parent.mkdir(parents=True)
    rig.settings_file.write_text("{broken", encoding="utf-8")
    _, data, _ = rig.hook("claude", payload(rig))
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "agent-mixer doctor" in data["hookSpecificOutput"]["permissionDecisionReason"]


def test_codex_and_gemini_failures_use_their_own_deny_shape(rig, monkeypatch):
    rig.run(["--saved", "edits", "plan"])
    break_store(monkeypatch)
    codex = {"session_id": "S1", "cwd": str(rig.proj), "hook_event_name": "PreToolUse", "turn_id": "t",
             "tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert rig.hook("codex", codex)[1]["hookSpecificOutput"]["permissionDecision"] == "deny"
    gem = {"session_id": "S1", "cwd": str(rig.proj), "hook_event_name": "BeforeTool", "tool_name": "run_shell_command",
           "tool_input": {"command": "ls"}}
    assert rig.hook("gemini", gem)[1]["decision"] == "deny"


def test_a_failing_prompt_hook_never_blocks_the_user(rig, monkeypatch):
    rig.run(["--saved", "edits", "plan"])
    break_store(monkeypatch)
    rc, out, _ = rig.run(["hook", "claude"], json.dumps({"session_id": "S1", "cwd": str(rig.proj),
                                                         "hook_event_name": "UserPromptSubmit", "prompt": "go"}))
    assert rc == 0 and out == ""
