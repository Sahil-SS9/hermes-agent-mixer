"""Tests for the edits knob (ask / auto / plan) and plan-mode terminal limits."""

from __future__ import annotations

from tests.legacy import decisions


def _knobs(**overrides):
    base = {
        "edits": "auto",
        "scope": [],
        "lines": "off",
        "deps": "allow",
        "root": None,
    }
    base.update(overrides)
    return base


def test_auto_allows_write_inside_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("write_file", {"path": "src/a.py", "content": "x"}, _knobs())
    assert decision is None


def test_ask_returns_approve_directive_with_rule_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("write_file", {"path": "src/a.py", "content": "x"}, _knobs(edits="ask"))
    assert decision is not None
    assert decision["action"] == "approve"
    assert decision["rule_key"].startswith("mixer:edit:") and decision["rule_key"].endswith("src/a.py")
    assert decision.get("message")


def test_ask_message_mentions_the_tool(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("patch", {"path": "src/a.py", "old_string": "a", "new_string": "b"}, _knobs(edits="ask"))
    assert decision is not None
    assert "patch" in decision["message"]


def test_plan_blocks_write_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate(
        "write_file", {"path": "src/a.py", "content": "x"}, _knobs(edits="plan")
    )
    assert decision is not None
    assert decision["action"] == "block"
    assert "plan" in decision["message"].lower()


def test_plan_blocks_patch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate(
        "patch", {"path": "src/a.py", "old_string": "a", "new_string": "b"}, _knobs(edits="plan")
    )
    assert decision is not None
    assert decision["action"] == "block"


def test_plan_blocks_execute_code(tmp_path):
    decision = decisions.evaluate("execute_code", {"code": "open('f','w').write('x')"}, _knobs(edits="plan"))
    assert decision is not None
    assert decision["action"] == "block"
    assert "plan" in decision["message"].lower()


def test_plan_allows_read_only_terminal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for command in ["ls -la", "cat x.txt", "git status", "git diff HEAD", "grep mixer *.py", "rg pattern .",
                    "find . -maxdepth 2 -name t", "wc -l x", "tree .", "pwd", "which hermes", "env | wc -l"]:
        decision = decisions.evaluate("terminal", {"command": command}, _knobs(edits="plan"))
        assert decision is None, f"read-only command blocked: {command}"


def test_plan_blocks_terminal_redirect(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for command in ["echo hi > f.txt", "echo hi >> f.txt", "cat a | tee b"]:
        decision = decisions.evaluate("terminal", {"command": command}, _knobs(edits="plan"))
        assert decision is not None, f"redirect allowed in plan mode: {command}"
        assert decision["action"] == "block"


def test_plan_blocks_non_read_only_terminal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for command in ["python script.py", "rm -rf x", "chmod +x run.sh", "uv run pytest", "make build"]:
        decision = decisions.evaluate("terminal", {"command": command}, _knobs(edits="plan"))
        assert decision is not None, f"command allowed in plan mode: {command}"


def test_plan_blocks_find_delete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("terminal", {"command": "find . -name t -delete"}, _knobs(edits="plan"))
    assert decision is not None
    assert decision["action"] == "block"


def test_plan_blocks_git_write_subcommands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for command in ["git checkout other", "git commit -m x", "git push origin main", "git restore a.py"]:
        decision = decisions.evaluate("terminal", {"command": command}, _knobs(edits="plan"))
        assert decision is not None, f"git write command allowed in plan mode: {command}"


def test_plan_allows_piped_read_only_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("terminal", {"command": "grep mixer *.py | wc -l"}, _knobs(edits="plan"))
    assert decision is None


def test_plan_allows_git_rev_parse(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("terminal", {"command": "git rev-parse HEAD"}, _knobs(edits="plan"))
    assert decision is None


def test_plan_message_explains_how_to_leave(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("terminal", {"command": "make build"}, _knobs(edits="plan"))
    assert decision is not None
    assert "edits" in decision["message"]
    assert "/mixer" in decision["message"]


def test_plan_respects_quotes_when_splitting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from hermes_agent_mixer.core import shell

    assert shell.split_segments("echo 'a && rm -rf x'") == [["echo", "a && rm -rf x"]]
    assert decisions.evaluate("terminal", {"command": "echo 'a && rm -rf x'"}, _knobs(edits="plan")) is None
    assert decisions.evaluate("terminal", {"command": "echo a && rm -rf x"}, _knobs(edits="plan")) is not None


def test_plan_blocks_write_in_second_segment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("terminal", {"command": "cat a.txt && echo hi > b.txt"}, _knobs(edits="plan"))
    assert decision is not None


def test_auto_terminal_is_not_scope_checked(tmp_path, monkeypatch, tmp_path_factory):
    """Documented Not-a-sandbox gap: terminal commands are not scope-checked in auto mode."""
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    decision = decisions.evaluate(
        "terminal", {"command": f"echo hi > {outside}/x.txt"}, _knobs(edits="auto")
    )
    assert decision is None


def test_scope_check_still_applies_in_auto_for_file_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("write_file", {"path": "nope/x.txt", "content": "x"}, _knobs(scope=["src/**"]))
    assert decision is not None
    assert decision["action"] == "block"


def test_ask_scope_block_wins_over_approve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decision = decisions.evaluate("write_file", {"path": "nope/x.txt", "content": "x"}, _knobs(scope=["src/**"], edits="ask"))
    assert decision is not None
    assert decision["action"] == "block"