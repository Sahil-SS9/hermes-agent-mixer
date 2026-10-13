"""The /mixer grammar and the board, shared by every host.

A *target* is what a command acts on: a session (changes live in the engine), a parked chat key
(changes wait for that chat's next turn), the saved settings (``agent-mixer --saved``) or nothing at
all (refuse and point to ``save``). The grammar is unchanged from 0.1 plus ``save <dial> <value>``.
"""

from __future__ import annotations

from typing import Any

from ..core import settings

USAGE = ("Usage: /mixer [show] | /mixer preset [show|<name>] | /mixer edits ask|auto|plan | "
         "/mixer scope add|remove|clear|show | /mixer lines N|off | "
         "/mixer deps allow|ask|block | /mixer save [<dial> <value>] | /mixer reset")


class Refusal(Exception):
    """The target cannot take this change; the message is the reply."""


class Target:
    """What a command acts on. Subclasses override what they support."""

    name = ""  # shown in notes: "this session only: <name>"
    allow_session_changes = True

    def effective(self) -> settings.Effective:
        raise NotImplementedError

    def set(self, knob: str, value: Any) -> str:
        """Apply one dial change; returns the note appended to the reply."""
        raise NotImplementedError

    def reset(self) -> str:
        raise NotImplementedError

    def save_current(self) -> str:
        raise NotImplementedError

    def save_one(self, knob: str, value: Any) -> str:
        raise NotImplementedError

    def saved_list(self, knob: str) -> list[str]:
        """The saved list value for ``scope`` or ``extra_write_tools`` (for ``save <dial> add|remove``)."""
        return []


def handle_command(raw_args: str, target: Target) -> str:
    """Handle one /mixer invocation and return the reply text."""
    tokens = (raw_args or "").strip().split()
    if tokens and tokens[0] == "board":
        tokens = tokens[1:] or ["show"]
    if not tokens or tokens[0] == "show":
        return render_board(target.effective(), target.name)
    sub, args = tokens[0], tokens[1:]
    try:
        if sub == "edits":
            return _set_choice(target, "edits", args, settings.EDIT_MODES)
        if sub == "deps":
            return _set_choice(target, "deps", args, settings.DEPS_MODES)
        if sub == "lines":
            return _set_lines(target, args)
        if sub == "scope":
            return _scope_command(target, args)
        if sub == "save":
            return _save(target, args)
        if sub == "preset":
            return _preset(target, args)
        if sub == "reset":
            return target.reset()
    except Refusal as refusal:
        return str(refusal)
    return f"Unknown subcommand '{sub}'. {USAGE}"


def _set_choice(target: Target, knob: str, args: list[str], allowed: tuple[str, ...]) -> str:
    if len(args) != 1:
        return f"{knob} needs one of: {', '.join(allowed)}. {USAGE}"
    value = args[0].lower()
    if value not in allowed:
        return f"Unknown {knob} mode '{args[0]}'. Choose one of: {', '.join(allowed)}."
    return f"mixer: {knob} = {value}" + target.set(knob, value)


def _parse_lines_arg(raw: str) -> tuple[int | None, str]:
    text = raw.lower()
    if text == "off":
        return 0, ""
    try:
        number = int(text)
    except ValueError:
        return None, f"Unknown lines value '{raw}'. Use a positive number of lines, or off (0)."
    if number < 0:
        return None, f"lines must be a positive number, or off (0) (got {number})."
    return number, ""


def _set_lines(target: Target, args: list[str]) -> str:
    if len(args) != 1:
        return f"lines needs a positive number of lines, or off. {USAGE}"
    number, error = _parse_lines_arg(args[0])
    if number is None:
        return error
    shown = "off" if number == 0 else f"{number} per turn"
    return f"mixer: lines = {shown}" + target.set("lines", number)


