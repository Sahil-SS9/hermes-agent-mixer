"""Codex adapter, built from payloads in the documented shapes (X5, D11).
https://developers.openai.com/codex/hooks - contract-tested only: Codex is not installed on this rig."""
from __future__ import annotations

import json

from tests.cli_driver import rig  # noqa: F401


def pre(rig, tool, command, sid="X1", turn="t1"):
    return {"session_id": sid, "transcript_path": None, "cwd": str(rig.proj), "hook_event_name": "PreToolUse",
            "model": "gpt", "permission_mode": "default", "turn_id": turn, "tool_name": tool,
            "tool_use_id": "call_1", "tool_input": {"command": command}}


def prompt(rig, text, sid="X1", turn="t1"):
    return {"session_id": sid, "transcript_path": None, "cwd": str(rig.proj), "hook_event_name": "UserPromptSubmit",
            "model": "gpt", "permission_mode": "default", "turn_id": turn, "prompt": text}


def add(path, n):
    return "*** Begin Patch\n*** Add File: " + path + "\n" + "".join(f"+l{i}\n" for i in range(n)) + "*** End Patch\n"


def verdict(data):
    if (data or {}).get("decision") == "block":
        return "deny"
    return ((data or {}).get("hookSpecificOutput") or {}).get("permissionDecision")


def test_apply_patch_targets_are_scope_checked(rig):
    rig.run(["--saved", "scope", "add", "src/**"])
    update = "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch\n"
    move = ("*** Begin Patch\n*** Update File: src/app.py\n*** Move to: README.md\n@@\n def f():\n-    return 1\n"
            "+    return 2\n*** End Patch\n")
    delete = "*** Begin Patch\n*** Delete File: README.md\n*** End Patch\n"
    cases = [(add("README.md", 2), "deny"), (add("src/n.py", 2), None), (update, "deny"), (move, "deny"), (delete, "deny"),
             ("*** Begin Patch\n*** Update File: src/app.py\n@@\n-    return 1\n+    return 3\n*** End Patch\n", None)]
    for patch, want in cases:
        assert verdict(rig.hook("codex", pre(rig, "apply_patch", patch))[1]) == want, patch


def test_deny_uses_the_pre_tool_use_output_shape(rig):
    rig.run(["--saved", "scope", "add", "src/**"])
    data = rig.hook("codex", pre(rig, "apply_patch", add("README.md", 1)))[1]
    out = data["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "deny" and out["permissionDecisionReason"]
    assert set(data) == {"hookSpecificOutput"}  # nothing that Codex would treat as a failed hook


def test_ask_degrades_to_deny_and_says_how_to_allow(rig):
    rig.run(["--saved", "edits", "ask"])
    data = rig.hook("codex", pre(rig, "apply_patch", add("src/n.py", 1)))[1]
    out = data["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "ask" in out["permissionDecisionReason"].lower()
    assert "agent-mixer edits auto" in out["permissionDecisionReason"]
    assert "continue" not in data and "stopReason" not in data and "suppressOutput" not in data


def test_deps_ask_degrades_with_the_right_hint(rig):
    rig.run(["--saved", "deps", "ask"])
    data = rig.hook("codex", pre(rig, "Bash", "npm install left-pad"))[1]
    assert verdict(data) == "deny" and "agent-mixer deps allow" in data["hookSpecificOutput"]["permissionDecisionReason"]


def test_codex_never_sees_an_ask_or_an_allow(rig):
    rig.run(["--saved", "edits", "ask"])
    for patch in (add("src/a.py", 1), add("README.md", 1)):
        raw = rig.run(["hook", "codex"], json.dumps(pre(rig, "apply_patch", patch)))[1]
        assert '"ask"' not in raw and '"allow"' not in raw


def test_bash_in_plan_mode(rig):
    rig.run(["--saved", "edits", "plan"])
    assert verdict(rig.hook("codex", pre(rig, "Bash", "rm src/app.py"))[1]) == "deny"
    assert verdict(rig.hook("codex", pre(rig, "Bash", "ls -la"))[1]) is None
    assert verdict(rig.hook("codex", pre(rig, "apply_patch", add("src/n.py", 1)))[1]) == "deny"


def test_a_mixer_prompt_is_handled_and_blocks_the_turn(rig):
    data = rig.hook("codex", prompt(rig, "/mixer edits plan", sid="X3"))[1]
    assert data["decision"] == "block" and "plan" in data["reason"].lower()
    assert verdict(rig.hook("codex", pre(rig, "apply_patch", add("src/n.py", 1), sid="X3"))[1]) == "deny"
    assert verdict(rig.hook("codex", pre(rig, "apply_patch", add("src/n.py", 1), sid="X4"))[1]) is None


def test_prompt_context_and_turn_budget(rig):
    rig.run(["--saved", "lines", "25"])
    ctx = rig.hook("codex", prompt(rig, "go"))[1]["hookSpecificOutput"]
    assert ctx["hookEventName"] == "UserPromptSubmit" and ctx["additionalContext"].startswith("Agent Mixer:")
    results = [verdict(rig.hook("codex", pre(rig, "apply_patch", add(f"src/{i}.py", 10), turn="t1"))[1]) for i in range(3)]
    assert results == [None, None, "deny"]
    assert verdict(rig.hook("codex", pre(rig, "apply_patch", add("src/z.py", 10), turn="t2"))[1]) is None


def test_subagents_use_the_parents_session_id_and_so_its_dials(rig):
    rig.run(["--session", "PARENT", "edits", "plan"])
    assert verdict(rig.hook("codex", pre(rig, "apply_patch", add("src/n.py", 1), sid="PARENT"))[1]) == "deny"


def test_patch_counting_uses_a_real_diff(rig):
    rig.run(["--saved", "lines", "3"])
    patch = ("*** Begin Patch\n*** Update File: src/app.py\n@@\n def f():\n-    return 1\n+    return 2\n*** End Patch\n")
    assert verdict(rig.hook("codex", pre(rig, "apply_patch", patch))[1]) is None  # 2 lines
    assert verdict(rig.hook("codex", pre(rig, "apply_patch", patch))[1]) == "deny"  # 4 > 3


def test_unrelated_tools_and_events_are_silent(rig):
    rig.run(["--saved", "edits", "plan"])
    assert rig.hook("codex", pre(rig, "WebSearch", "x"))[1] is None
    assert rig.hook("codex", {"session_id": "X1", "cwd": str(rig.proj), "hook_event_name": "SessionStart"})[1] is None
