"""Subagents inherit the parent's dials and share its per-turn budget (B2, QW11, D2).
Rewrite of test_subagent_session_does_not_inherit_parent_override, which locked the bug in."""
from __future__ import annotations

import pytest

from tests.hermes_driver import bound, mixer, subagent_start, subagent_stop, tool, turn, unbound, verdict
from tests.test_session_binding import TUI_T

THREE = "1\n2\n3\n"


@pytest.fixture
def work(tmp_path, monkeypatch, host_shim):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.chdir(home)
    monkeypatch.setenv("TERMINAL_CWD", str(proj))
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    monkeypatch.delenv("HERMES_SESSION_KEY", raising=False)
    return {"path": "src/new.py", "content": "x\n"}


def test_subagent_start_links_a_child_that_inherits_the_dials(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(**TUI_T):
        mixer(ctx, "edits plan")
        turn(ctx, "sess_T", platform="tui")
        subagent_start(ctx, "sess_T", "sess_T_c1")
    out = unbound(lambda: verdict(tool(ctx, "write_file", work, "sess_T_c1", turn="c1-t1")))
    assert out == "block"


def test_pre_llm_call_with_parent_session_id_links_a_child(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(**TUI_T):
        mixer(ctx, "edits plan")
        turn(ctx, "sess_T", platform="tui")

    def child():
        turn(ctx, "sess_T_c2", turn_id="c2-t1", parent="sess_T")
        return verdict(tool(ctx, "write_file", work, "sess_T_c2", turn="c2-t1"))

    assert unbound(child) == "block"


def test_children_read_the_parents_dials_live_not_a_copy(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(**TUI_T):
        turn(ctx, "sess_T", platform="tui")
        subagent_start(ctx, "sess_T", "sess_T_c")
        assert verdict(tool(ctx, "write_file", work, "sess_T_c")) == "allow"
        mixer(ctx, "edits plan")
        assert verdict(tool(ctx, "write_file", work, "sess_T_c")) == "block"
        mixer(ctx, "edits auto")
        assert verdict(tool(ctx, "write_file", work, "sess_T_c")) == "allow"


def test_child_shares_the_parents_current_turn_budget(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(**TUI_T):
        mixer(ctx, "lines 5")
        turn(ctx, "sess_T", turn_id="p-t1", platform="tui")
        parent = verdict(tool(ctx, "write_file", {"path": "src/a.py", "content": THREE}, "sess_T", turn="p-t1"))
        subagent_start(ctx, "sess_T", "sess_T_c3", "p-t1")

    def child():
        turn(ctx, "sess_T_c3", turn_id="c3-t1", parent="sess_T")
        return verdict(tool(ctx, "write_file", {"path": "src/b.py", "content": THREE}, "sess_T_c3", turn="c3-t1"))

    assert (parent, unbound(child)) == ("allow", "block")


def test_a_child_turn_never_resets_the_parents_budget(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(**TUI_T):
        mixer(ctx, "lines 5")
        turn(ctx, "sess_T", turn_id="p-t1", platform="tui")
        tool(ctx, "write_file", {"path": "src/a.py", "content": THREE}, "sess_T", turn="p-t1")
        subagent_start(ctx, "sess_T", "sess_T_c")
        turn(ctx, "sess_T_c", turn_id="c-t1", parent="sess_T")
        turn(ctx, "sess_T_c", turn_id="c-t2", parent="sess_T")
        again = verdict(tool(ctx, "write_file", {"path": "src/b.py", "content": THREE}, "sess_T", turn="p-t1"))
    assert again == "block"


def test_a_new_parent_turn_resets_the_shared_budget(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(**TUI_T):
        mixer(ctx, "lines 5")
        turn(ctx, "sess_T", turn_id="p-t1", platform="tui")
        subagent_start(ctx, "sess_T", "sess_T_c")
        tool(ctx, "write_file", {"path": "src/a.py", "content": THREE}, "sess_T_c")
        turn(ctx, "sess_T", turn_id="p-t2", platform="tui")
        assert verdict(tool(ctx, "write_file", {"path": "src/b.py", "content": THREE}, "sess_T_c")) == "allow"


def test_grandchildren_resolve_to_the_root_session(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(**TUI_T):
        mixer(ctx, "edits plan")
        turn(ctx, "sess_T", platform="tui")
        subagent_start(ctx, "sess_T", "child")
        subagent_start(ctx, "child", "grandchild")
        assert verdict(tool(ctx, "write_file", work, "grandchild")) == "block"


def test_subagent_stop_drops_the_link_but_keeps_the_parent(work, fresh_plugin):
    from hermes_agent_mixer.hermes import plugin

    ctx = fresh_plugin()
    with bound(**TUI_T):
        mixer(ctx, "edits plan")
        turn(ctx, "sess_T", platform="tui")
        subagent_start(ctx, "sess_T", "child")
        subagent_stop(ctx, "sess_T", "child")
        assert verdict(tool(ctx, "write_file", work, "sess_T")) == "block"
    assert "child" not in plugin.get_mixer().session_ids()


def test_an_unlinked_session_keeps_only_saved_dials(work, fresh_plugin):
    ctx = fresh_plugin()
    with bound(**TUI_T):
        mixer(ctx, "edits plan")
        turn(ctx, "sess_T", platform="tui")
    assert verdict(tool(ctx, "write_file", work, "stranger")) == "allow"


def test_a_child_turn_inside_the_parents_chat_does_not_remap_the_chat_key(work, fresh_plugin):
    gw = {"platform": "discord", "chat_id": "111", "chat_type": "group", "session_key": "agent:main:discord:group:111"}
    ctx = fresh_plugin()
    with bound(**gw):
        turn(ctx, "sess_A", platform="discord")
        subagent_start(ctx, "sess_A", "sess_A_child")
        turn(ctx, "sess_A_child", turn_id="c1", parent="sess_A", platform="discord")  # same ContextVars as the parent
        mixer(ctx, "edits plan")
        turn(ctx, "sess_A", turn_id="t2", platform="discord")
        assert verdict(tool(ctx, "write_file", work, "sess_A", turn="t2")) == "block"
