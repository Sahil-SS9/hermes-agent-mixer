"""Hermes plugin entry point for Agent Mixer.

Registers the ``/mixer`` slash command and the ``pre_tool_call`` /
``pre_llm_call`` hooks. Enforcement logic lives in tested modules
(settings, mixer, scope, terminal, decisions); this module is only wiring.
"""

from __future__ import annotations

from typing import Any

from hermes_agent_mixer import decisions
from hermes_agent_mixer.board import handle_command as _board_handle
from hermes_agent_mixer.mixer import Mixer
from hermes_agent_mixer import session_key as _session_key_mod

_HOOKS_WIRED: list[str] = []

_MIXER: Mixer | None = None
_CONFIG_GET: Any = None
_CONFIG_SET: Any = None
_current_session_key = _session_key_mod.current_session_key


def get_mixer() -> Mixer:
    """The process-wide Mixer (created lazily so tests can drive it)."""
    global _MIXER
    if _MIXER is None:
        _MIXER = Mixer(config_get=_CONFIG_GET or _no_config)
    return _MIXER


def reset_mixer() -> None:
    """Drop the process-wide Mixer (test/reset seam)."""
    global _MIXER, _CONFIG_GET, _CONFIG_SET
    _MIXER = None
    _CONFIG_GET = None
    _CONFIG_SET = None


def _no_config(key: str, default=None):
    return None


def _pre_tool_call(tool_name: str = "", args: dict | None = None, task_id: str = "",
                   session_id: str = "", **kwargs: Any) -> dict[str, Any] | None:
    """Ordered decision for one tool call. None = allow."""
    mixer = get_mixer()
    session_key = (session_id or "").strip() or (task_id or "").strip()
    knobs = mixer.settings_for(session_key)
    return decisions.evaluate(
        tool_name, args or {}, knobs, mixer.lines_state,
        session_id=session_key, task_id=task_id or "",
    )


def _pre_llm_call(session_id: str = "", task_id: str = "", **kwargs: Any) -> None:
    """Turn boundary: reset this turn's lines counter (fires once per turn)."""
    session_key = (session_id or "").strip() or (task_id or "").strip()
    get_mixer().lines_state.reset_turn(session_key, task_id or "")
    return None


def _mixer_command(raw_args: str = "") -> str | None:
    """/mixer board and subcommands; writes via the host-owned config writer."""
    session = _current_session_key()
    mixer = get_mixer()
    return _board_handle(
        raw_args, mixer, session,
        save=_CONFIG_SET,
        approvals_mode=_approvals_mode(),
    )


def _approvals_mode() -> str | None:
    """Hermes' current approvals mode, for context display only.

    Plugins have no ctx API for top-level config; this mirrors how bundled
    plugins read host config (guarded, display-only)."""
    try:
        from hermes_cli.config import load_config_readonly

        mode = ((load_config_readonly() or {}).get("approvals") or {}).get("mode")
        return str(mode) if isinstance(mode, str) and mode else None
    except Exception:
        return None


def register(ctx: Any) -> None:
    """Wire Agent Mixer's hooks, command and unload callback into the host."""
    global _CONFIG_GET, _CONFIG_SET
    _CONFIG_GET = ctx.get_config
    _CONFIG_SET = getattr(ctx, "set_config", None)
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
    reset_mixer()
    _HOOKS_WIRED = []