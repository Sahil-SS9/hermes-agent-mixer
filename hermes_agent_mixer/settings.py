"""Knob settings: validation and normalisation.

Raw values arrive from plugin config (possibly anything YAML gave) and from
/mixer commands (strings). Everything is normalised here; invalid values fall
back to defaults instead of breaking enforcement.

The manifest declares lines as int with an optional default: "off" (disabled)
is represented as the string sentinel; any positive number is the budget.
"""

from __future__ import annotations

_KNOB_KEYS = ("edits", "scope", "lines", "deps")
_EDIT_MODES = ("ask", "auto", "plan")
_DEPS_MODES = ("allow", "ask", "block")

DEFAULT_EDITS = "auto"
DEFAULT_SCOPE: list[str] = []
LINES_OFF = "off"
DEFAULT_DEPS = "ask"


def normalise(raw: dict) -> dict:
    """Return validated knobs ``{edits, scope, lines, deps}``.

    ``lines`` is always the string "off" or a positive int, so saved defaults
    and session overrides agree regardless of the source text.
    """
    edits = _edit_mode(raw.get("edits"))
    scope = _scope(raw.get("scope"))
    lines = _lines(raw.get("lines"))
    deps = _deps_mode(raw.get("deps"))
    return {"edits": edits, "scope": scope, "lines": lines, "deps": deps}


def defaults() -> dict:
    return normalise({})


def _edit_mode(value) -> str:
    if isinstance(value, str) and value.lower() in _EDIT_MODES:
        return value.lower()
    return DEFAULT_EDITS


def _deps_mode(value) -> str:
    if isinstance(value, str) and value.lower() in _DEPS_MODES:
        return value.lower()
    return DEFAULT_DEPS


def _scope(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return list(DEFAULT_SCOPE)
    return [str(item).strip() for item in value if str(item).strip()]


def _lines(value):
    if value is None:
        return LINES_OFF
    if isinstance(value, bool):
        return LINES_OFF
    if isinstance(value, int):
        return value if value > 0 else LINES_OFF
    if isinstance(value, float) and value.is_integer():
        return int(value) if value > 0 else LINES_OFF
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", "off", "on"):
            return LINES_OFF
        try:
            number = int(text)
        except ValueError:
            return LINES_OFF
        return number if number > 0 else LINES_OFF
    return LINES_OFF


def is_valid_knob(knob: str) -> bool:
    return knob in _KNOB_KEYS