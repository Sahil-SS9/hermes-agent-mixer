"""Claude Code adapter, built from payloads in the documented shapes (X4).
https://code.claude.com/docs/en/hooks - PreToolUse, UserPromptSubmit, UserPromptExpansion."""
from __future__ import annotations

import pytest



def pre(rig, tool, tool_input, sid="S1", prompt_id="p1", **extra):
    return {"session_id": sid, "prompt_id": prompt_id, "transcript_path": str(rig.proj / ".t.jsonl"),
            "cwd": str(rig.proj), "permission_mode": "default", "hook_event_name": "PreToolUse",
            "tool_name": tool, "tool_input": tool_input, "tool_use_id": "toolu_1", **extra}


def prompt(rig, text, sid="S1", prompt_id="p1", event="UserPromptSubmit", **extra):
    return {"session_id": sid, "prompt_id": prompt_id, "cwd": str(rig.proj), "permission_mode": "default",
            "hook_event_name": event, "prompt": text, **extra}


def decision(data):
    return ((data or {}).get("hookSpecificOutput") or {}).get("permissionDecision")


def setup_scope(rig):
    rig.run(["--saved", "scope", "add", "src/**"])


def test_write_outside_scope_is_denied_with_a_reason(rig):
    setup_scope(rig)
    rc, data, _ = rig.hook("claude", pre(rig, "Write", {"file_path": str(rig.proj / "README.md"), "content": "x\n"}))
    out = data["hookSpecificOutput"]
    assert rc == 0 and out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "deny"
    assert "mixer:scope" in out["permissionDecisionReason"]


def test_allowed_calls_print_nothing_and_never_allow(rig):
    setup_scope(rig)
    rc, out, _ = rig.run(["hook", "claude"], __import__("json").dumps(
        pre(rig, "Write", {"file_path": str(rig.proj / "src" / "a.py"), "content": "x\n"})))
    assert rc == 0 and out == ""


@pytest.mark.parametrize("tool,tool_input", [
    ("Write", {"file_path": "src/a.py", "content": "x\n"}),
    ("Edit", {"file_path": "src/app.py", "old_string": "return 1", "new_string": "return 2", "replace_all": False}),
    ("NotebookEdit", {"notebook_path": "src/n.ipynb", "new_source": "x", "edit_mode": "replace"}),
    ("MultiEdit", {"file_path": "src/app.py", "edits": [{"old_string": "1", "new_string": "2"}]}),
])
def test_edits_ask_asks_natively_for_every_file_tool(rig, tool, tool_input):
    rig.run(["--saved", "edits", "ask"])
    tool_input = dict(tool_input, **{k: str(rig.proj / v) for k, v in tool_input.items() if k in ("file_path", "notebook_path")})
    _, data, _ = rig.hook("claude", pre(rig, tool, tool_input))
    assert decision(data) == "ask"


def test_edit_outside_scope_is_denied(rig):
    setup_scope(rig)
    _, data, _ = rig.hook("claude", pre(rig, "Edit", {"file_path": str(rig.proj / "README.md"), "old_string": "a",
                                                        "new_string": "b", "replace_all": False}))
    assert decision(data) == "deny"


def test_notebook_edit_outside_scope_is_denied(rig):
    setup_scope(rig)
    _, data, _ = rig.hook("claude", pre(rig, "NotebookEdit", {"notebook_path": str(rig.proj / "n.ipynb"), "new_source": "x"}))
    assert decision(data) == "deny"


def test_bash_write_targets_are_checked(rig):
    setup_scope(rig)
    assert decision(rig.hook("claude", pre(rig, "Bash", {"command": "echo x > README.md"}))[1]) == "deny"
    assert decision(rig.hook("claude", pre(rig, "Bash", {"command": "echo x > src/ok.txt"}))[1]) is None


def test_bash_relative_targets_use_the_hook_cwd(rig):
    setup_scope(rig)
    project = {"CLAUDE_PROJECT_DIR": str(rig.proj)}
    payload = pre(rig, "Bash", {"command": "touch a.py"})
    payload["cwd"] = str(rig.proj / "src")
    assert decision(rig.hook("claude", payload, extra_env=project)[1]) is None
    assert decision(rig.hook("claude", pre(rig, "Bash", {"command": "touch a.py"}), extra_env=project)[1]) == "deny"


def test_scope_globs_anchor_at_claude_project_dir(rig):
    setup_scope(rig)
    payload = pre(rig, "Write", {"file_path": str(rig.proj / "src" / "a.py"), "content": "x"})
    payload["cwd"] = str(rig.proj / "src")  # Claude may be sitting in a subfolder
    assert decision(rig.hook("claude", payload, extra_env={"CLAUDE_PROJECT_DIR": str(rig.proj)})[1]) is None
    other = pre(rig, "Write", {"file_path": str(rig.proj / "README.md"), "content": "x"})
    other["cwd"] = str(rig.proj / "src")
    assert decision(rig.hook("claude", other, extra_env={"CLAUDE_PROJECT_DIR": str(rig.proj)})[1]) == "deny"


def test_powershell_is_read_only_in_plan_mode(rig):
    rig.run(["--saved", "edits", "plan"])
    assert decision(rig.hook("claude", pre(rig, "PowerShell", {"command": "Get-ChildItem src"}))[1]) is None
    assert decision(rig.hook("claude", pre(rig, "PowerShell", {"command": "Remove-Item src/app.py"}))[1]) == "deny"


