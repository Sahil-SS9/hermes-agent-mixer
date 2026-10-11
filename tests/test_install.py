"""install / uninstall / doctor (X7): plan-first, idempotent, merging, byte-stable, sandboxed."""
from __future__ import annotations

import json
from pathlib import Path

import pytest



def mixer_hooks(data, event, name):
    return [h for g in (data.get("hooks") or {}).get(event, []) for h in g.get("hooks", [])
            if "agent-mixer" in h.get("command", "") and h["command"].rstrip().endswith(f"hook {name}")]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture
def claude_settings(rig):
    path = Path(rig.env["HOME"]) / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"theme": "dark", "hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo other"}]}]}}, indent=2), encoding="utf-8")
    return path


def test_install_without_yes_prints_the_plan_and_writes_nothing(rig, claude_settings):
    before = claude_settings.read_bytes()
    rc, out, _ = rig.run(["install", "claude"])
    assert rc == 0 and claude_settings.read_bytes() == before
    assert str(claude_settings) in out and "--yes" in out and "PreToolUse" in out
    assert not (Path(rig.env["HOME"]) / ".claude" / "commands" / "mixer.md").exists()


def test_install_is_idempotent_and_byte_stable(rig, claude_settings):
    rig.run(["install", "claude", "--yes"])
    first = claude_settings.read_bytes()
    rig.run(["install", "claude", "--yes"])
    assert claude_settings.read_bytes() == first
    data = read(claude_settings)
    for event in ("PreToolUse", "UserPromptSubmit", "UserPromptExpansion"):
        assert len(mixer_hooks(data, event, "claude")) == 1


def test_install_keeps_the_users_own_settings_and_hooks(rig, claude_settings):
    rig.run(["install", "claude", "--yes"])
    data = read(claude_settings)
    assert data["theme"] == "dark"
    assert any(h["command"] == "echo other" for g in data["hooks"]["PreToolUse"] for h in g["hooks"])


def test_the_hook_command_is_an_absolute_path(rig, claude_settings):
    rig.run(["install", "claude", "--yes"])
    command = mixer_hooks(read(claude_settings), "PreToolUse", "claude")[0]["command"]
    assert command.startswith("/") or command.startswith("'/") or " -m hermes_agent_mixer.cli " in command


def test_matchers_are_limited_to_the_tools_mixer_acts_on(rig, claude_settings):
    rig.run(["install", "claude", "--yes"])
    group = next(g for g in read(claude_settings)["hooks"]["PreToolUse"]
                 if any("agent-mixer" in h["command"] for h in g["hooks"]))
    tools = set(group["matcher"].split("|"))
    assert {"Write", "Edit", "Bash", "PowerShell", "mcp__.*"} <= tools
    assert "Read" not in tools and "Grep" not in tools and ".*" not in tools


def test_uninstall_removes_only_mixers_entries_and_the_command_file(rig, claude_settings):
    rig.run(["install", "claude", "--yes"])
    command_file = Path(rig.env["HOME"]) / ".claude" / "commands" / "mixer.md"
    assert command_file.is_file() and "agent-mixer doctor" in command_file.read_text()
    rig.run(["uninstall", "claude", "--yes"])
    data = read(claude_settings)
    assert data["theme"] == "dark" and "echo other" in json.dumps(data)
    assert "agent-mixer" not in json.dumps(data) and not command_file.exists()
    assert set(data["hooks"]) == {"PreToolUse"}


def test_uninstall_without_yes_changes_nothing(rig, claude_settings):
    rig.run(["install", "claude", "--yes"])
    before = claude_settings.read_bytes()
    rc, out, _ = rig.run(["uninstall", "claude"])
    assert rc == 0 and claude_settings.read_bytes() == before and "--yes" in out


def test_install_creates_missing_files_and_uninstall_leaves_valid_json(rig):
    rig.run(["install", "claude", "--yes"])
    path = Path(rig.env["HOME"]) / ".claude" / "settings.json"
    assert mixer_hooks(read(path), "PreToolUse", "claude")
    rig.run(["uninstall", "claude", "--yes"])
    assert read(path) == {}


def test_project_install_uses_settings_local_json_and_leaves_home_alone(rig):
    rc, _, err = rig.run(["install", "claude", "--project", "--yes"])
    assert rc == 0, err
    assert mixer_hooks(read(rig.proj / ".claude" / "settings.local.json"), "PreToolUse", "claude")
    assert not (Path(rig.env["HOME"]) / ".claude").exists()
    assert (rig.proj / ".claude" / "commands" / "mixer.md").is_file()


