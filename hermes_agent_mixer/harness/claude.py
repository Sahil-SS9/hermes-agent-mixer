"""Claude Code adapter (X4). https://code.claude.com/docs/en/hooks

Events: PreToolUse, UserPromptSubmit, UserPromptExpansion. ``session_id`` is stable across subagents
(which add ``agent_id``), ``prompt_id`` is the turn. Output is the documented ``hookSpecificOutput``
for PreToolUse and ``{"decision": "block", "reason": ...}`` to stop a prompt.
"""
from __future__ import annotations

import os
from typing import Any

from hermes_agent_mixer.core.calls import Call
from hermes_agent_mixer.harness.common import Event, mixer_command_args, write_call

NAME = "claude"
DISPLAY = "Claude Code"
CAN_ASK = True

TOOL_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell|mcp__.*"


def _call(tool: str, args: dict[str, Any], cwd: str, extras: list[str]) -> Call | None:
    from fnmatch import fnmatchcase

    if tool == "Write":
        return write_call(tool, args)
    if tool == "Edit":
        return Call("edit", tool, path=str(args.get("file_path") or ""), old=_text(args.get("old_string")),
                    new=_text(args.get("new_string")), replace_all=bool(args.get("replace_all")))
    if tool == "MultiEdit":
        edits = [e for e in (args.get("edits") or []) if isinstance(e, dict)]
        return Call("edit", tool, path=str(args.get("file_path") or ""),
                    old="\n".join(_text(e.get("old_string")) for e in edits),
                    new="\n".join(_text(e.get("new_string")) for e in edits))
    if tool == "NotebookEdit":
        return write_call(tool, {"file_path": args.get("notebook_path"), "content": args.get("new_source")})
    if tool in ("Bash", "PowerShell"):
        return Call("shell", tool, command=_text(args.get("command")), shell="powershell" if tool == "PowerShell" else "posix",
                    cwd=cwd or None)
    if extras and any(fnmatchcase(tool, glob) for glob in extras):
        return write_call(tool, args)
    return None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def parse(payload: dict[str, Any], environ: dict[str, str], extras: list[str]) -> Event | None:
    name = payload.get("hook_event_name")
    session = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    workspace = environ.get("CLAUDE_PROJECT_DIR") or cwd
    turn = payload.get("prompt_id")
    turn = str(turn) if turn else None
    if not session:
        return None
    if name == "PreToolUse":
        args = payload.get("tool_input")
        call = _call(str(payload.get("tool_name") or ""), args if isinstance(args, dict) else {}, cwd, extras)
        return Event("tool", session, cwd, workspace, turn, call, hook_event=name) if call else None
    if name == "UserPromptSubmit":
        return Event("prompt", session, cwd, workspace, turn, mixer_args=mixer_command_args(str(payload.get("prompt") or "")),
                     hook_event=name)
    if name == "UserPromptExpansion":
        if payload.get("command_name") != "mixer":
            return None
        return Event("prompt", session, cwd, workspace, turn, mixer_args=str(payload.get("command_args") or "").strip(),
                     hook_event=name)
    return None


def render_tool(action: str, message: str, event: Event) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": action,
                                   "permissionDecisionReason": message}}


def render_context(text: str, event: Event) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event.hook_event or "UserPromptSubmit", "additionalContext": text}}


def render_command(text: str, event: Event) -> dict:
    return {"decision": "block", "reason": text}
