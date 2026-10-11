"""Dial definitions, validation and the effective-settings view.

Raw values arrive from saved settings (plugin config or settings.json, so possibly anything YAML or
JSON gave) and from commands (strings). A saved value that is not valid never weakens a dial:
``edits`` and ``deps`` fall back to ``ask``, and the board shows a warning (D6). ``lines`` is an
int with ``0`` meaning off; the 0.1 text forms ``"off"`` and ``"50"`` are still read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("agent_mixer")

DIALS = ("edits", "scope", "lines", "deps")
SAVED_ONLY = ("extra_write_tools",)
SAVED_KEYS = (*DIALS, *SAVED_ONLY)
EDIT_MODES = ("ask", "auto", "plan")
DEPS_MODES = ("allow", "ask", "block")

DEFAULTS: dict[str, Any] = {
    "edits": "auto",
    "scope": [],
    "lines": 0,
    "deps": "ask",
    "extra_write_tools": [],
}
# What an invalid saved value falls back to. Never the most permissive choice.
SAFE_FALLBACK: dict[str, Any] = {"edits": "ask", "deps": "ask", "scope": [], "lines": 0, "extra_write_tools": []}

_warned: set[tuple[str, str]] = set()


def is_valid_knob(knob: str) -> bool:
    return knob in DIALS


def default_of(knob: str):
    value = DEFAULTS[knob]
    return list(value) if isinstance(value, list) else value


def parse_lines(value: Any) -> int | None:
    """Return a non-negative int budget (0 = off), or None when the value is not a budget."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("off", "none", ""):
            return 0
        try:
            number = int(text)
        except ValueError:
            return None
        return number if number >= 0 else None
    return None


def _scope_list(value: Any) -> list[str] | None:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return None
    return [str(item).strip() for item in value if str(item).strip()]


def coerce(knob: str, raw: Any) -> tuple[Any, bool]:
    """Validate one raw value. Returns ``(value, ok)``; when not ok the value is the safe fallback."""
    if knob == "edits":
        if isinstance(raw, str) and raw.strip().lower() in EDIT_MODES:
            return raw.strip().lower(), True
    elif knob == "deps":
        if isinstance(raw, str) and raw.strip().lower() in DEPS_MODES:
            return raw.strip().lower(), True
    elif knob == "lines":
        number = parse_lines(raw)
        if number is not None:
            return number, True
    elif knob in ("scope", "extra_write_tools"):
        items = _scope_list(raw)
        if items is not None:
            return items, True
    fallback = SAFE_FALLBACK[knob]
    return (list(fallback) if isinstance(fallback, list) else fallback), False


@dataclass
class Effective:
    """The dials in force for one session, where each came from, and what is wrong with them."""

    values: dict[str, Any]
    sources: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    session: str = ""
    left: int | None = None  # lines left this turn, when a budget is on

    def __getitem__(self, knob: str):
        return self.values[knob]

    def get(self, knob: str, default=None):
        return self.values.get(knob, default)

    def is_default(self) -> bool:
        return all(self.values[k] == DEFAULTS[k] for k in DIALS)


def resolve(saved: dict[str, Any], override: dict[str, Any] | None = None, *, session: str = "") -> Effective:
    """Session override over saved value over default, with a source label per dial."""
    override = override or {}
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    warnings: list[str] = []
    for knob in SAVED_KEYS:
        if knob in override and knob in DIALS:
            value, _ok = coerce(knob, override[knob])
            values[knob], sources[knob] = value, "session"
            continue
        raw = saved.get(knob)
        if raw is None:
            values[knob], sources[knob] = default_of(knob), "default"
            continue
        value, ok = coerce(knob, raw)
        values[knob] = value
        if not ok:
            sources[knob] = "saved"
            message = f"saved {knob} {raw!r} is not valid; using {SAFE_FALLBACK[knob]!r}"
            warnings.append(message)
            if (knob, repr(raw)) not in _warned:
                _warned.add((knob, repr(raw)))
                log.warning("agent-mixer: %s", message)
        else:
            sources[knob] = "default" if value == DEFAULTS[knob] else "saved"
    return Effective(values, sources, warnings, session)
