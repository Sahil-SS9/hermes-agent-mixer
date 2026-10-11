"""Tests for the lines-per-turn budget: diff-based counting, reset, isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_agent_mixer.core import diffcount
from tests import legacy
from tests.legacy import decisions
from tests.legacy import LinesState


def _knobs(lines, edits="auto"):
    return {"edits": edits, "scope": [], "lines": lines, "deps": "allow", "root": None}


# -- counting primitives ----------------------------------------------------


def test_new_file_counts_all_lines_added(tmp_path):
    added, removed = diffcount.count_diff_lines(None, "a\nb\nc\n")
    assert (added, removed) == (3, 0)


def test_overwrite_counts_added_and_removed_from_real_diff(tmp_path):
    before = "line1\nline2\nline3\nline4\n"
    after = "line1\nline9\nline3\nline4\n"
    added, removed = diffcount.count_diff_lines(before, after)
    assert added == 1
    assert removed == 1


def test_empty_after_counts_all_removed(tmp_path):
    added, removed = diffcount.count_diff_lines("a\nb\n", "")
    assert added == 0
    assert removed == 2


def test_reordered_lines_count_as_moves(tmp_path):
    """difflib counts a reorder as removed+added; the sum is what the budget sees."""
    before = "a\nb\nc\n"
    after = "c\nb\na\n"
    added, removed = diffcount.count_diff_lines(before, after)
    assert added == 2 and removed == 2


# -- estimates per tool call -------------------------------------------------


def test_estimate_write_new_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    added, removed = legacy.estimate("write_file", {"path": "new.txt", "content": "x\ny\n"})
    assert (added, removed) == (2, 0)


def test_estimate_write_overwrite_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "f.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    added, removed = legacy.estimate("write_file", {"path": "f.txt", "content": "line1\nCHANGED\nline3\n"})
    assert (added, removed) == (1, 1)


def test_estimate_patch_replace_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "f.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    added, removed = legacy.estimate(
        "patch", {"path": "f.py", "old_string": "y = 2", "new_string": "y = 3\nz = 4"}
    )
    # 'y = 2' removed, 'y = 3' and 'z = 4' added
    assert added == 2
    assert removed == 1


def test_estimate_patch_v4a_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "f.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    patch_text = (
        "*** Begin Patch\n"
        "*** Update File: f.py\n"
        "@@\n"
        " two\n"
        "-three\n"
        "+three\n"
        "+four\n"
        "*** End Patch\n"
    )
    added, removed = legacy.estimate("patch", {"path": "f.py", "mode": "patch", "patch": patch_text})
    # The real V4A apply yields one/two/three/four from one/two/three: a real
    # diff counts ONE added line. Raw +/- counting of the patch text would
    # overcount as (2 added, 1 removed) - this assertion proves the simulated
    # diff is the source.
    assert added == 1
    assert removed == 0


def test_estimate_patch_all_replace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "f.txt").write_text("dup\ndup\n", encoding="utf-8")
    added, removed = legacy.estimate(
        "patch", {"path": "f.txt", "old_string": "dup", "new_string": "new", "replace_all": True}
    )
    assert added == 2
    assert removed == 2


def test_estimate_missing_path_is_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert legacy.estimate("write_file", {}) == (0, 0)


# -- budget behaviour through the decision engine -----------------------------


def test_write_over_budget_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _mixer_state()
    decision = decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n3\n4\n5\n"}, _knobs(3), state)
    assert decision is not None
    assert decision["action"] == "block"
    assert "lines" in decision["message"]


def test_block_message_gives_remaining_budget_and_suggests_summarising(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _mixer_state()
    assert decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n"}, _knobs(3), state) is None
    decision = decisions.evaluate("write_file", {"path": "b.txt", "content": "1\n2\n3\n"}, _knobs(3), state)
    # allowed so far: 2 of 3 used -> 1 line remains before the block
    assert "1" in decision["message"]
    assert "summaris" in decision["message"].lower()


def test_budget_exactly_met_allows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = LinesState()
    ok = decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n3\n"}, _knobs(3), state)
    assert ok is None
    # no session/task ids: the process-wide fallback key
    assert state.used("", "") == 3


def test_cumulative_across_calls_in_one_turn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = LinesState()
    assert decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n3\n"}, _knobs(3), state) is None
    second = decisions.evaluate("write_file", {"path": "b.txt", "content": "1\n"}, _knobs(3), state)
    assert second is not None
    assert "lines" in second["message"]


def test_blocked_call_does_not_consume_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _mixer_state()
    assert decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n"}, _knobs(3), state) is None
    decision = decisions.evaluate("write_file", {"path": "b.txt", "content": "1\n2\n3\n"}, _knobs(3), state)
    assert decision is not None
    after_block = decisions.evaluate("write_file", {"path": "c.txt", "content": "1\n"}, _knobs(3), state)
    assert after_block is None


def _mixer_state():
    return LinesState()


# -- turn reset and isolation -------------------------------------------------


def test_turn_reset_via_pre_llm_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = LinesState()
    assert decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n3\n"}, _knobs(3), state,
                              session_id="t", task_id="task") is None
    state.reset_turn("t", "task")
    ok = decisions.evaluate("write_file", {"path": "b.txt", "content": "1\n2\n"}, _knobs(3), state,
                            session_id="t", task_id="task")
    assert ok is None


def test_task_ids_isolate_counters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = LinesState()
    assert decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n3\n"}, _knobs(3), state) is None
    other = decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n3\n"}, _knobs(3), state,
                               task_id="turn-2")
    assert other is None


def test_sessions_isolate_counters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = LinesState()
    assert decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n3\n"}, _knobs(3), state,
                              session_id="s1") is None
    other = decisions.evaluate("write_file", {"path": "b.txt", "content": "1\n2\n3\n"}, _knobs(3), state,
                               session_id="s2")
    assert other is None


# -- knob scope ---------------------------------------------------------------


def test_lines_off_disables_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for _ in range(3):
        assert decisions.evaluate("write_file", {"path": "a.txt", "content": "1\n2\n3\n4\n"}, _knobs("off")) is None


def test_lines_does_not_apply_to_other_tools(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    assert decisions.evaluate(
        "terminal", {"command": f"echo x > {outside}/big.txt"}, _knobs(1)) is None
    assert decisions.evaluate("execute_code", {"code": "print('hi')"}, _knobs(1)) is None


def test_lines_stage_order_after_scope(tmp_path, monkeypatch):
    """A blocked-by-scope write must not consume budget or preempt the scope message."""
    monkeypatch.chdir(tmp_path)
    state = _mixer_state()
    decision = decisions.evaluate(
        "write_file", {"path": "nope/a.txt", "content": "1\n2\n3\n4\n"},
        {"edits": "auto", "scope": ["src/**"], "lines": 2, "deps": "allow", "root": None}, state)
    assert decision is not None
    assert "scope" in decision["message"]
    assert state.used("", "") == 0


def test_patch_counting_works_through_decisions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "f.txt").write_text("keep\n" * 10, encoding="utf-8")
    state = _mixer_state()
    decision = decisions.evaluate(
        "patch", {"path": "f.txt", "old_string": "keep\n" * 10, "new_string": "new"},
        _knobs(3), state)
    assert decision is not None
    assert decision["action"] == "block"