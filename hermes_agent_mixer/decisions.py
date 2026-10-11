"""Decision engine for Agent Mixer.

Order: plan -> scope -> deps -> lines -> ask. The first block wins. Returns a
directive dict ({"action": "block"|"approve"|"modify", ...}) or None to allow.
The deps and lines stages are slots filled in S3; before that they no-op.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_agent_mixer import scope as scope_mod
from hermes_agent_mixer import terminal as terminal_mod

_FILE_TOOLS = ("write_file", "patch")

_PLAN_MESSAGE_WRITE = (
    "blocked by mixer:edits: plan mode is read-only. {tool} was prevented. "
    "Leave it with /mixer edits auto (or ask)."
)

_PLAN_MESSAGE_TERMINAL = (
    "blocked by mixer:edits: plan mode limits terminal to read-only commands. "
    "Segment {index} is not read-only. Leave it with /mixer edits auto (or ask)."
)

_ASK_MESSAGE = (
    "mixer:edits needs your approval for {tool}. The call waits for you - "
    "approve, always-allow (remembered per rule), or deny."
)


def evaluate(tool_name: str, args: dict[str, Any], knobs: dict[str, Any]) -> dict[str, str] | None:
    """Run the ordered stages and return the winning directive (or None)."""
    edits = (knobs.get("edits") or "auto").lower()
    scope_globs = [str(g) for g in (knobs.get("scope") or [])]
    root_value = knobs.get("root")
    root = Path(str(root_value)) if root_value else Path.cwd()

    if tool_name in _FILE_TOOLS:
        if edits == "plan":
            return {"action": "block", "message": _PLAN_MESSAGE_WRITE.format(tool=tool_name)}
        message = scope_mod.check_scope(str(args.get("path") or ""), scope_globs, root)
        if message:
            return {"action": "block", "message": message}
        # deps (S3) and lines (S3) stages go here, before ask.
        if edits == "ask":
            return {
                "action": "approve",
                "message": _ASK_MESSAGE.format(tool=tool_name),
                "rule_key": "mixer:edits",
            }
        return None

    if tool_name == "execute_code":
        if edits == "plan":
            return {"action": "block", "message": _PLAN_MESSAGE_WRITE.format(tool=tool_name)}
        return None

    if tool_name == "terminal":
        if edits == "plan":
            all_read_only, bad_index = terminal_mod.classify_command(str(args.get("command") or ""))
            if not all_read_only:
                return {
                    "action": "block",
                    "message": _PLAN_MESSAGE_TERMINAL.format(index=bad_index + 1),
                }
        # deps stage (S3) goes here.
        return None

    return None