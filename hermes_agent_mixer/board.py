"""Board rendering for Agent Mixer.

The board shows the four knobs (active value marked), the current session's
lines usage and Hermes' own approvals mode for context. Plain text only.
"""

from __future__ import annotations

from typing import Any

_USAGE = (
    "Usage: /mixer [show] | /mixer edits ask|auto|plan | "
    "/mixer scope add|remove|clear|show | /mixer lines N|off | "
    "/mixer deps allow|ask|block | /mixer save | /mixer reset"
)


def handle_command(raw_args: str, mixer: Any, session_key: str, *,
                   save: Any = None, approvals_mode: str | None = None) -> str:
    """Handle one /mixer invocation; returns the reply text."""
    tokens = (raw_args or "").strip().split()
    if not tokens or tokens[0] == "show":
        return render_board(mixer, session_key, approvals_mode=approvals_mode)
    sub, args = tokens[0], tokens[1:]

    if sub == "edits":
        return _set_knob(mixer, session_key, "edits", args, ("ask", "auto", "plan"))
    if sub == "deps":
        return _set_knob(mixer, session_key, "deps", args, ("allow", "ask", "block"))
    if sub == "lines":
        return _set_lines(mixer, session_key, args)
    if sub == "scope":
        return _scope_command(mixer, session_key, args)
    if sub == "save":
        return _save(mixer, session_key, save)
    if sub == "reset":
        return _reset(mixer, session_key)
    return f"Unknown subcommand {_qc(sub)}. {_USAGE}"


def _qc(value: str) -> str:
    return f"'{value}'"


def _set_knob(mixer: Any, session_key: str, knob: str, args: list[str],
              allowed: tuple[str, ...]) -> str:
    if len(args) != 1:
        return f"{knob} needs one of: {', '.join(allowed)}. {_USAGE}"
    value = args[0].lower()
    if value not in allowed:
        return f"Unknown {knob} mode {_qc(args[0])}. Choose one of: {', '.join(allowed)}."
    mixer.set_session(session_key, knob, value)
    return f"mixer: {knob} = {value}" + _session_note(session_key)


def _set_lines(mixer: Any, session_key: str, args: list[str]) -> str:
    if len(args) != 1:
        return f"lines needs a positive number of lines or 'off'. {_USAGE}"
    raw = args[0].lower()
    if raw == "off":
        mixer.set_session(session_key, "lines", "off")
        return f"mixer: lines = off" + _session_note(session_key)
    try:
        number = int(raw)
    except ValueError:
        return f"Unknown lines value {_qc(args[0])}. Use a positive number of lines or 'off'."
    if number <= 0:
        return f"lines must be a positive number or 'off' (got {number})."
    mixer.set_session(session_key, "lines", number)
    return f"mixer: lines = {number} per turn" + _session_note(session_key)


def _scope_command(mixer: Any, session_key: str, args: list[str]) -> str:
    if not args:
        return render_scope_lines(mixer, session_key) + f"\n{('Usage: /mixer scope add|remove|clear|show')}"
    verb = args[0]
    current = list(mixer.settings_for(session_key)["scope"])
    if verb == "add" and len(args) == 2:
        glob = args[1]
        if glob not in current:
            current.append(glob)
        mixer.set_session(session_key, "scope", current)
        return f"mixer: scope = {_fmt_scope(current)}" + _session_note(session_key)
    if verb == "remove" and len(args) == 2:
        current = [g for g in current if g != args[1]]
        mixer.set_session(session_key, "scope", current)
        return f"mixer: scope = {_fmt_scope(current)}" + _session_note(session_key)
    if verb == "clear" and len(args) == 1:
        mixer.set_session(session_key, "scope", [])
        return "mixer: scope cleared (project root only)" + _session_note(session_key)
    if verb == "show" and len(args) == 1:
        return render_scope_lines(mixer, session_key)
    return f"scope needs add|remove|clear|show. {_USAGE}"


def _fmt_scope(globs: list[str]) -> str:
    return ", ".join(globs) if globs else "(project root)"


def _save(mixer: Any, session_key: str, save: Any) -> str:
    if not callable(save):
        return "mixer: save is not available here (config writer missing)."
    effective = mixer.settings_for(session_key)
    for knob in ("edits", "scope", "lines", "deps"):
        save(knob, effective[knob])
    return "mixer: saved these as the plugin defaults (all new sessions start here)."


def _reset(mixer: Any, session_key: str) -> str:
    mixer.reset_session(session_key)
    return "mixer: reset to the saved defaults for this session."


def _session_note(session_key: str) -> str:
    return "" if not session_key else f" (this session only: {session_key[:8]})"


def render_scope_lines(mixer: Any, session_key: str) -> str:
    globs = mixer.settings_for(session_key)["scope"]
    note = "" if globs else "  (everything inside the project root is allowed)"
    return f"  scope   {_fmt_scope(globs)}{note}"


def render_board(mixer: Any, session_key: str, *, approvals_mode: str | None = None) -> str:
    """One screenshot-style board."""
    settings = mixer.settings_for(session_key)
    lines = [
        f"Agent Mixer · session {(session_key or 'global')[:12] or 'global'}",
        _knob_line("edits ", ("ask", "auto", "plan"), settings["edits"]),
        render_scope_lines(mixer, session_key),
        f"  lines   {_lines_cell(mixer, session_key, settings['lines'])}",
        _knob_line("deps  ", ("allow", "ask", "block"), settings["deps"]),
        "  Hermes approvals: {}.  (/yolo or approvals.mode to change; not a Mixer knob)".format(
            approvals_mode if approvals_mode else "unknown"),
    ]
    return "\n".join(lines)


def _knob_line(label: str, values: tuple[str, ...], active: str) -> str:
    parts = []
    for value in values:
        rendered = f"[ACTIVE] {value}" if value == active else value
        parts.append(rendered)
    return f"  {label}{'  '.join(parts)}"


def _lines_cell(mixer: Any, session_key: str, budget: Any) -> str:
    if not isinstance(budget, int):
        return "off"
    used = mixer.lines_state.session_used(session_key)
    return f"{used} / {budget} this turn"