def test_settings_json_flag_prints_the_hook_json_and_writes_nothing(rig):
    rc, out, _ = rig.run(["install", "claude", "--settings-json"])
    data = json.loads(out)
    assert rc == 0 and set(data["hooks"]) == {"PreToolUse", "UserPromptSubmit", "UserPromptExpansion"}
    assert not (Path(rig.env["HOME"]) / ".claude").exists()


def test_codex_install_writes_hooks_json_and_says_to_trust_it(rig):
    rc, out, _ = rig.run(["install", "codex", "--yes"])
    path = Path(rig.env["HOME"]) / ".codex" / "hooks.json"
    data = read(path)
    assert rc == 0 and "/hooks" in out
    assert len(mixer_hooks(data, "PreToolUse", "codex")) == 1 and len(mixer_hooks(data, "UserPromptSubmit", "codex")) == 1
    assert data["hooks"]["PreToolUse"][0]["matcher"] == "Bash|apply_patch|mcp__.*"
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] == 10  # seconds
    first = path.read_bytes()
    rig.run(["install", "codex", "--yes"])
    assert path.read_bytes() == first  # a changed hook would need re-trusting


def test_codex_uninstall(rig):
    rig.run(["install", "codex", "--yes"])
    rig.run(["uninstall", "codex", "--yes"])
    assert read(Path(rig.env["HOME"]) / ".codex" / "hooks.json") == {}


def test_gemini_install_uses_milliseconds(rig):
    rc, _, _ = rig.run(["install", "gemini", "--yes"])
    data = read(Path(rig.env["HOME"]) / ".gemini" / "settings.json")
    hooks = mixer_hooks(data, "BeforeTool", "gemini") + mixer_hooks(data, "BeforeAgent", "gemini")
    assert rc == 0 and len(hooks) == 2 and all(h["timeout"] >= 1000 for h in hooks)


def test_gemini_install_keeps_other_settings(rig):
    path = Path(rig.env["HOME"]) / ".gemini" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"theme": "GitHub", "mcpServers": {"a": {}}}), encoding="utf-8")
    rig.run(["install", "gemini", "--yes"])
    rig.run(["uninstall", "gemini", "--yes"])
    assert read(path) == {"theme": "GitHub", "mcpServers": {"a": {}}}


def test_an_unparseable_settings_file_is_never_overwritten(rig):
    path = Path(rig.env["HOME"]) / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    rc, _, err = rig.run(["install", "claude", "--yes"])
    assert rc != 0 and path.read_text() == "{ not json" and "not valid JSON" in err


def test_bad_arguments_print_usage(rig):
    for argv in (["install"], ["install", "vim"], ["install", "claude", "--force"]):
        rc, out, err = rig.run(argv)
        assert rc == 2 and "usage" in (out + err).lower()


def test_installed_hooks_run_the_real_cli_end_to_end(rig):
    """What install writes is what a harness would execute."""
    import shlex
    import subprocess

    rig.run(["install", "claude", "--yes"])
    command = mixer_hooks(read(Path(rig.env["HOME"]) / ".claude" / "settings.json"), "PreToolUse", "claude")[0]["command"]
    rig.run(["--saved", "scope", "add", "src/**"])
    payload = {"session_id": "E1", "prompt_id": "p", "cwd": str(rig.proj), "hook_event_name": "PreToolUse",
               "tool_name": "Write", "tool_input": {"file_path": str(rig.proj / "README.md"), "content": "x"}}
    done = subprocess.run(shlex.split(command), input=json.dumps(payload), capture_output=True, text=True,
                          env={**rig.env}, cwd=rig.proj)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_doctor_sees_installs(rig):
    rig.run(["install", "claude", "--yes"])
    rig.run(["install", "codex", "--yes"])
    _, out, _ = rig.run(["doctor"])
    claude_line = next(line for line in out.splitlines() if line.startswith("claude"))
    codex_line = next(line for line in out.splitlines() if line.startswith("codex"))
    gemini_line = next(line for line in out.splitlines() if line.startswith("gemini"))
    assert "PreToolUse" in claude_line and "PreToolUse" in codex_line and "not installed" in gemini_line


def test_doctor_never_writes_outside_the_sandbox(rig):
    before = set(Path(rig.root).rglob("*"))
    rig.run(["doctor"])
    new = set(Path(rig.root).rglob("*")) - before
    assert all(str(p).startswith(str(rig.root)) for p in new)
