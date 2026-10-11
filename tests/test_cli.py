"""The agent-mixer CLI (X2, X3): grammar, session targeting, saved settings, startup cost."""
from __future__ import annotations

import json
import subprocess
import sys



def claude_pre(sid, proj, tool, tool_input, prompt_id="p1"):
    return {"session_id": sid, "prompt_id": prompt_id, "cwd": str(proj), "permission_mode": "default",
            "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "tool_use_id": "t"}


def test_saved_scope_add_writes_the_settings_file(rig):
    rc, out, err = rig.run(["--saved", "scope", "add", "src/**"])
    assert rc == 0, err
    assert json.loads(rig.settings_file.read_text())["scope"] == ["src/**"]
    assert "saved" in out.lower()


def test_saved_dials_and_the_int_budget(rig):
    rig.run(["--saved", "edits", "ask"])
    rig.run(["--saved", "lines", "40"])
    rig.run(["--saved", "deps", "block"])
    assert json.loads(rig.settings_file.read_text()) == {"edits": "ask", "lines": 40, "deps": "block"}
    rig.run(["--saved", "lines", "off"])
    assert json.loads(rig.settings_file.read_text())["lines"] == 0


def test_saved_scope_remove_and_clear(rig):
    rig.run(["--saved", "scope", "add", "a/**"])
    rig.run(["--saved", "scope", "add", "b/**"])
    rig.run(["--saved", "scope", "remove", "a/**"])
    assert json.loads(rig.settings_file.read_text())["scope"] == ["b/**"]
    rig.run(["--saved", "scope", "clear"])
    assert json.loads(rig.settings_file.read_text())["scope"] == []


def test_bad_values_change_nothing(rig):
    rc, out, _ = rig.run(["--saved", "edits", "plna"])
    assert "unknown" in out.lower()
    assert not rig.settings_file.exists()


def test_session_flag_works_for_a_session_no_hook_has_seen(rig):
    rc, out, err = rig.run(["--session", "S9", "edits", "plan"])
    assert rc == 0, err
    rc, data, _ = rig.hook("claude", claude_pre("S9", rig.proj, "Write", {"file_path": str(rig.proj / "a.py"), "content": "x"}))
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_without_a_flag_the_latest_session_in_this_folder_is_used_and_named(rig):
    rig.hook("claude", claude_pre("OLD", rig.proj, "Bash", {"command": "ls"}))
    rig.hook("claude", claude_pre("NEWER", rig.proj, "Bash", {"command": "ls"}))
    rc, out, _ = rig.run(["edits", "plan"])
    assert rc == 0 and "NEWER" in out
    _, board, _ = rig.run(["board"])
    assert "NEWER" in board and "plan" in board


def test_without_a_flag_and_no_session_seen_it_errors_and_suggests_saved(rig):
    rc, out, err = rig.run(["edits", "plan"])
    assert rc != 0 and "--saved" in (out + err)
    rc, out, err = rig.run(["board"])
    assert rc != 0 and "--saved" in (out + err)


def test_another_folders_session_is_not_picked(rig, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    rig.hook("claude", claude_pre("THEIRS", other, "Bash", {"command": "ls"}), cwd=other)
    rc, out, err = rig.run(["board"])
    assert rc != 0 and "THEIRS" not in out


def test_board_for_a_named_session_shows_where_each_value_comes_from(rig):
    rig.run(["--saved", "deps", "block"])
    rig.run(["--session", "S1", "edits", "plan"])
    rc, out, _ = rig.run(["--session", "S1", "board"])
    assert "(session)" in out and "(saved)" in out and "(default)" in out


def test_session_changes_do_not_touch_saved_settings(rig):
    rig.run(["--session", "S1", "edits", "plan"])
    assert not rig.settings_file.exists()


def test_save_one_dial_from_a_session_target(rig):
    rig.run(["--session", "S1", "save", "deps", "block"])
    assert json.loads(rig.settings_file.read_text()) == {"deps": "block"}


def test_agent_mixer_home_overrides_both_locations(rig, tmp_path):
    home = tmp_path / "amhome"
    rig.run(["--saved", "edits", "ask"], extra_env={"AGENT_MIXER_HOME": str(home)})
    rig.run(["--session", "S1", "edits", "plan"], extra_env={"AGENT_MIXER_HOME": str(home)})
    assert (home / "settings.json").is_file() and (home / "state" / ".lock").is_file()
    assert not rig.settings_file.exists()


def test_default_locations_follow_the_xdg_variables(rig):
    rig.run(["--saved", "edits", "ask"])
    rig.run(["--session", "S1", "edits", "plan"])
    assert rig.settings_file.is_file() and (rig.state_dir / ".lock").is_file()


def test_unknown_input_prints_usage_and_fails(rig):
    rc, out, err = rig.run(["frobnicate"])
    assert rc != 0 and "usage" in (out + err).lower()
    rc, out, err = rig.run([])
    assert rc != 0 and "usage" in (out + err).lower()


def test_version_flag(rig):
    import hermes_agent_mixer

    rc, out, _ = rig.run(["--version"])
    assert rc == 0 and hermes_agent_mixer.__version__ in out


def test_the_cli_imports_nothing_heavy():
    code = ("import sys, hermes_agent_mixer.cli\n"
            "bad = [m for m in ('argparse', 'asyncio', 'yaml', 'gateway', 'tools', 'hermes_cli', 'subprocess', "
            "'hermes_agent_mixer.hermes') if m in sys.modules]\n"
            "print(','.join(bad))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == ""


def test_a_hook_never_imports_the_hermes_adapter(rig):
    code = ("import sys, json\n"
            "from hermes_agent_mixer import cli\n"
            "cli.main(['hook', 'claude'], stdin=json.dumps({'session_id': 's', 'hook_event_name': 'Notification'}), "
            "env={'HOME': '/nonexistent'}, cwd='/')\n"
            "print(','.join(m for m in ('argparse', 'asyncio', 'yaml', 'hermes_agent_mixer.hermes') if m in sys.modules))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == ""


def test_python_dash_m_entry_point_works(rig):
    done = subprocess.run([sys.executable, "-m", "hermes_agent_mixer.cli", "--version"],
                          capture_output=True, text=True)
    assert done.returncode == 0 and "agent-mixer" in done.stdout


def test_doctor_lists_every_harness_and_the_settings_location(rig):
    rc, out, _ = rig.run(["doctor"])
    low = out.lower()
    assert rc == 0 and all(h in low for h in ("claude", "codex", "gemini"))
    assert str(rig.settings_file.parent) in out and str(rig.state_dir) in out
    assert "hermes" in low  # says Hermes keeps its own saved values


def test_doctor_reports_an_unreadable_settings_file(rig):
    rig.settings_file.parent.mkdir(parents=True)
    rig.settings_file.write_text("{broken", encoding="utf-8")
    rc, out, _ = rig.run(["doctor"])
    assert "broken" in out.lower() or "unreadable" in out.lower() or "not valid" in out.lower()
