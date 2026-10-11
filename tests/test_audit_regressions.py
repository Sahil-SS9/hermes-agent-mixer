"""Regression witnesses for defects found in the delivered candidate.

Payloads are classified, never executed. All on-disk fixtures are under pytest's
sandbox; each regression was witnessed RED before changing production code.
"""
from __future__ import annotations

import pytest

from hermes_agent_mixer import decisions, diffcount, plugin
from hermes_agent_mixer.mixer import LinesState


def knobs(**overrides):
    return {"edits": "auto", "scope": [], "deps": "allow", "lines": "off", **overrides}


@pytest.mark.parametrize("command", [
    "pwd >marker", "cat README.md>marker", "cat README.md>>marker",
    "pwd 2>marker", "pwd &>marker", "pwd &&touch marker",
    "cat README.md|tee marker", "pwd;touch marker", "pwd||touch marker",
    "pwd\ntouch marker", "git branch new-branch", "git branch --track new-branch",
    "git branch --unset-upstream", "git branch --edit-description",
    "git diff --output=marker", "git diff --output marker", "git log --output=marker",
    'env python3 -c "print(1)"', "env -i touch marker", "env -S 'touch marker'",
    "tree -o marker", "find . -fprint marker", "find . -fprintf marker '%p'",
    "find . -fls marker", 'cat "$(touch marker)"', "cat `touch marker`",
    "cat <(touch marker)", "pwd & touch marker",
])
def test_r1_plan_blocks_terminal_write_forms(tmp_path, command):
    result = decisions.evaluate("terminal", {"command": command}, knobs(edits="plan"), root=tmp_path)
    assert result is not None, f"plan mode allowed {command!r}"
    assert result["action"] == "block"
    assert "mixer:edits" in result["message"]


@pytest.mark.parametrize("command", [
    "cat 'a && b'", "cat '>'", "cat '|'", "cat ';'", "cat '$(literal)'",
    "cat a|wc -l", "pwd;git status", "git branch", "git branch --list 'feature/*'",
    "git branch --all", "env", "env -0",
])
def test_r1_plan_preserves_quoted_literals_and_read_only_commands(tmp_path, command):
    assert decisions.evaluate("terminal", {"command": command}, knobs(edits="plan"), root=tmp_path) is None


@pytest.mark.parametrize("body", [
    "*** Update File: outside.txt\n@@\n-old\n+new",
    "*** Add File: outside.txt\n+new",
    "*** Delete File: outside.txt",
    "*** Move File: src/a.txt -> outside.txt",
    "*** Move File: outside.txt -> src/a.txt",
    "***\tUpdate File: outside.txt\n@@\n-old\n+new",
    "*** Update File: src/a.txt\n@@\n-old\n+new\n*** Update File: outside.txt\n@@\n-old\n+new",
])
def test_r2_bulk_patch_checks_every_target_in_hook(tmp_path, monkeypatch, fake_ctx, body):
    monkeypatch.chdir(tmp_path)
    plugin.reset_mixer()
    try:
        fake_ctx._settings.update(scope=["src/**"])
        plugin.register(fake_ctx)
        result = fake_ctx.hooks["pre_tool_call"][0](
            tool_name="patch", args={"mode": "patch", "patch": f"*** Begin Patch\n{body}\n*** End Patch\n"},
            session_id="s", task_id="t")
        assert result is not None
        assert result["action"] == "block"
        assert "mixer:scope" in result["message"]
        assert "outside.txt" in result["message"]
    finally:
        plugin.reset_mixer()


def test_r2_bulk_patch_checks_symlink_escape(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "src").symlink_to(outside, target_is_directory=True)
    result = decisions.evaluate("patch", {"mode": "patch", "patch":
        "*** Begin Patch\n*** Add File: src/escape.txt\n+hi\n*** End Patch\n"},
        knobs(scope=["src/**"]), root=root)
    assert result is not None and result["action"] == "block"
    assert "mixer:scope" in result["message"]


def test_r2_bulk_patch_path_argument_cannot_hide_target(tmp_path):
    result = decisions.evaluate("patch", {"path": "src/decoy.txt", "mode": "patch", "patch":
        "*** Begin Patch\n*** Delete File: outside.txt\n*** End Patch\n"},
        knobs(scope=["src/**"]), root=tmp_path)
    assert result is not None and result["action"] == "block"
    assert "outside.txt" in result["message"]


