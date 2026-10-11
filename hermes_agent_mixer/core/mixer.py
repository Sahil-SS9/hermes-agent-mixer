"""Mixer state: per-session knob overrides over the plugin config defaults.

The host gives hooks a session identity, and the command handler resolves the
same identity from the host's session context, so state stays per-session with
a process-wide fallback when no session id is available (one-session surfaces).
"""

from __future__ import annotations

from threading import RLock
from typing import Any, Callable

from hermes_agent_mixer.core import settings as settings_mod

GLOBAL_SESSION = ""


class LinesState:
    """Current-turn counters, with atomic admission for concurrent tool calls."""

    def __init__(self) -> None:
        self._used: dict[tuple[str, str], int] = {}
        self._lock = RLock()

    def used(self, session_id: str, task_id: str) -> int:
        with self._lock:
            return self._used.get((session_id or "", task_id or ""), 0)

    def add(self, session_id: str, task_id: str, lines: int) -> None:
        if lines <= 0:
            return
        key = (session_id or "", task_id or "")
        with self._lock:
            self._used[key] = self._used.get(key, 0) + lines

    def reserve(self, session_id: str, task_id: str, lines: int, budget: int) -> tuple[bool, int]:
        """Check and reserve together; return (allowed, usage before this call)."""
        key = (session_id or "", task_id or "")
        with self._lock:
            used = self._used.get(key, 0)
            if used + lines > budget:
                return False, used
            self._used[key] = used + lines
            return True, used

    def reset_turn(self, session_id: str, task_id: str) -> None:
        """Discard the session's previous turn even if its task id changed."""
        session = session_id or ""
        with self._lock:
            self._used = {key: used for key, used in self._used.items() if key[0] != session}

    def session_used(self, session_id: str) -> int:
        """Current-turn usage only; previous turns are removed at pre_llm_call."""
        key = session_id or ""
        with self._lock:
            return sum(value for (session, _task), value in self._used.items() if session == key)

    def reset_all(self) -> None:
        with self._lock:
            self._used.clear()


class Mixer:
    """Per-session knob settings resolved against plugin config defaults."""

    def __init__(self, config_get: Callable[[str, Any], Any] | None = None):
        self._config_get = config_get or (lambda key, default=None: None)
        self._overrides: dict[str, dict[str, Any]] = {}
        self.lines_state = LinesState()

    # -- resolution ------------------------------------------------------

    def _config_default(self, knob: str):
        value = self._config_get(knob, None)
        if value is None:
            return settings_mod.defaults()[knob]
        return value

    def settings_for(self, session_id: str) -> dict:
        """Validated effective knobs: config defaults, overridden per session."""
        base = {knob: self._config_default(knob) for knob in ("edits", "scope", "lines", "deps")}
        override = self._overrides.get(self._key(session_id), {})
        merged = {**base, **override}
        return settings_mod.normalise(merged)

    # -- session overrides -------------------------------------------------

    @staticmethod
    def _key(session_id: str | None) -> str:
        return (session_id or "").strip() or GLOBAL_SESSION

    def set_session(self, session_id: str, knob: str, value) -> None:
        if not settings_mod.is_valid_knob(knob):
            raise KeyError(f"unknown knob: {knob}")
        key = self._key(session_id)
        self._overrides.setdefault(key, {})[knob] = value

    def reset_session(self, session_id: str) -> None:
        self._overrides.pop(self._key(session_id), None)

    def current_settings(self, session_id: str) -> dict:
        """Effective settings plus whether each knob comes from an override."""
        effective = self.settings_for(session_id)
        override = self._overrides.get(self._key(session_id), {})
        return {
            "session_key": self._key(session_id),
            "knobs": effective,
            "overridden": sorted(override),
        }

    def on_unload(self) -> None:
        self._overrides.clear()