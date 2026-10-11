"""Tests for the /mixer board, subcommands, save and reset."""

from __future__ import annotations

import pytest

from hermes_agent_mixer.core import board, mixer as mixer_mod
from hermes_agent_mixer.hermes import host as session_key_mod


def _mixer(settings=None):
    store = dict(settings or {})

    def config_get(key, default=None):
        return store.get(key, default)

    def config_set(key, value):
        store[key] = value

    return mixer_mod.Mixer(config_get=config_get), config_set


# -- subcommand behaviour -----------------------------------------------------


def test_show_renders_board_with_knob_values():
    mixer, _ = _mixer({"scope": ["src/**", "tests/**"]})
    text = board.handle_command("", mixer, "sess-abc")
    assert "Agent Mixer" in text
    assert "edits" in text and "auto" in text and "[ACTIVE]" in text
    assert "src/**" in text and "tests/**" in text
    assert "deps" in text and "ask" in text
    assert "approvals" in text  # the Hermes approvals rule is stated in words


def test_show_shows_lines_off_or_budget():
    mixer, _ = _mixer({"lines": 200})
    text = board.handle_command("", mixer, "s")
    assert "200" in text and "this turn" in text
    mixer2, _ = _mixer({"lines": "off"})
    text2 = board.handle_command("", mixer2, "s")
    assert "off" in text2.lower()


def test_edits_subcommand_sets_override():
    mixer, _ = _mixer()
    text = board.handle_command("edits plan", mixer, "sess-a")
    assert "plan" in text
    assert mixer.settings_for("sess-a")["edits"] == "plan"


def test_edits_rejects_unknown_mode():
    mixer, _ = _mixer()
    text = board.handle_command("edits yolo", mixer, "sess-a")
    assert "unknown" in text.lower() or "invalid" in text.lower()
    assert mixer.settings_for("sess-a")["edits"] == "auto"


def test_scope_add_remove_clear_show():
    mixer, _ = _mixer()
    board.handle_command("scope add src/**", mixer, "sess-a")
    board.handle_command("scope add tests/**", mixer, "sess-a")
    shown = board.handle_command("scope show", mixer, "sess-a")
    assert "src/**" in shown and "tests/**" in shown
    board.handle_command("scope remove src/**", mixer, "sess-a")
    assert mixer.settings_for("sess-a")["scope"] == ["tests/**"]
    board.handle_command("scope clear", mixer, "sess-a")
    assert mixer.settings_for("sess-a")["scope"] == []


def test_lines_sets_positive_int():
    mixer, _ = _mixer()
    board.handle_command("lines 150", mixer, "sess-a")
    assert mixer.settings_for("sess-a")["lines"] == 150


def test_lines_rejects_zero_and_garbage():
    mixer, _ = _mixer()
    zero = board.handle_command("lines 0", mixer, "sess-a")
    assert "off" in zero.lower() or "positive" in zero.lower()
    garbage = board.handle_command("lines many", mixer, "sess-a")
    assert "unknown" in garbage.lower() or "off" in garbage.lower()
    assert mixer.settings_for("sess-a")["lines"] == "off"


def test_lines_off_disables():
    mixer, _ = _mixer({"lines": 150})
    board.handle_command("lines off", mixer, "sess-a")
    assert mixer.settings_for("sess-a")["lines"] == "off"


def test_deps_subcommand_modes():
    mixer, _ = _mixer()
    board.handle_command("deps block", mixer, "sess-a")
    assert mixer.settings_for("sess-a")["deps"] == "block"
    bad = board.handle_command("deps maybe", mixer, "sess-a")
    assert "unknown" in bad.lower() or "invalid" in bad.lower()


def test_unknown_subcommand_prints_usage():
    mixer, _ = _mixer()
    text = board.handle_command("destroy everything", mixer, "sess-a")
    assert "usage" in text.lower()


def test_state_never_mutated_by_bad_input():
    mixer, _ = _mixer()
    board.handle_command("edits nope", mixer, "s")
    board.handle_command("deps nope", mixer, "s")
    board.handle_command("lines x", mixer, "s")
    assert mixer.settings_for("s") == {"edits": "auto", "scope": [], "lines": "off", "deps": "ask"}


# -- save and reset -----------------------------------------------------------


def test_save_writes_current_session_settings_to_config():
    mixer, config_set = _mixer()
    board.handle_command("edits ask", mixer, "sess-s")
    board.handle_command("scope add src/**", mixer, "sess-s")
    board.handle_command("lines 120", mixer, "sess-s")
    board.handle_command("deps block", mixer, "sess-s")
    text = board.handle_command("save", mixer, "sess-s", save=config_set)
    assert "saved" in text.lower()
    store = {}
    board.handle_command("save", mixer, "sess-s", save=lambda k, v: store.__setitem__(k, v))
    assert store["edits"] == "ask"
    assert store["scope"] == ["src/**"]
    assert store["lines"] == "120", "saved text must match the host's manifest type"
    assert mixer.settings_for("sess-s")["lines"] == 120
    assert store["deps"] == "block"


def test_save_without_sink_reports_error():
    mixer, _ = _mixer()
    text = board.handle_command("save", mixer, "s")
    assert "not available" in text.lower() or "error" in text.lower()


