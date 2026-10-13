"""Codex adapter (X5, D11). https://developers.openai.com/codex/hooks

PreToolUse covers ``Bash``, ``apply_patch`` (``tool_input.command`` is the patch text) and ``mcp__*``.
Subagents report the parent's ``session_id``. ``turn_id`` is the turn. Codex treats ``ask`` (and
``continue``, ``stopReason``, ``suppressOutput`` on PreToolUse) as a failed hook and runs the tool, so
Mixer only ever emits a deny here. Hooks are "a useful guardrail, not a complete enforcement boundary".
"""
from __future__ import annotations

import os
from fnmatch import fnmatchcase
from typing import Any

from ..core.calls import Call
from ..harness.common import Event, mixer_command_args, write_call

NAME = "codex"
DISPLAY = "Codex"
CAN_ASK = False

TOOL_MATCHER = "Bash|apply_patch|mcp__.*"


def _call(tool: str, args: dict[str, Any], extras: list[str]) -> Call | None:
    if tool == "apply_patch":
        return Call("patch", tool, patch_text=str(args.get("command") or args.get("input") or args.get("patch") or ""))
    if tool == "Bash":
        return Call("shell", tool, command=str(args.get("command") or ""))
    if extras and any(fnmatchcase(tool, glob) for glob in extras):
        return write_call(tool, args)
    return None


def parse(payload: dict[str, Any], environ: dict[str, str], extras: list[str]) -> Event | None:
    name = payload.get("hook_event_name")
    session = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or os.getcwd())
    turn = payload.get("turn_id")
    turn = str(turn) if turn else None
    if not session:
        return None
    if name == "PreToolUse":
        args = payload.get("tool_input")
        call = _call(str(payload.get("tool_name") or ""), args if isinstance(args, dict) else {}, extras)
        return Event("tool", session, cwd, cwd, turn, call, hook_event=name) if call else None
    if name == "UserPromptSubmit":
        return Event("prompt", session, cwd, cwd, turn, mixer_args=mixer_command_args(str(payload.get("prompt") or "")),
                     hook_event=name)
    return None


def render_tool(action: str, message: str, event: Event) -> dict:
    """Always a deny: ``ask`` is a failed hook in Codex (the caller has already degraded it)."""
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": message}}


def render_context(text: str, event: Event) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}


def render_command(text: str, event: Event) -> dict:
    return {"decision": "block", "reason": text}
