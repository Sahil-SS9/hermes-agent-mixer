"""install / uninstall for Claude Code, Codex and Gemini CLI (X7).

Without ``--yes`` the plan is printed and nothing is written. Installs are idempotent, merge into
existing files (the user's own hooks stay), and are byte-stable on a re-run (Codex trusts a hook by its
hash). Hook commands use the absolute path of the ``agent-mixer`` executable.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from ..harness import claude, codex, gemini

MARKER = "agent-mixer"
TIMEOUT_SECONDS = 10
COMMAND_FILE = """---
description: Show or change Agent Mixer dials (edits, scope, lines, deps)
argument-hint: "[edits ask|auto|plan] [scope add|remove|clear <glob>] [lines N|off] [deps allow|ask|block]"
---
The Agent Mixer hook handles /mixer before the model sees it. If you can read this, the hook is not
installed or not running: tell the user to run `agent-mixer doctor`.
"""


def executable() -> str:
    """Absolute path of the agent-mixer executable (the hook command must not depend on PATH)."""
    argv0 = sys.argv[0] if sys.argv else ""
    if os.path.basename(argv0) in ("agent-mixer", "agent-mixer.exe") and os.path.isfile(argv0):
        return os.path.abspath(argv0)
    found = shutil.which("agent-mixer")
    if found:
        return os.path.abspath(found)
    return f"{shlex.quote(sys.executable)} -m hermes_agent_mixer.cli"


def _command(name: str) -> str:
    exe = executable()
    return f"{shlex.quote(exe) if ' ' in exe and ' -m ' not in exe else exe} hook {name}"


def _is_ours(hook: dict[str, Any], name: str) -> bool:
    command = str(hook.get("command", ""))
    return MARKER in command and command.rstrip().endswith(f"hook {name}")


def _entries(name: str) -> dict[str, list[dict[str, Any]]]:
    command = _command(name)
    if name == "claude":
        hook = {"type": "command", "command": command, "timeout": TIMEOUT_SECONDS}
        return {"PreToolUse": [{"matcher": claude.TOOL_MATCHER, "hooks": [dict(hook)]}],
                "UserPromptSubmit": [{"hooks": [dict(hook)]}],
                "UserPromptExpansion": [{"hooks": [dict(hook)]}]}
    if name == "codex":
        hook = {"type": "command", "command": command, "timeout": TIMEOUT_SECONDS}
        return {"PreToolUse": [{"matcher": codex.TOOL_MATCHER, "hooks": [dict(hook)]}],
                "UserPromptSubmit": [{"hooks": [dict(hook)]}]}
    hook = {"name": "agent-mixer", "type": "command", "command": command, "timeout": TIMEOUT_SECONDS * 1000}
    return {"BeforeTool": [{"matcher": gemini.TOOL_MATCHER, "hooks": [dict(hook)]}],
            "BeforeAgent": [{"hooks": [dict(hook)]}]}


def settings_path(name: str, home: str, here: str, project: bool) -> Path:
    base = Path(here) if project else Path(home)
    if name == "claude":
        return base / ".claude" / ("settings.local.json" if project else "settings.json")
    if name == "codex":
        return base / ".codex" / "hooks.json"
    return base / ".gemini" / "settings.json"


def command_file(home: str, here: str, project: bool) -> Path:
    return (Path(here) if project else Path(home)) / ".claude" / "commands" / "mixer.md"


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a JSON object")
    return data


def _strip_ours(data: dict[str, Any], name: str) -> None:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept = []
        for group in groups:
            inner = [h for h in (group.get("hooks") or []) if not _is_ours(h, name)] if isinstance(group, dict) else None
            if inner is None:
                kept.append(group)
            elif inner:
                kept.append({**group, "hooks": inner})
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del data["hooks"]


def merged(data: dict[str, Any], name: str, install: bool) -> dict[str, Any]:
    out = json.loads(json.dumps(data))
    _strip_ours(out, name)
    if install:
        hooks = out.setdefault("hooks", {})
        for event, groups in _entries(name).items():
            hooks.setdefault(event, []).extend(groups)
    return out


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def run(action: str, args: list[str], environ, here: str) -> int:
    flags = {a for a in args if a.startswith("--")}
    names = [a for a in args if not a.startswith("--")]
    unknown = flags - {"--project", "--yes", "--settings-json"}
    if len(names) != 1 or names[0] not in ("claude", "codex", "gemini") or unknown:
        print("usage: agent-mixer install|uninstall claude|codex|gemini [--project] [--yes] [--settings-json]",
              file=sys.stderr)
        return 2
    name = names[0]
    install = action == "install"
    project = "--project" in flags
    home = environ.get("HOME") or environ.get("USERPROFILE") or os.path.expanduser("~")
    if "--settings-json" in flags:
        print(_dump({"hooks": _entries(name)}), end="")
        return 0
    path = settings_path(name, home, here, project)
    try:
        before = _load(path)
    except ValueError as exc:
        print(f"agent-mixer: {path} is not valid JSON ({exc}); fix or move it first.", file=sys.stderr)
        return 1
    after = merged(before, name, install)
    new_text = _dump(after) if (after or path.is_file()) else ""
    extras = []
    if name == "claude":
        extras.append((command_file(home, here, project), COMMAND_FILE if install else None))
    verb = "write" if install else "remove Mixer's entries from"
    print(f"agent-mixer {action} {name}: will {verb} {path}")
    if install:
        for event, groups in _entries(name).items():
            matcher = groups[0].get("matcher")
            print(f"  {event}{' [' + matcher + ']' if matcher else ''}: {groups[0]['hooks'][0]['command']}")
    for target, body in extras:
        print(f"  {'write' if body else 'remove'} {target}")
    if "--yes" not in flags:
        print("Nothing was written. Re-run with --yes to apply.")
        return 0
    if before != after or not path.is_file():
        if after or install:
            _write(path, new_text)
        elif path.is_file():
            _write(path, _dump(after))
    for target, body in extras:
        if body is not None:
            _write(target, body)
        elif target.is_file():
            target.unlink()
    print("Done.")
    if install and name == "codex":
        print("Codex only runs hooks you have trusted: open Codex, run /hooks, and trust the Agent Mixer hooks "
              "(trust is keyed to the hook's hash, so re-trust after any change).")
    if install and name == "gemini":
        print("Restart Gemini CLI so it reads the new hooks. Timeouts are in milliseconds.")
    if install and name == "claude":
        print("Restart Claude Code (or run /hooks to check). `/mixer` now works in the prompt.")
    print("Reminder: Mixer sees tool calls, not system calls; terminal and code-running tools are best effort.")
    return 0
