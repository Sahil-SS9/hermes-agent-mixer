"""Every Hermes host import lives in this file (rule 5).

Mixer uses the public plugin API for everything it can. Three host modules have no public equivalent,
so they are imported here, each guarded, with a fallback that follows the same order:

* ``gateway.session_context.get_session_env`` - the ContextVar-aware reader of ``HERMES_SESSION_*``.
  It returns the ContextVar when one is bound (even to ``""``) and ``os.environ`` only when nothing
  is bound. Fallback: ``os.environ``.
* ``tools.file_tools_paths._resolve_path_for_task`` and ``_authoritative_workspace_root`` - how the
  file tools turn a path into a real one, and the workspace root they anchor to. Fallback: an
  absolute, non-sentinel ``$TERMINAL_CWD``, then the process cwd.
* ``tools.fuzzy_match.fuzzy_find_and_replace`` - the matcher the patch tool applies, used to count
  what a drifted patch really changes. Fallback: exact match, then line-trimmed (core/fuzzy.py).

A missing or changed host module never breaks enforcement; it only makes Mixer fall back.
"""
from __future__ import annotations

import importlib
import logging
import os
from typing import Any

log = logging.getLogger("agent_mixer")

_CACHE: dict[str, Any] = {}
_MISSING = object()


def _import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001 - any host import problem means "use the fallback"
        return None


def reset_cache() -> None:
    _CACHE.clear()


def _function(module: str, attr: str):
    key = f"{module}:{attr}"
    if key not in _CACHE:
        loaded = _import(module)
        fn = getattr(loaded, attr, None) if loaded is not None else None
        _CACHE[key] = fn if callable(fn) else _MISSING
    return None if _CACHE[key] is _MISSING else _CACHE[key]


def available() -> dict[str, bool]:
    return {
        "gateway.session_context": _function("gateway.session_context", "get_session_env") is not None,
        "tools.file_tools_paths": _function("tools.file_tools_paths", "_resolve_path_for_task") is not None,
        "tools.fuzzy_match": _function("tools.fuzzy_match", "fuzzy_find_and_replace") is not None,
        "hermes_constants.get_hermes_home": _function("hermes_constants", "get_hermes_home") is not None,
    }


def session_env(name: str) -> str:
    """A ``HERMES_SESSION_*`` value: the bound ContextVar if there is one, else ``os.environ``."""
    getter = _function("gateway.session_context", "get_session_env")
    if getter is not None:
        try:
            return str(getter(name) or "")
        except Exception:  # noqa: BLE001
            log.debug("agent-mixer: get_session_env failed", exc_info=True)
    return os.environ.get(name, "")


def resolve_path(path: str, task_id: str | None) -> str | None:
    """The host's absolute path for a file-tool argument, or None when the host cannot say."""
    resolver = _function("tools.file_tools_paths", "_resolve_path_for_task")
    if resolver is None:
        return None
    try:
        return str(resolver(path, task_id or "default"))
    except Exception:  # noqa: BLE001
        log.debug("agent-mixer: host path resolver failed", exc_info=True)
        return None


def workspace_root(task_id: str | None) -> str | None:
    getter = _function("tools.file_tools_paths", "_authoritative_workspace_root")
    if getter is None:
        return None
    try:
        return getter(task_id or "default") or None
    except Exception:  # noqa: BLE001
        return None


def fuzzy_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    """The text the patch tool would produce, or None when it would fail (or is unavailable)."""
    matcher = _function("tools.fuzzy_match", "fuzzy_find_and_replace")
    if matcher is None:
        return None
    try:
        result, count, _strategy, error = matcher(content, old, new, replace_all)
    except Exception:  # noqa: BLE001
        return None
    return result if error is None and count else None


def has_fuzzy() -> bool:
    return _function("tools.fuzzy_match", "fuzzy_find_and_replace") is not None


def hermes_home() -> str | None:
    """The host's Hermes home (``hermes_constants.get_hermes_home()``), or None.

    Host resolves: context-local override → ``HERMES_HOME`` env → platform default. Used
    for the one shared data root (plugin-data/<plugin>) so panels and hooks store state
    in the same directory this process resolves.
    """
    getter = _function("hermes_constants", "get_hermes_home")
    if getter is None:
        value = os.environ.get("HERMES_HOME", "")
        return value if value and os.path.isabs(value) else None
    try:
        value = str(getter())
    except Exception:  # noqa: BLE001
        log.debug("agent-mixer: get_hermes_home failed", exc_info=True)
        return None
    return value if value and os.path.isabs(value) else None
