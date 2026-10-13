"""Gemini CLI adapter (X6, D11). https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md

BeforeTool carries ``tool_name`` and ``tool_input``; BeforeAgent carries ``prompt`` and has no turn id,
so each BeforeAgent starts a new turn. stdout must be JSON only. Exit 2 blocks; any other non-zero exit
only warns (fails open), so a handled failure still exits 0 with a deny.
"""
from __future__ import annotations

import os
import time
from fnmatch import fnmatchcase
from typing import Any

from ..core.calls import Call
from ..harness.common import Event, mixer_command_args, write_call

NAME = "gemini"
DISPLAY = "Gemini CLI"
CAN_ASK = False

TOOL_MATCHER = "write_file|replace|run_shell_command|mcp__.*"


def _call(tool: str, args: dict[str, Any], cwd: str, extras: list[str]) -> Call | None:
    if tool == "write_file":
        return write_call(tool, args)
    if tool == "replace":
        return Call("edit", tool, path=str(args.get("file_path") or ""), old=_text(args.get("old_string")),
                    new=_text(args.get("new_string")), replace_all=bool(args.get("allow_multiple")))
    if tool == "run_shell_command":
        where = args.get("dir_path")
        return Call("shell", tool, command=_text(args.get("command")), cwd=where if isinstance(where, str) and where else cwd)
    if extras and any(fnmatchcase(tool, glob) for glob in extras):
        return write_call(tool, args)
    return None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def parse(payload: dict[str, Any], environ: dict[str, str], extras: list[str]) -> Event | None:
    name = payload.get("hook_event_name")
    session = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or environ.get("GEMINI_PROJECT_DIR") or os.getcwd())
    workspace = environ.get("GEMINI_PROJECT_DIR") or cwd
    if not session:
        return None
    if name == "BeforeTool":
        args = payload.get("tool_input")
        call = _call(str(payload.get("tool_name") or ""), args if isinstance(args, dict) else {}, cwd, extras)
        return Event("tool", session, cwd, workspace, None, call, hook_event=name) if call else None
    if name == "BeforeAgent":
        return Event("prompt", session, cwd, workspace, f"gemini-{time.time_ns()}",
                     mixer_args=mixer_command_args(str(payload.get("prompt") or "")), hook_event=name)
    return None


def render_tool(action: str, message: str, event: Event) -> dict:
    return {"decision": "deny", "reason": message}


def render_context(text: str, event: Event) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "BeforeAgent", "additionalContext": text}}


def render_command(text: str, event: Event) -> dict:
    return {"decision": "deny", "reason": text}
