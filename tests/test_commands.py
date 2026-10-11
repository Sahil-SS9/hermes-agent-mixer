"""The /mixer board, subcommands, save and reset (host-neutral grammar)."""

from __future__ import annotations

from hermes_agent_mixer.core import board
from hermes_agent_mixer.core.mixer import Mixer
from hermes_agent_mixer.core.targets import SessionTarget


def _mixer(settings=None):
    store = dict(settings or {})
    mixer = Mixer(saved=lambda: dict(store))
    return mixer, store


def _cmd(mixer, raw, sid="sess-a", store=None):
    target = SessionTarget(mixer, sid, write_saved=None if store is None else store.__setitem__)
    return board.handle_command(raw, target)


def _eff(mixer, sid="sess-a"):
    return mixer.effective(sid)


# -- subcommand behaviour -----------------------------------------------------


def test_show_renders_board_with_knob_values():
    mixer, _ = _mixer({"scope": ["src/**", "tests/**"]})
    text = _cmd(mixer, "", "sess-abc")
    assert "Agent Mixer" in text
    assert "edits" in text and "auto" in text and "[ACTIVE]" in text
    assert "src/**" in text and "tests/**" in text
    assert "deps" in text and "ask" in text
    assert "approvals" in text  # the approvals rule is stated in words


def test_show_shows_lines_off_or_budget():
    mixer, _ = _mixer({"lines": 200})
    text = _cmd(mixer, "", "s")
    assert "200" in text and "this turn" in text
    mixer2, _ = _mixer({"lines": "off"})
    assert "off" in _cmd(mixer2, "", "s").lower()


def test_board_alias_shows_the_board():
    mixer, _ = _mixer()
    assert _cmd(mixer, "board") == _cmd(mixer, "")


def test_edits_subcommand_sets_override():
    mixer, _ = _mixer()
    assert "plan" in _cmd(mixer, "edits plan")
    assert _eff(mixer)["edits"] == "plan"


def test_edits_rejects_unknown_mode():
    mixer, _ = _mixer()
    text = _cmd(mixer, "edits yolo")
    assert "unknown" in text.lower() or "invalid" in text.lower()
    assert _eff(mixer)["edits"] == "auto"


def test_scope_add_remove_clear_show():
    mixer, _ = _mixer()
    _cmd(mixer, "scope add src/**")
    _cmd(mixer, "scope add tests/**")
    shown = _cmd(mixer, "scope show")
    assert "src/**" in shown and "tests/**" in shown
    _cmd(mixer, "scope remove src/**")
    assert _eff(mixer)["scope"] == ["tests/**"]
    _cmd(mixer, "scope clear")
    assert _eff(mixer)["scope"] == []


def test_lines_sets_positive_int():
    mixer, _ = _mixer()
    _cmd(mixer, "lines 150")
    assert _eff(mixer)["lines"] == 150


def test_lines_zero_means_off_and_garbage_is_rejected():
    mixer, _ = _mixer({"lines": 40})
    assert "off" in _cmd(mixer, "lines 0")
    assert _eff(mixer)["lines"] == 0
    mixer, _ = _mixer()
    garbage = _cmd(mixer, "lines many")
    assert "unknown" in garbage.lower()
    negative = _cmd(mixer, "lines -3")
    assert "positive" in negative.lower()
    assert _eff(mixer)["lines"] == 0


def test_lines_off_disables():
    mixer, _ = _mixer({"lines": 150})
    _cmd(mixer, "lines off")
    assert _eff(mixer)["lines"] == 0


def test_deps_subcommand_modes():
    mixer, _ = _mixer()
    _cmd(mixer, "deps block")
    assert _eff(mixer)["deps"] == "block"
    bad = _cmd(mixer, "deps maybe")
    assert "unknown" in bad.lower() or "invalid" in bad.lower()


def test_unknown_subcommand_prints_usage():
    mixer, _ = _mixer()
    assert "usage" in _cmd(mixer, "destroy everything").lower()


