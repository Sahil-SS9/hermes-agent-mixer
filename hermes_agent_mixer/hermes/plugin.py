"""Hermes plugin entry point for Agent Mixer.

Registers the ``/mixer`` slash command and the ``pre_tool_call``, ``pre_llm_call``,
``subagent_start`` and ``subagent_stop`` hooks. Session identity follows D1 and D2:

* hooks use the ``session_id`` keyword the host passes; they never read env or ContextVars for it;
* the command takes ``HERMES_SESSION_ID`` from the ContextVar-aware reader; with none bound it falls
  back to the chat key the gateway binds, mapped to a session through ``pre_llm_call``; with
  nothing bound it refuses;
* subagents link to their parent and share its dials and per-turn budget.
"""

from __future__ import annotations

import logging
import time
from threading import RLock
from typing import Any

from hermes_agent_mixer.core import board, settings
from hermes_agent_mixer.core.mixer import Mixer
from hermes_agent_mixer.core.store import MemoryStore
from hermes_agent_mixer.hermes import host, tools
from hermes_agent_mixer.hermes.ports import HermesPorts

log = logging.getLogger("agent_mixer")

KEY_IDLE_SECONDS = 24 * 3600.0
MAX_KEYS = 1000

_MIXER: Mixer | None = None
_CONFIG_GET: Any = None
_CONFIG_SET: Any = None
_KEY_SID: dict[str, tuple[str, float]] = {}  # chat key -> (session id, last seen)
_PENDING: dict[str, list[tuple[str, Any]]] = {}  # chat key -> changes waiting for its next turn
_LOCK = RLock()


def _now() -> float:
    return time.time()


def _saved() -> dict:
    if _CONFIG_GET is None:
        return {}
    found = {}
    for key in settings.SAVED_KEYS:
        try:
            value = _CONFIG_GET(key, None)
        except Exception:  # noqa: BLE001 - a broken config read must not break enforcement
            value = None
        if value is not None:
            found[key] = value
    return found


def get_mixer() -> Mixer:
    """The process-wide Mixer (created lazily so tests can drive it)."""
    global _MIXER
    if _MIXER is None:
        _MIXER = Mixer(MemoryStore(), _saved, clock=lambda: _now())
    return _MIXER


def reset_mixer() -> None:
    """Drop all process state (test/reset seam)."""
    global _MIXER, _CONFIG_GET, _CONFIG_SET
    _MIXER = None
    _CONFIG_GET = None
    _CONFIG_SET = None
    with _LOCK:
        _KEY_SID.clear()
        _PENDING.clear()


def _extra_globs() -> list[str]:
    if _CONFIG_GET is None:
        return []
    value, ok = settings.coerce("extra_write_tools", _CONFIG_GET("extra_write_tools", None) or [])
    return value if ok else []


def _session(session_id: str, task_id: str) -> str:
    return (session_id or "").strip() or (task_id or "").strip()


# -- hooks ------------------------------------------------------------------------------------------


def _pre_tool_call(tool_name: str = "", args: dict | None = None, task_id: str = "",
                   session_id: str = "", **kwargs: Any) -> dict[str, Any] | None:
    """Ordered decision for one tool call. None = no opinion."""
    call = tools.to_call(tool_name, args, _extra_globs())
    if call is None:
        return None
    decision = get_mixer().decide(_session(session_id, task_id), call, HermesPorts(), task_id=task_id or None)
    return tools.to_directive(decision)


def _pre_llm_call(session_id: str = "", task_id: str = "", turn_id: str = "", parent_session_id: str = "",
                  **kwargs: Any) -> dict[str, str] | None:
    """Turn boundary: reset this turn's budget, learn the chat key, apply parked changes, state the rules."""
    mixer = get_mixer()
    sid = _session(session_id, task_id)
    if not sid:
        return None
    parent = (parent_session_id or "").strip()
    child = bool(parent) or mixer.parent_of(sid) is not None
    mixer.begin_turn(sid, turn_id or None, parent=parent or None)
    if not child:
        key = host.session_env("HERMES_SESSION_KEY").strip()
        if key:
            with _LOCK:
                _KEY_SID[key] = (sid, _now())
                waiting = _PENDING.pop(key, [])
                _prune_keys()
            for knob, value in waiting:
                try:
                    mixer.set_session(sid, knob, value)
                except (KeyError, ValueError):
                    log.warning("agent-mixer: dropped parked change %s=%r", knob, value)
    text = mixer.rules_line(sid)
    return {"context": text} if text else None


def _prune_keys() -> None:
    now = _now()
    for key in [k for k, (_s, seen) in _KEY_SID.items() if now - seen > KEY_IDLE_SECONDS]:
        _KEY_SID.pop(key, None)
    for key in sorted(_KEY_SID, key=lambda k: _KEY_SID[k][1])[: max(len(_KEY_SID) - MAX_KEYS, 0)]:
        _KEY_SID.pop(key, None)
    for key in [k for k in _PENDING if k not in _KEY_SID and len(_PENDING) > MAX_KEYS]:
        _PENDING.pop(key, None)