def test_plan_mode_via_slash_command_is_per_session(rig):
    exp = prompt(rig, "/mixer edits plan", event="UserPromptExpansion", expansion_type="slash_command",
                 command_name="mixer", command_args="edits plan", command_source="user")
    rc, data, _ = rig.hook("claude", exp)
    assert rc == 0 and data["decision"] == "block" and "plan" in data["reason"].lower()
    w = {"file_path": str(rig.proj / "src" / "a.py"), "content": "x\n"}
    assert decision(rig.hook("claude", pre(rig, "Write", w, sid="S1"))[1]) == "deny"
    assert decision(rig.hook("claude", pre(rig, "Write", w, sid="S2"))[1]) is None


def test_the_submit_event_handles_a_typed_mixer_command_too(rig):
    rc, data, _ = rig.hook("claude", prompt(rig, "/mixer lines 9"))
    assert data["decision"] == "block" and "9" in data["reason"]
    assert rig.run(["--session", "S1", "board"])[1].count("9") >= 1


def test_the_board_comes_back_for_a_bare_slash_mixer(rig):
    _, data, _ = rig.hook("claude", prompt(rig, "/mixer"))
    assert data["decision"] == "block" and "Agent Mixer" in data["reason"]


def test_other_prompts_and_other_slash_commands_are_left_alone(rig):
    assert rig.hook("claude", prompt(rig, "fix the bug"))[1] is None
    assert rig.hook("claude", prompt(rig, "/mixerish thing"))[1] is None
    exp = prompt(rig, "/review", event="UserPromptExpansion", expansion_type="slash_command",
                 command_name="review", command_args="")
    assert rig.hook("claude", exp)[1] is None


def test_prompt_hook_injects_the_rules_line_only_off_defaults(rig):
    assert rig.hook("claude", prompt(rig, "go"))[1] is None
    rig.run(["--saved", "deps", "block"])
    _, data, _ = rig.hook("claude", prompt(rig, "go"))
    out = data["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    assert out["additionalContext"].startswith("Agent Mixer:") and len(out["additionalContext"]) < 300
    assert "terminal" in out["additionalContext"]


def test_turn_budget_resets_on_a_new_prompt_id(rig):
    rig.run(["--saved", "lines", "5"])
    three = "a\nb\nc\n"
    def write(name, pid):
        return decision(rig.hook("claude", pre(rig, "Write", {"file_path": str(rig.proj / "src" / name), "content": three},
                                               prompt_id=pid))[1])
    assert (write("one.py", "p1"), write("two.py", "p1"), write("three.py", "p2")) == (None, "deny", None)


def test_the_prompt_event_also_resets_the_budget(rig):
    rig.run(["--saved", "lines", "5"])
    three = "a\nb\nc\n"
    w = lambda n: decision(rig.hook("claude", pre(rig, "Write", {"file_path": str(rig.proj / "src" / n), "content": three}))[1])
    assert w("a.py") is None and w("b.py") == "deny"
    rig.hook("claude", prompt(rig, "again", prompt_id="p1"))  # same prompt id: no reset
    assert w("c.py") == "deny"
    rig.hook("claude", prompt(rig, "again", prompt_id="p2"))
    assert w("d.py") is None


def test_subagents_share_the_session_dials_and_the_budget(rig):
    rig.run(["--session", "S1", "lines", "5"])
    three = "a\nb\nc\n"
    parent = rig.hook("claude", pre(rig, "Write", {"file_path": str(rig.proj / "src" / "a.py"), "content": three}))[1]
    child = rig.hook("claude", pre(rig, "Write", {"file_path": str(rig.proj / "src" / "b.py"), "content": three},
                                   agent_id="agent-1", agent_type="Explore"))[1]
    assert decision(parent) is None and decision(child) == "deny"


def test_mcp_write_tools_follow_extra_write_tools(rig):
    setup_scope(rig)
    rig.run(["--saved", "save", "extra_write_tools", "mcp__fs__write*"])
    bad = pre(rig, "mcp__fs__write_file", {"path": str(rig.proj / "README.md"), "content": "x"})
    ok = pre(rig, "mcp__fs__write_file", {"path": str(rig.proj / "src" / "a.py"), "content": "x"})
    assert decision(rig.hook("claude", bad)[1]) == "deny" and decision(rig.hook("claude", ok)[1]) is None
    assert decision(rig.hook("claude", pre(rig, "mcp__other__thing", {"path": "README.md"}))[1]) is None


def test_edit_drift_is_counted_not_blocked(rig):
    rig.run(["--saved", "lines", "50"])
    payload = pre(rig, "Edit", {"file_path": str(rig.proj / "src" / "app.py"), "old_string": "def f():\n  return 1",
                                "new_string": "def f():\n  return 2", "replace_all": False})
    assert decision(rig.hook("claude", payload)[1]) is None


def test_dependency_additions_ask(rig):
    (rig.proj / "pyproject.toml").write_text('[project]\nname="d"\ndependencies = [\n    "requests",\n]\n')
    payload = pre(rig, "Edit", {"file_path": str(rig.proj / "pyproject.toml"), "old_string": '    "requests",',
                                "new_string": '    "requests",\n    "rich",', "replace_all": False})
    out = rig.hook("claude", payload)[1]["hookSpecificOutput"]
    assert out["permissionDecision"] == "ask" and "rich" in out["permissionDecisionReason"]


def test_other_tools_and_events_are_silent(rig):
    rig.run(["--saved", "edits", "plan"])
    assert rig.hook("claude", pre(rig, "Read", {"file_path": "x"}))[1] is None
    assert rig.hook("claude", {"session_id": "S1", "cwd": str(rig.proj), "hook_event_name": "Notification", "message": "hi"})[1] is None
    assert rig.hook("claude", {"session_id": "S1", "cwd": str(rig.proj), "hook_event_name": "Stop"})[1] is None
