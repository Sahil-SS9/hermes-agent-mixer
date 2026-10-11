"""Mixer state: per-session knob overrides over the plugin config defaults.

The host gives hooks a session identity, and the command handler resolves the
same identity from the host's session context, so state stays per-session with
a process-wide fallback when no session id is available (one-session surfaces).
"""

from __future__ import annotations

from typing import Any, Callable

from hermes_agent_mixer import settings as settings_mod

GLOBAL_SESSION = ""


class Mixer:
    """Per-session knob settings resolved against plugin config defaults."""

    def __init__(self, config_get: Callable[[str, Any], Any] | None = None):
        self._config_get = config_get or (lambda key, default=None: None)
        self._overrides: dict[str, dict[str, Any]] = {}

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