def _scope_command(target: Target, args: list[str]) -> str:
    if not args:
        return _scope_lines(target.effective()) + "\nUsage: /mixer scope add|remove|clear|show"
    verb = args[0]
    current = list(target.effective()["scope"])
    if verb == "add" and len(args) == 2:
        if args[1] not in current:
            current.append(args[1])
        return f"mixer: scope = {_fmt_scope(current)}" + target.set("scope", current)
    if verb == "remove" and len(args) == 2:
        current = [g for g in current if g != args[1]]
        return f"mixer: scope = {_fmt_scope(current)}" + target.set("scope", current)
    if verb == "clear" and len(args) == 1:
        return "mixer: scope cleared (no limit)" + target.set("scope", [])
    if verb == "show" and len(args) == 1:
        return _scope_lines(target.effective())
    return f"scope needs add|remove|clear|show. {USAGE}"


def _preset(target: Target, args: list[str]) -> str:
    """`preset show` lists the bundles; `preset <name>` applies one (QW12)."""
    from ..core import presets

    if not args or args[0] in ("show", "list"):
        return presets.render_list()
    if len(args) != 1:
        return f"preset takes one name. Presets: {', '.join(presets.names())}."
    return presets.apply(args[0], target)


def _save(target: Target, args: list[str]) -> str:
    if not args:
        return target.save_current()
    knob, rest = args[0], args[1:]
    if knob not in settings.SAVED_KEYS:
        return f"Unknown setting '{knob}'. Dials: {', '.join(settings.DIALS)} (and extra_write_tools)."
    if knob == "scope" or knob == "extra_write_tools":
        if rest and rest[0] in ("add", "remove", "clear"):
            return _save_list_edit(target, knob, rest)
        return target.save_one(knob, list(rest))
    if len(rest) != 1:
        return f"save {knob} needs exactly one value. {USAGE}"
    if knob == "lines":
        number, error = _parse_lines_arg(rest[0])
        if number is None:
            return error
        return target.save_one("lines", number)
    allowed = settings.EDIT_MODES if knob == "edits" else settings.DEPS_MODES
    value = rest[0].lower()
    if value not in allowed:
        return f"Unknown {knob} mode '{rest[0]}'. Choose one of: {', '.join(allowed)}."
    return target.save_one(knob, value)


def _save_list_edit(target: Target, knob: str, rest: list[str]) -> str:
    current = list(target.saved_list(knob))
    verb, globs = rest[0], rest[1:]
    if verb == "add":
        current += [g for g in globs if g not in current]
    elif verb == "remove":
        current = [g for g in current if g not in globs]
    else:
        current = []
    return target.save_one(knob, current)


def _fmt_scope(globs: list[str]) -> str:
    return ", ".join(globs) if globs else "(no limit)"


def _scope_lines(eff: settings.Effective) -> str:
    return f"  scope   {_fmt_scope(eff['scope'])}  ({eff.sources['scope']})"


def render_board(eff: settings.Effective, label: str = "") -> str:
    """One screenshot-style board; each value says where it comes from."""
    where = label or eff.session or "no session"
    lines = [
        f"Agent Mixer · {where}",
        _choice_line("edits ", settings.EDIT_MODES, eff["edits"], eff.sources["edits"]),
        _scope_lines(eff) if eff["scope"] else f"  scope   (no limit)  ({eff.sources['scope']})",
        f"  lines   {_lines_cell(eff)}  ({eff.sources['lines']})",
        _choice_line("deps  ", settings.DEPS_MODES, eff["deps"], eff.sources["deps"]),
    ]
    if eff["extra_write_tools"]:
        lines.append(f"  extra write tools  {', '.join(eff['extra_write_tools'])}  ({eff.sources['extra_write_tools']})")
    for warning in eff.warnings:
        lines.append(f"  ! {warning}; fix it with /mixer save <dial> <value> or the plugin settings")
    lines.append("  ask uses the host's approvals gate; always-allow remembers one file or one package. "
                 "Terminal and execute_code are watched best-effort, not sandboxed.")
    return "\n".join(lines)


def _choice_line(label: str, values: tuple[str, ...], active: str, source: str) -> str:
    parts = [f"[ACTIVE] {value}" if value == active else value for value in values]
    return f"  {label}{'  '.join(parts)}  ({source})"


def _lines_cell(eff: settings.Effective) -> str:
    budget = eff["lines"]
    if not budget:
        return "off"
    left = eff.left if eff.left is not None else budget
    return f"{budget} per turn, {left} left this turn"