def _subagent_start(parent_session_id: str = "", child_session_id: str = "", **kwargs: Any) -> None:
    get_mixer().link_child(child_session_id or "", parent_session_id or "")


def _subagent_stop(child_session_id: str = "", **kwargs: Any) -> None:
    get_mixer().drop(child_session_id or "")


# -- the /mixer command -----------------------------------------------------------------------------


def _identify() -> tuple[str, str]:
    """('session', id) | ('key', chat key not yet mapped) | ('none', '')  (D1)."""
    sid = host.session_env("HERMES_SESSION_ID").strip()
    if sid:
        return "session", sid
    key = host.session_env("HERMES_SESSION_KEY").strip()
    if key:
        with _LOCK:
            mapped = _KEY_SID.get(key)
        return ("session", mapped[0]) if mapped else ("key", key)
    return "none", ""


class _HermesTarget(board.Target):
    def __init__(self, kind: str, ident: str) -> None:
        self.kind, self.ident = kind, ident
        self.name = ident if kind == "session" else ("" if kind == "none" else f"chat {ident}")

    def _parked(self) -> dict:
        with _LOCK:
            return dict(_PENDING.get(self.ident, []))

    def effective(self) -> settings.Effective:
        mixer = get_mixer()
        if self.kind == "session":
            return mixer.effective(self.ident)
        if self.kind == "key":
            return settings.resolve(_saved(), self._parked(), session=self.name)
        return settings.resolve(_saved(), None, session="")

    def _refuse(self) -> board.Refusal:
        return board.Refusal(
            "mixer: can't tell which chat or session this is (nothing is bound here), so nothing was "
            "changed. Set a saved default with `/mixer save <dial> <value>` (for example "
            "`/mixer save edits plan`) or in the plugin settings.")

    def set(self, knob: str, value: Any) -> str:
        if self.kind == "session":
            get_mixer().set_session(self.ident, knob, value)
            return f" (this session only: {self.ident})"
        if self.kind == "key":
            with _LOCK:
                waiting = [(k, v) for k, v in _PENDING.get(self.ident, []) if k != knob]
                waiting.append((knob, value))
                _PENDING[self.ident] = waiting
            return f" (this chat only: {self.ident}; applies from its next turn)"
        raise self._refuse()

    def reset(self) -> str:
        if self.kind == "session":
            get_mixer().reset_session(self.ident)
            return "mixer: reset to the saved defaults for this session."
        if self.kind == "key":
            with _LOCK:
                _PENDING.pop(self.ident, None)
            return "mixer: dropped the changes waiting for this chat's next turn."
        raise self._refuse()

    def _writer(self):
        if not callable(_CONFIG_SET):
            raise board.Refusal("mixer: save is not available here (config writer missing).")
        return _CONFIG_SET

    def save_current(self) -> str:
        if self.kind == "none":
            raise self._refuse()
        write = self._writer()
        eff = self.effective()
        for knob in settings.DIALS:
            write(knob, eff.values[knob])
        return "mixer: saved these as the plugin defaults (all new sessions start here)."

    def save_one(self, knob: str, value: Any) -> str:
        self._writer()(knob, value)
        shown = ", ".join(value) if isinstance(value, list) else value
        return f"mixer: saved {knob} = {shown or '(none)'} as the plugin default (all new sessions start here)."

    def saved_list(self, knob: str) -> list[str]:
        return list(settings.coerce(knob, _saved().get(knob) or [])[0])


def _mixer_command(raw_args: str = "") -> str | None:
    """/mixer board and subcommands; saved defaults go through the host-owned config writer."""
    kind, ident = _identify()
    return board.handle_command(raw_args, _HermesTarget(kind, ident))


# -- wiring -----------------------------------------------------------------------------------------


def register(ctx: Any) -> None:
    """Wire Agent Mixer's hooks, command and unload callback into the host."""
    global _CONFIG_GET, _CONFIG_SET
    _CONFIG_GET = ctx.get_config
    _CONFIG_SET = getattr(ctx, "set_config", None)
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("subagent_start", _subagent_start)
    ctx.register_hook("subagent_stop", _subagent_stop)
    ctx.register_command(
        "mixer",
        handler=_mixer_command,
        description="Show or change the Agent Mixer dials (edits, scope, lines, deps)",
        args_hint="[edits ask|auto|plan] [scope add|remove|clear <glob>] [lines N|off] [deps allow|ask|block] "
                  "[save [<dial> <value>]] [reset]",
    )
    ctx.on_unload(_on_unload)


def _on_unload() -> None:
    """Clear module state so a reload starts fresh."""
    mixer = _MIXER
    if mixer is not None:
        mixer.on_unload()
    reset_mixer()
