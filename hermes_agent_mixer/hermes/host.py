"""Session identity for the /mixer command handler.

The hooks receive ``session_id`` from the host payload, but a slash command
handler only gets the raw arguments string, so the handler resolves the same
identity through the host's session context instead of any mutable
"last seen" guess:

1. gateway ContextVar bridge (set while the gateway runs plugin handlers);
2. ``HERMES_SESSION_ID`` in the process environment (published by the CLI
   and kept in sync on session switches);
3. empty string: single-session surfaces share process-wide fallback state.
"""

from __future__ import annotations

import os


def _gateway_get_session_env(name: str) -> str:
    """Host-owned session context reader (gateway binds it around handlers)."""
    try:
        from gateway.session_context import get_session_env

        return get_session_env(name)
    except Exception:
        return ""


def current_session_key() -> str:
    """The session id the /mixer state binds to (empty = process fallback)."""
    try:
        value = _gateway_get_session_env("HERMES_SESSION_ID")
    except Exception:
        value = ""
    if value:
        return value.strip()
    try:
        return (os.environ.get("HERMES_SESSION_ID") or "").strip()
    except Exception:
        return ""