def test_state_never_mutated_by_bad_input():
    mixer, _ = _mixer()
    for raw in ("edits nope", "deps nope", "lines x", "scope fly", "save lines x", "save edits plna"):
        _cmd(mixer, raw, "s")
    eff = _eff(mixer, "s")
    assert eff.values == {"edits": "auto", "scope": [], "lines": 0, "deps": "ask", "extra_write_tools": []}
    assert set(eff.sources.values()) == {"default"}


# -- save and reset -----------------------------------------------------------


def test_save_writes_current_session_settings_to_config():
    mixer, store = _mixer()
    for raw in ("edits ask", "scope add src/**", "lines 120", "deps block"):
        _cmd(mixer, raw, "sess-s")
    text = _cmd(mixer, "save", "sess-s", store)
    assert "saved" in text.lower()
    assert store["edits"] == "ask" and store["scope"] == ["src/**"] and store["deps"] == "block"
    assert store["lines"] == 120 and isinstance(store["lines"], int)


def test_save_one_dial_sets_a_saved_default_directly():
    mixer, store = _mixer()
    assert "saved" in _cmd(mixer, "save deps block", "s", store)
    assert store == {"deps": "block"}
    _cmd(mixer, "save lines 30", "s", store)
    _cmd(mixer, "save lines off", "s", store)
    assert store["lines"] == 0
    _cmd(mixer, "save scope add a/** b/**", "s", store)
    _cmd(mixer, "save scope remove a/**", "s", store)
    assert store["scope"] == ["b/**"]
    _cmd(mixer, "save scope clear", "s", store)
    assert store["scope"] == []
    assert "unknown" in _cmd(mixer, "save speed 9", "s", store).lower()


def test_save_without_sink_reports_error():
    mixer, _ = _mixer()
    text = _cmd(mixer, "save", "s")
    assert "not available" in text.lower()


def test_reset_clears_session_overrides():
    mixer, _ = _mixer({"edits": "ask"})
    _cmd(mixer, "edits plan", "sess-s")
    _cmd(mixer, "lines 50", "sess-s")
    assert _eff(mixer, "sess-s")["edits"] == "plan"
    assert "reset" in _cmd(mixer, "reset", "sess-s").lower()
    assert _eff(mixer, "sess-s")["edits"] == "ask"
    assert _eff(mixer, "sess-s")["lines"] == 0


def test_reset_with_no_overrides_reports_reset():
    mixer, _ = _mixer()
    assert "reset" in _cmd(mixer, "reset", "s").lower()


def test_board_shows_session_reference():
    mixer, _ = _mixer()
    assert "sess-9f2a" in _cmd(mixer, "", "sess-9f2a")


def test_board_lines_show_left_of_budget():
    mixer, _ = _mixer({"lines": 200})
    mixer.begin_turn("s-x", "t1")
    from tests.helpers import write
    from hermes_agent_mixer.core.ports import Ports

    mixer.decide("s-x", write("a.py", "1\n" * 87), Ports())
    text = _cmd(mixer, "", "s-x")
    assert "113 left" in text and "200" in text


def test_commands_work_through_the_hermes_adapter_for_the_same_session(tmp_path, monkeypatch, fresh_plugin):
    from tests.hermes_driver import mixer as run_mixer, tool

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HERMES_SESSION_ID", "sess-env")
    ctx = fresh_plugin()
    run_mixer(ctx, "edits plan")
    assert tool(ctx, "execute_code", {"code": "1"}, "sess-env")["action"] == "block"
    assert tool(ctx, "execute_code", {"code": "1"}, "someone-else") is None


def test_command_without_any_bound_session_changes_nothing(tmp_path, monkeypatch, fresh_plugin):
    from tests.hermes_driver import mixer as run_mixer, tool

    monkeypatch.chdir(tmp_path)
    ctx = fresh_plugin()
    reply = run_mixer(ctx, "edits plan")
    assert "save" in reply.lower()
    assert tool(ctx, "execute_code", {"code": "1"}, "s") is None
