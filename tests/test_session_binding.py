"""Session identity on each Hermes surface (B1, QW11, D1), driven through the real upstream
gateway.session_context (tests/upstream_shim), never a mock of it."""
from __future__ import annotations

import os

import pytest

from tests.hermes_driver import bound, mixer, tool, turn, unbound, verdict

GW_A = {"platform": "discord", "chat_id": "111", "chat_type": "group", "session_key": "agent:main:discord:group:111"}
GW_B = {"platform": "discord", "chat_id": "222", "chat_type": "group", "session_key": "agent:main:discord:group:222"}
TUI_T = {"platform": "tui", "session_key": "tui-key-1", "session_id": "sess_T"}
TUI_U = {"platform": "tui", "session_key": "tui-key-2", "session_id": "sess_U"}


@pytest.fixture
def work(tmp_path, monkeypatch, host_shim):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.chdir(home)  # the gateway's systemd WorkingDirectory is HERMES_HOME
    monkeypatch.setenv("TERMINAL_CWD", str(proj))
    for var in ("HERMES_SESSION_ID", "HERMES_SESSION_KEY"):
        monkeypatch.delenv(var, raising=False)
    return {"path": "src/new.py", "content": "x\n"}


def test_gateway_session_id_is_never_taken_from_os_environ(work, fresh_plugin, monkeypatch):
    """Rewrite of the 0.1 test that mocked behaviour the gateway does not have: the gateway binds the
    session key and an EMPTY session id, so os.environ (the last agent built, chat B) must not leak in."""
    monkeypatch.setenv("HERMES_SESSION_ID", "sess_B")
    ctx = fresh_plugin()
    with bound(**GW_A):
        reply = mixer(ctx, "edits plan")
    assert "sess_B" not in reply
    with bound(**GW_A):
        turn(ctx, "sess_A", platform="discord")
        a = verdict(tool(ctx, "write_file", work, "sess_A"))
    with bound(**GW_B):
        turn(ctx, "sess_B", platform="discord")
        b = verdict(tool(ctx, "write_file", work, "sess_B"))
    assert a == "block"  # a command sent before any turn is parked under the chat key, then applied
    assert b == "allow"


def test_gateway_command_mid_conversation_applies_to_that_chat_only(work, fresh_plugin, monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_ID", "sess_B")
    ctx = fresh_plugin()
    with bound(**GW_A):
        turn(ctx, "sess_A", platform="discord")
    with bound(**GW_B):
        turn(ctx, "sess_B", platform="discord")
    with bound(**GW_A):
        reply = mixer(ctx, "edits plan")
    assert "sess_B" not in reply and "sess_A" in reply
    with bound(**GW_A):
        turn(ctx, "sess_A", turn_id="t2", platform="discord")
        assert verdict(tool(ctx, "write_file", work, "sess_A", turn="t2")) == "block"
    with bound(**GW_B):
        turn(ctx, "sess_B", turn_id="t2", platform="discord")
        assert verdict(tool(ctx, "write_file", work, "sess_B", turn="t2")) == "allow"


def test_a_parked_change_names_this_chats_key_not_another_session(work, fresh_plugin, monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_ID", "sess_B")
    ctx = fresh_plugin()
    with bound(**GW_A):
        reply = mixer(ctx, "edits plan")
    assert GW_A["session_key"] in reply and "next turn" in reply
    assert GW_B["session_key"] not in reply


def test_gateway_hook_without_the_chat_context_uses_the_hook_session_id(work, fresh_plugin, monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_ID", "sess_B")
    ctx = fresh_plugin()
    with bound(**GW_A):
        mixer(ctx, "edits plan")
        turn(ctx, "sess_A", platform="discord")
    with bound(**GW_B):
        turn(ctx, "sess_B", platform="discord")
    assert unbound(lambda: verdict(tool(ctx, "write_file", work, "sess_A"))) == "block"
    assert unbound(lambda: verdict(tool(ctx, "write_file", work, "sess_B"))) == "allow"


def test_tui_binds_key_and_session_id(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(**TUI_T):
        mixer(ctx, "edits plan")
        turn(ctx, "sess_T", platform="tui")
        t = verdict(tool(ctx, "write_file", work, "sess_T"))
    with bound(**TUI_U):
        turn(ctx, "sess_U", platform="tui")
        u = verdict(tool(ctx, "write_file", work, "sess_U"))
    assert (t, u) == ("block", "allow")


def test_classic_cli_uses_os_environ_and_does_not_leak_into_the_next_session(work, fresh_plugin, monkeypatch):
    ctx = fresh_plugin()
    monkeypatch.setenv("HERMES_SESSION_ID", "sess_C")
    mixer(ctx, "edits plan")
    turn(ctx, "sess_C")
    assert verdict(tool(ctx, "write_file", work, "sess_C")) == "block"
    monkeypatch.setenv("HERMES_SESSION_ID", "sess_D")  # /new
    turn(ctx, "sess_D")
    assert verdict(tool(ctx, "write_file", work, "sess_D")) == "allow"


def test_unidentifiable_session_refuses_and_changes_nothing(work, fresh_plugin, monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_ID", "sess_B")
    ctx = fresh_plugin()
    with bound(platform="api_server"):
        reply = mixer(ctx, "edits plan")
        turn(ctx, "sess_B")
        assert verdict(tool(ctx, "write_file", work, "sess_B")) == "allow"
    assert "save" in reply.lower() and "sess_B" not in reply


def test_save_one_dial_works_with_no_session(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(platform="api_server"):
        reply = mixer(ctx, "save deps block")
    assert ctx._settings["deps"] == "block"
    assert "deps" in reply


def test_save_one_dial_validates_the_value(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(platform="api_server"):
        reply = mixer(ctx, "save edits plna")
    assert "edits" not in ctx._settings and "plna" in reply


def test_save_lines_writes_an_int_and_zero_means_off(work, fresh_plugin):
    ctx = fresh_plugin()
    mixer(ctx, "save lines 40")
    assert ctx._settings["lines"] == 40 and isinstance(ctx._settings["lines"], int)
    mixer(ctx, "save lines off")
    assert ctx._settings["lines"] == 0


def test_save_scope_replaces_the_saved_list(work, fresh_plugin):
    ctx = fresh_plugin()
    mixer(ctx, "save scope src/** docs/**")
    assert ctx._settings["scope"] == ["src/**", "docs/**"]


def test_save_current_set_still_works(work, fresh_plugin, monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_ID", "sess_S")
    ctx = fresh_plugin()
    mixer(ctx, "edits ask")
    mixer(ctx, "lines 12")
    assert "saved" in mixer(ctx, "save")
    assert ctx._settings["edits"] == "ask" and ctx._settings["lines"] == 12


def test_idle_sessions_are_pruned_after_24h(work, fresh_plugin, monkeypatch):
    from hermes_agent_mixer.hermes import plugin

    clock = [1000.0]
    monkeypatch.setattr(plugin, "_now", lambda: clock[0])
    ctx = fresh_plugin()
    monkeypatch.setenv("HERMES_SESSION_ID", "old")
    mixer(ctx, "edits plan")
    turn(ctx, "old")
    clock[0] += 25 * 3600
    turn(ctx, "fresh")
    sessions = plugin.get_mixer().session_ids()
    assert "old" not in sessions and "fresh" in sessions


def test_at_most_1000_sessions_are_kept(work, fresh_plugin):
    from hermes_agent_mixer.hermes import plugin

    ctx = fresh_plugin()
    for i in range(1100):
        turn(ctx, f"s{i}")
    assert len(plugin.get_mixer().session_ids()) <= 1000