def test_reset_clears_session_overrides():
    mixer, _ = _mixer({"edits": "ask"})
    board.handle_command("edits plan", mixer, "sess-s")
    board.handle_command("lines 50", mixer, "sess-s")
    assert mixer.settings_for("sess-s")["edits"] == "plan"
    text = board.handle_command("reset", mixer, "sess-s")
    assert "reset" in text.lower()
    assert mixer.settings_for("sess-s")["edits"] == "ask"
    assert mixer.settings_for("sess-s")["lines"] == "off"


def test_reset_with_no_overrides_reports_defaults():
    mixer, _ = _mixer()
    text = board.handle_command("reset", mixer, "s")
    assert "reset" in text.lower() or "default" in text.lower()


def test_board_shows_session_reference():
    mixer, _ = _mixer()
    text = board.handle_command("", mixer, "sess-9f2a")
    assert "sess-9f2a"[:4] in text or "session" in text.lower()


def test_board_lines_show_used_of_budget():
    mixer, _ = _mixer({"lines": 200})
    mixer.lines_state.add("s-x", "task-1", 87)
    text = board.handle_command("", mixer, "s-x")
    assert "87" in text and "200" in text


# -- session key resolution ----------------------------------------------------


def test_session_key_from_os_environ(monkeypatch):
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    monkeypatch.setattr(session_key_mod, "_gateway_get_session_env", None, raising=False)
    monkeypatch.setenv("HERMES_SESSION_ID", "sess-env")
    assert session_key_mod.current_session_key() == "sess-env"


def test_session_key_empty_without_host_context(monkeypatch):
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    monkeypatch.setattr(session_key_mod, "_gateway_get_session_env", None, raising=False)
    assert session_key_mod.current_session_key() == ""


def test_gateway_session_id_preferred_over_environ(monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_ID", "sess-env")
    monkeypatch.setattr(session_key_mod, "_gateway_get_session_env", lambda name: "sess-gateway", raising=False)
    assert session_key_mod.current_session_key() == "sess-gateway"


# -- plugin-level integration: command to hook over one session ------------------


def test_command_change_visible_to_hook_same_session(tmp_path, monkeypatch):
    """The CLI publishes HERMES_SESSION_ID; handler and hooks bind the same key."""
    from hermes_agent_mixer.hermes import plugin as mixer_plugin
    from tests import conftest as conftest_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    monkeypatch.setattr(mixer_plugin, "_current_session_key", lambda: "sess-env", raising=False)
    mixer_plugin.reset_mixer()
    ctx = conftest_mod.FakeCtx()
    mixer_plugin.register(ctx)
    handler = ctx.commands["mixer"]["handler"]
    handler("edits plan")
    hook = ctx.hooks["pre_tool_call"][0]
    result = hook(tool_name="execute_code", args={"code": "1"}, task_id="t1",
                  session_id="sess-env")
    mixer_plugin.reset_mixer()
    assert result is not None
    assert result["action"] == "block"


def test_command_handler_without_session_falls_back_to_global(tmp_path, monkeypatch):
    """No host session context: /mixer edits the process-wide fallback identity."""
    from hermes_agent_mixer.hermes import plugin as mixer_plugin
    from tests import conftest as conftest_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mixer_plugin, "_current_session_key", lambda: "", raising=False)
    mixer_plugin.reset_mixer()
    ctx = conftest_mod.FakeCtx()
    mixer_plugin.register(ctx)
    handler = ctx.commands["mixer"]["handler"]
    handler("edits plan")
    mixer = mixer_plugin.get_mixer()
    assert mixer.settings_for("")["edits"] == "plan"
    mixer_plugin.reset_mixer()


def test_subagent_session_does_not_inherit_parent_override(tmp_path, monkeypatch):
    """Overrides bind to the session id from the host; a child subagent session runs defaults."""
    from hermes_agent_mixer.hermes import plugin as mixer_plugin
    from tests import conftest as conftest_mod

    monkeypatch.chdir(tmp_path)
    mixer_plugin.reset_mixer()
    ctx = conftest_mod.FakeCtx()
    mixer_plugin.register(ctx)
    handler = ctx.commands["mixer"]["handler"]
    handler("edits plan")
    hook = ctx.hooks["pre_tool_call"][0]
    child = hook(tool_name="execute_code", args={"code": "1"}, task_id="child-task",
                 session_id="child-session")
    mixer_plugin.reset_mixer()
    assert child is None, "subagent sessions must use defaults, not the parent's overrides"


def test_subagent_counters_isolated_from_parent(tmp_path, monkeypatch):
    from hermes_agent_mixer.hermes import plugin as mixer_plugin
    from tests import conftest as conftest_mod

    monkeypatch.chdir(tmp_path)
    mixer_plugin.reset_mixer()
    ctx = conftest_mod.FakeCtx({"lines": 3})
    mixer_plugin.register(ctx)
    hook = ctx.hooks["pre_tool_call"][0]
    ok = hook(tool_name="write_file", args={"path": "a.txt", "content": "1\n2\n3\n"}, task_id="t1",
              session_id="parent-session")
    child = hook(tool_name="write_file", args={"path": "a.txt", "content": "1\n2\n3\n"}, task_id="child-turn",
                 session_id="child-session")
    mixer_plugin.reset_mixer()
    assert ok is None, "parent's first call must fit the configured budget"
    assert child is None, "child session starts with a fresh budget"