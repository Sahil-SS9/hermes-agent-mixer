"""Gemini CLI adapter, built from payloads in the documented shapes (X6, D11).
https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md - contract-tested only."""
from __future__ import annotations

from tests.cli_driver import rig  # noqa: F401


def event(rig, name, sid="G1", **fields):
    return {"session_id": sid, "transcript_path": "", "cwd": str(rig.proj), "hook_event_name": name,
            "timestamp": "2026-10-11T20:00:00Z", **fields}


def tool(rig, name, tool_input, sid="G1"):
    return event(rig, "BeforeTool", sid, tool_name=name, tool_input=tool_input)


def verdict(data):
    return (data or {}).get("decision")


def test_write_file_outside_scope_is_denied_with_a_reason(rig):
    rig.run(["--saved", "scope", "add", "src/**"])
    data = rig.hook("gemini", tool(rig, "write_file", {"file_path": str(rig.proj / "README.md"), "content": "x"}))[1]
    assert verdict(data) == "deny" and "mixer:scope" in data["reason"]
    assert rig.hook("gemini", tool(rig, "write_file", {"file_path": str(rig.proj / "src" / "a.py"), "content": "x"}))[1] is None


def test_replace_is_counted_and_scope_checked(rig):
    rig.run(["--saved", "scope", "add", "src/**"])
    ok = tool(rig, "replace", {"file_path": str(rig.proj / "src" / "app.py"), "instruction": "bump",
                               "old_string": "return 1", "new_string": "return 2"})
    bad = tool(rig, "replace", {"file_path": str(rig.proj / "README.md"), "instruction": "x", "old_string": "a",
                                "new_string": "b", "allow_multiple": True})
    assert rig.hook("gemini", ok)[1] is None and verdict(rig.hook("gemini", bad)[1]) == "deny"


def test_run_shell_command_uses_dir_path_for_relative_targets(rig):
    rig.run(["--saved", "scope", "add", "src/**"])
    inside = tool(rig, "run_shell_command", {"command": "touch a.py", "dir_path": str(rig.proj / "src")})
    outside = tool(rig, "run_shell_command", {"command": "touch a.py", "dir_path": str(rig.proj)})
    assert rig.hook("gemini", inside)[1] is None and verdict(rig.hook("gemini", outside)[1]) == "deny"
    assert verdict(rig.hook("gemini", tool(rig, "run_shell_command", {"command": "echo x > README.md"}))[1]) == "deny"


def test_plan_mode_read_only_shell(rig):
    rig.run(["--saved", "edits", "plan"])
    assert rig.hook("gemini", tool(rig, "run_shell_command", {"command": "git status"}))[1] is None
    assert verdict(rig.hook("gemini", tool(rig, "run_shell_command", {"command": "rm -rf x"}))[1]) == "deny"
    assert verdict(rig.hook("gemini", tool(rig, "write_file", {"file_path": str(rig.proj / "a"), "content": "x"}))[1]) == "deny"


def test_ask_degrades_to_deny_with_the_reason_why(rig):
    rig.run(["--saved", "edits", "ask"])
    data = rig.hook("gemini", tool(rig, "write_file", {"file_path": str(rig.proj / "src" / "b.py"), "content": "x"}))[1]
    assert verdict(data) == "deny" and "ask" in data["reason"].lower() and "agent-mixer edits auto" in data["reason"]


def test_before_agent_injects_the_rules_line(rig):
    assert rig.hook("gemini", event(rig, "BeforeAgent", prompt="go"))[1] is None
    rig.run(["--saved", "edits", "ask"])
    out = rig.hook("gemini", event(rig, "BeforeAgent", prompt="go"))[1]["hookSpecificOutput"]
    assert out["hookEventName"] == "BeforeAgent" and out["additionalContext"].startswith("Agent Mixer:")


def test_a_mixer_prompt_in_before_agent_is_handled(rig):
    data = rig.hook("gemini", event(rig, "BeforeAgent", "G2", prompt="/mixer edits plan"))[1]
    assert verdict(data) == "deny" and "plan" in data["reason"].lower()
    w = {"file_path": str(rig.proj / "src" / "a.py"), "content": "x"}
    assert verdict(rig.hook("gemini", tool(rig, "write_file", w, "G2"))[1]) == "deny"
    assert rig.hook("gemini", tool(rig, "write_file", w, "G3"))[1] is None


def test_each_before_agent_starts_a_new_turn(rig):
    rig.run(["--saved", "lines", "5"])
    three = "a\nb\nc\n"
    w = lambda n: verdict(rig.hook("gemini", tool(rig, "write_file", {"file_path": str(rig.proj / "src" / n), "content": three}))[1])
    assert (w("a.py"), w("b.py")) == (None, "deny")
    rig.hook("gemini", event(rig, "BeforeAgent", prompt="again"))
    assert w("c.py") is None


def test_stdout_is_json_only_and_never_a_crash(rig):
    rc, out, err = rig.run(["hook", "gemini"], "{}")
    assert rc == 0 and out == ""
    rc, out, err = rig.run(["hook", "gemini"], "[1, 2]")
    assert rc == 2 and err.strip()
    rig.run(["--saved", "scope", "add", "src/**"])
    rc, out, _ = rig.run(["hook", "gemini"], __import__("json").dumps(
        tool(rig, "write_file", {"file_path": str(rig.proj / "README.md"), "content": "x"})))
    import json
    assert rc == 0 and json.loads(out)["decision"] == "deny"


def test_other_tools_are_silent(rig):
    rig.run(["--saved", "edits", "plan"])
    assert rig.hook("gemini", tool(rig, "read_file", {"file_path": "x"}))[1] is None
    assert rig.hook("gemini", event(rig, "AfterTool", tool_name="write_file"))[1] is None
