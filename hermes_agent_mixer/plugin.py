"""Hermes plugin entry point for Agent Mixer.

Registers the ``/mixer`` slash command and the ``pre_tool_call`` /
``pre_llm_call`` hooks. Enforcement logic lands in S2-S4 behind tested
modules; the scaffold's hooks are permissive.
"""

from __future__ import annotations

from typing import Any

_HOOKS_WIRED: list[str] = []


def _pre_tool_call(**kwargs: Any) -> dict[str, Any] | None:
    """Scaffold: permissive. Real decisions arrive with S2-S3."""
    return None


def _pre_llm_call(session_id: str = "", **kwargs: Any) -> None:
    """Scaffold: turn boundary. Counter reset arrives with S3."""
    return None


def _mixer_command(raw_args: str = "") -> str | None:
    """Scaffold placeholder; the real board arrives with S4."""
    return "Agent Mixer: scaffolding in place (knobs land in S2-S4)"


def register(ctx: Any) -> None:
    """Wire Agent Mixer's hooks, command and unload callback into the host."""
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_command(
        "mixer",
        handler=_mixer_command,
        description="Show or change the Agent Mixer knobs (edits, scope, lines, deps)",
        args_hint="[edits ask|auto|plan] [scope ...] [lines N|off] [deps allow|ask|block] [save] [reset]",
    )
    ctx.on_unload(_on_unload)
    for hook_name in ("pre_tool_call", "pre_llm_call"):
        _HOOKS_WIRED.append(hook_name)


def _on_unload() -> None:
    """Clear module state so a reload starts fresh."""
    global _HOOKS_WIRED
    _HOOKS_WIRED = []