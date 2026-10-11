"""Regression witnesses for session/turn lifecycle and parallel budget admission."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from hermes_agent_mixer.core import decisions
from hermes_agent_mixer.hermes import plugin
from hermes_agent_mixer.core.mixer import LinesState


@pytest.mark.parametrize("new_task", ["new-turn", "old-turn"])
def test_r4_board_resets_only_current_session_at_turn_boundary(tmp_path, monkeypatch, fake_ctx, new_task):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HERMES_SESSION_ID", "parent")
    plugin.reset_mixer()
    try:
        fake_ctx._settings.update(lines=2, deps="allow")
        plugin.register(fake_ctx)
        begin = fake_ctx.hooks["pre_llm_call"][0]
        hook = fake_ctx.hooks["pre_tool_call"][0]
        begin(session_id="parent", task_id="old-turn")
        assert hook(tool_name="write_file", args={"path": "one.txt", "content": "one\n"},
                    session_id="parent", task_id="old-turn") is None
        assert hook(tool_name="write_file", args={"path": "child.txt", "content": "child\n"},
                    session_id="child", task_id="child-turn") is None
        assert "1 / 2 this turn" in fake_ctx.commands["mixer"]["handler"]("")
        begin(session_id="parent", task_id=new_task)
        assert "0 / 2 this turn" in fake_ctx.commands["mixer"]["handler"]("")
        assert plugin.get_mixer().lines_state.session_used("child") == 1
        assert hook(tool_name="write_file", args={"path": "two.txt", "content": "one\ntwo\n"},
                    session_id="parent", task_id=new_task) is None
        assert "2 / 2 this turn" in fake_ctx.commands["mixer"]["handler"]("")
    finally:
        plugin.reset_mixer()


def test_parallel_calls_cannot_both_take_the_last_line(tmp_path, monkeypatch):
    state = LinesState()
    barrier = Barrier(2)
    original_used = state.used

    def stale_read(session, task):
        value = original_used(session, task)
        barrier.wait(timeout=5)
        return value

    # Make the old read-then-add race deterministic. Atomic admission no longer
    # uses this vulnerable split read path. No file-tool payload is executed.
    monkeypatch.setattr(state, "used", stale_read)
    knobs = {"edits": "auto", "scope": [], "deps": "allow", "lines": 1}

    def call(index):
        return decisions.evaluate("write_file", {"path": f"{index}.txt", "content": "one\n"},
            knobs, state, root=tmp_path, session_id="s", task_id="t")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, range(2)))
    assert sum(result is None for result in results) == 1
    blocked = [result for result in results if result is not None]
    assert len(blocked) == 1 and blocked[0]["action"] == "block"
    assert original_used("s", "t") == 1


def test_unload_reload_rebinds_saved_defaults_and_discards_budget(tmp_path, monkeypatch, fake_ctx):
    monkeypatch.chdir(tmp_path)
    plugin.reset_mixer()
    try:
        fake_ctx._settings.update(edits="plan", lines=2)
        plugin.register(fake_ctx)
        old = plugin.get_mixer()
        assert old.settings_for("s")["edits"] == "plan"
        old.lines_state.add("s", "t", 2)
        for callback in fake_ctx.unload_callbacks:
            callback()
        new_ctx = type(fake_ctx)({"edits": "auto", "lines": 1})
        plugin.register(new_ctx)
        assert plugin.get_mixer().settings_for("s")["edits"] == "auto"
        assert plugin.get_mixer().lines_state.session_used("s") == 0
    finally:
        plugin.reset_mixer()
