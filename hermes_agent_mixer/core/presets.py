"""Presets: named bundles of the four dials (QW12).

A preset is shorthand, not a new mechanism: ``/mixer preset surgical`` applies the same four dial
changes as typing them out, through the same Target.set() path, so session and saved targets work
unchanged. ``preset show`` lists the bundles; ``preset <name>`` applies one. Unknown names never
change anything.
"""

from __future__ import annotations

from typing import Any

from hermes_agent_mixer.core import board, settings

#: name -> dial overrides, applied in DIALS order. Every value must pass settings.coerce.
PRESETS: dict[str, dict[str, Any]] = {
    "builder": {"edits": "auto", "scope": [], "lines": 0, "deps": "allow"},
    "auditor": {"edits": "plan", "scope": [], "lines": 0, "deps": "ask"},
    "explorer": {"edits": "plan", "scope": [], "lines": 0, "deps": "allow"},
    "surgical": {"edits": "auto", "scope": ["src/**", "tests/**"], "lines": 30, "deps": "ask"},
}


def names() -> list[str]:
    return sorted(PRESETS)


def is_preset(name: str) -> bool:
    return name.strip().lower() in PRESETS


def apply(name: str, target: board.Target) -> str:
    """Apply one preset to the target, dial by dial, and return the reply text.

    Every preset dial is written explicitly so the bundle pins all four dials — a preset is a
    statement of "run like this", not "nudge what differs". The reply still lists every value.
    """
    key = (name or "").strip().lower()
    preset = PRESETS.get(key)
    if preset is None:
        return (f"Unknown preset '{name}'. Presets: {', '.join(names())}. "
                f"See one with /mixer preset show.")
    parts: list[str] = []
    notes: list[str] = []
    for dial in settings.DIALS:
        notes.append(target.set(dial, preset[dial]))
        parts.append(_fmt(dial, preset[dial]))
    unique_notes = list(dict.fromkeys(n for n in notes if n))
    suffix = (" " + " ".join(dict.fromkeys(unique_notes))) if unique_notes else ""
    return f"mixer: preset {key} applied ({'; '.join(parts)})" + suffix


def _fmt(dial: str, value: Any) -> str:
    if dial == "scope":
        shown = ", ".join(value) if value else "(no limit)"
        return f"scope={shown}"
    if dial == "lines":
        return f"lines={'off' if not value else value}"
    return f"{dial}={value}"


def render_list() -> str:
    """One line per preset: the dials it sets."""
    lines = ["Presets (apply with /mixer preset <name>):"]
    for name in names():
        p = PRESETS[name]
        lines.append(f"  {name:<9} edits={p['edits']}, scope={', '.join(p['scope']) or '(no limit)'}, "
                     f"lines={'off' if not p['lines'] else p['lines']}, deps={p['deps']}")
    return "\n".join(lines)