def test_r2_bulk_patch_inside_scope_is_allowed(tmp_path):
    result = decisions.evaluate("patch", {"mode": "patch", "patch":
        "*** Begin Patch\n*** Update File: src/a.txt\n@@\n-old\n+new\n*** Add File: src/b.txt\n+hi\n*** End Patch\n"},
        knobs(scope=["src/**"]), root=tmp_path)
    assert result is None


@pytest.mark.parametrize("edits", ["auto", "ask"])
def test_r3_line_limit_blocks_before_dependency_approval(tmp_path, edits):
    state = LinesState()
    result = decisions.evaluate("write_file", {"path": "package.json", "content":
        '{\n  "dependencies": {\n    "new-package": "1.0"\n  }\n}\n'},
        knobs(edits=edits, deps="ask", lines=1), state, root=tmp_path, session_id="s", task_id="t")
    assert result is not None and result["action"] == "block"
    assert "mixer:lines" in result["message"]
    assert state.used("s", "t") == 0


def test_r3_dependency_approval_reserves_the_allowed_budget(tmp_path):
    state = LinesState()
    result = decisions.evaluate("write_file", {"path": "package.json", "content":
        '{"dependencies": {"new-package": "1.0"}}\n'},
        knobs(deps="ask", lines=1), state, root=tmp_path, session_id="s", task_id="t")
    assert result is not None and result["action"] == "approve"
    assert result["rule_key"] == "mixer:deps"
    assert state.used("s", "t") == 1
    second = decisions.evaluate("write_file", {"path": "extra.txt", "content": "hi\n"},
        knobs(deps="ask", lines=1), state, root=tmp_path, session_id="s", task_id="t")
    assert second is not None and second["action"] == "block"


def test_r3_dependency_block_still_precedes_line_block(tmp_path):
    state = LinesState()
    result = decisions.evaluate("write_file", {"path": "package.json", "content":
        '{"dependencies": {"new-package": "1.0"}}\n'},
        knobs(deps="block", lines=0), state, root=tmp_path)
    assert result is not None and result["action"] == "block"
    assert "mixer:deps" in result["message"]
    assert state.used("", "") == 0


@pytest.mark.parametrize("tool,args,expected", [
    ("write_file", {"content": "new\n"}, (1, 20)),
    ("patch", {"old_string": "old-0", "new_string": "new"}, (1, 1)),
])
def test_r5_tilde_paths_read_the_actual_before_state(tmp_path, monkeypatch, tool, args, expected):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / "large.txt").write_text("".join(f"old-{i}\n" for i in range(20)), encoding="utf-8")
    assert diffcount.estimate(tool, {"path": "~/large.txt", **args}, tmp_path) == expected


def test_r5_tilde_overwrite_is_blocked_by_real_diff(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / "large.txt").write_text("".join(f"old-{i}\n" for i in range(20)), encoding="utf-8")
    result = decisions.evaluate("write_file", {"path": "~/large.txt", "content": "new\n"},
        knobs(lines=1), LinesState(), root=tmp_path)
    assert result is not None and result["action"] == "block"
    assert "21 lines" in result["message"]


@pytest.mark.parametrize("section", [
    '[project]\ndependencies = ["requests"]\n',
    '[project.optional-dependencies]\nextra = ["requests"]\n',
    '[dependency-groups]\ndev = ["requests"]\n',
])
def test_r6_unversioned_pyproject_dependency_is_detected(tmp_path, section):
    result = decisions.evaluate("write_file", {"path": "pyproject.toml", "content": section},
        knobs(deps="block"), root=tmp_path)
    assert result is not None and result["action"] == "block"
    assert "requests" in result["message"]


@pytest.mark.parametrize("after", [
    '[project]\ndependencies = ["requests>=2"]\n',
    '[project]\ndependencies = []\n',
])
def test_r6_existing_bare_dependency_bump_or_removal_is_allowed(tmp_path, after):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["requests"]\n', encoding="utf-8")
    assert decisions.evaluate("write_file", {"path": "pyproject.toml", "content": after},
        knobs(deps="block"), root=tmp_path) is None
