"""Hermes plugin entry point for Agent Mixer.

Registers the ``/mixer`` slash command and the ``pre_tool_call`` /
``pre_llm_call`` hooks. Enforcement logic lives in tested modules
(settings, mixer, scope, terminal, decisions); this module is only wiring.
"""

from __future__ import annotations

from typing import Any

from hermes_agent_mixer import decisions
from hermes_agent_mixer.mixer import Mixer

_HOOKS_WIRED: list[str] = []

_MIXER: Mixer | None = None
_CONFIG_GET: Any = None


def get_mixer() -> Mixer:
    """The process-wide Mixer (created lazily so tests can drive it)."""
    global _MIXER
    if _MIXER is None:
        _MIXER = Mixer(config_get=_CONFIG_GET or _no_config)
    return _MIXER


def reset_mixer() -> None:
    """Drop the process-wide Mixer (test/reset seam)."""
    global _MIXER, _CONFIG_GET
    _MIXER = None
    _CONFIG_GET = None


def _no_config(key: str, default=None):
    return None


def _pre_tool_call(tool_name: str = "", args: dict | None = None, task_id: str = "",
                   session_id: str = "", **kwargs: Any) -> dict[str, Any] | None:
    """Ordered decision for one tool call. None = allow."""
    mixer = get_mixer()
    knobs = mixer.settings_for(session_id or task_id)
    return decisions.evaluate(tool_name, args or {}, knobs)


def _pre_llm_call(session_id: str = "", task_id: str = "", **kwargs: Any) -> None:
    """Turn boundary. The lines counter reset is added with the lines knob (S3)."""
    return None


def _mixer_command(raw_args: str = "") -> str | None:
    """Scaffold placeholder; the real board arrives with S4."""
    return "Agent Mixer: scaffolding in place (knobs land in S2-S4)"


def register(ctx: Any) -> None:
    """Wire Agent Mixer's hooks, command and unload callback into the host."""
    global _CONFIG_GET
    _CONFIG_GET = ctx.get_config
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
    mixer = _MIXER
    if mixer is not None:
        mixer.on_unload()
    _HOOKS_WIRED = []