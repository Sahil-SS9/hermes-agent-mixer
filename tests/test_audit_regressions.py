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
