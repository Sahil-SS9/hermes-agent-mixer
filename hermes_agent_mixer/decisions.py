"""Decision engine for Agent Mixer.

Order: plan -> scope -> deps -> lines -> ask. The first block wins. Returns a
directive dict ({"action": "block"|"approve", ...}) or None to allow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_agent_mixer import depsguard, diffcount, patches, scope as scope_mod
from hermes_agent_mixer import terminal as terminal_mod

_FILE_TOOLS = ("write_file", "patch")

_PLAN_MESSAGE_WRITE = (
    "blocked by mixer:edits: plan mode is read-only. {tool} was prevented. "
    "Leave it with /mixer edits auto (or ask)."
)

_PLAN_MESSAGE_TERMINAL = (
    "blocked by mixer:edits: plan mode limits terminal to read-only commands. "
    "Segment {index} is not read-only. Leave it with /mixer edits auto (or ask)."
)

_ASK_MESSAGE = (
    "mixer:edits needs your approval for {tool}. The call waits for you - "
    "approve, always-allow (remembered per rule), or deny."
)

_DEPS_BLOCK_MESSAGE = (
    "blocked by mixer:deps: this would add new dependencies ({names}). "
    "Raise it deliberately with /mixer deps ask or allow."
)

_DEPS_ASK_MESSAGE = (
    "mixer:deps: this would add new dependencies ({names}). "
    "The call waits for your approval - deny it if you did not intend a new dependency."
)

_LINES_MESSAGE = (
    "blocked by mixer:lines: this change is {need} lines (added+removed). "
    "You have used {used} of the {budget}-line budget this turn, {remaining} remain. "
    "Stop and summarise the turn, or raise the budget with /mixer lines N."
)


def evaluate(tool_name: str, args: dict[str, Any], knobs: dict[str, Any],
             state: Any = None, *, root: Path | None = None,
             session_id: str = "", task_id: str = "") -> dict[str, str] | None:
    """Run the ordered stages and return the winning directive (or None).

    ``state`` carries the mixer's turn counters (optional; budget stage is
    skipped without one). ``root`` overrides the project root; the hook passes
    ``session_id``/``task_id`` for counter keying.
    """
    edits = (knobs.get("edits") or "auto").lower()
    scope_globs = [str(g) for g in (knobs.get("scope") or [])]
    deps_mode = (knobs.get("deps") or "ask").lower()
    lines_budget = knobs.get("lines")
    root_value = root if root is not None else knobs.get("root")
    root_dir = Path(str(root_value)) if root_value else Path.cwd()
    session_key = (session_id or task_id or "")

    if tool_name in _FILE_TOOLS:
        if edits == "plan":
            return {"action": "block", "message": _PLAN_MESSAGE_WRITE.format(tool=tool_name)}
        if tool_name == "patch" and args.get("mode") == "patch":
            try:
                targets = patches.paths(str(args.get("patch") or ""))
            except ValueError:
                targets = []
            if not targets:
                return {"action": "block", "message":
                        "blocked by mixer:scope: cannot identify bulk-patch targets. "
                        "Use a valid patch or separate path-based edits."}
        else:
            targets = [str(args.get("path") or "")]
        for path_text in targets:
            message = scope_mod.check_scope(path_text, scope_globs, root_dir)
            if message:
                return {"action": "block", "message": message}
        deps_directive = _manifest_deps_directive(tool_name, args, root_dir, deps_mode)
        if deps_directive:
            return deps_directive
        lines_directive = _lines_directive(
            tool_name, args, root_dir, lines_budget, state, session_key, task_id)
        if lines_directive:
            return lines_directive
        if edits == "ask":
            return {
                "action": "approve",
                "message": _ASK_MESSAGE.format(tool=tool_name),
                "rule_key": "mixer:edits",
            }
        return None

    if tool_name == "execute_code":
        if edits == "plan":
            return {"action": "block", "message": _PLAN_MESSAGE_WRITE.format(tool=tool_name)}
        return None

    if tool_name == "terminal":
        command = str(args.get("command") or "")
        if edits == "plan":
            all_read_only, bad_index = terminal_mod.classify_command(command)
            if not all_read_only:
                return {
                    "action": "block",
                    "message": _PLAN_MESSAGE_TERMINAL.format(index=bad_index + 1),
                }
        return _terminal_deps_directive(command, deps_mode)

    return None


# -- deps stage ---------------------------------------------------------------


def _manifest_deps_directive(tool_name: str, args: dict[str, Any], root_dir: Path,
                             deps_mode: str) -> dict[str, str] | None:
    if deps_mode not in ("block", "ask"):
        return None
    path_text = str(args.get("path") or "")
    if not _is_manifest_path(path_text):
        return None
    before = diffcount.read_before_text(tool_name, args, root_dir)
    after = diffcount.simulate(tool_name, args, root_dir)
    if after is None:
        return None  # not simulatable: cannot judge new entries
    names = depsguard.detect_new_deps(path_text, before, after)
    if not names:
        return None
    shown = ", ".join(names)
    if deps_mode == "block":
        return {"action": "block", "message": _DEPS_BLOCK_MESSAGE.format(names=shown)}
    return {
        "action": "approve",
        "message": _DEPS_ASK_MESSAGE.format(names=shown),
        "rule_key": "mixer:deps",
    }


def _terminal_deps_directive(command: str, deps_mode: str) -> dict[str, str] | None:
    if deps_mode not in ("block", "ask"):
        return None
    import shlex

    for tokens in terminal_mod.split_segments(command):
        try:
            segment = shlex.join(tokens)
        except ValueError:
            segment = " ".join(tokens)
        classified = depsguard.classify_install(segment)
        if not classified:
            continue
        kind, names = classified
        if kind != "new" or not names:
            continue
        shown = ", ".join(names)
        if deps_mode == "block":
            return {"action": "block", "message": _DEPS_BLOCK_MESSAGE.format(names=shown)}
        return {
            "action": "approve",
            "message": _DEPS_ASK_MESSAGE.format(names=shown),
            "rule_key": "mixer:deps",
        }
    return None


def _is_manifest_path(path_text: str) -> bool:
    from pathlib import PurePosixPath

    name = PurePosixPath(path_text.replace("\\", "/")).name.lower()
    if name in ("package.json", "pyproject.toml", "cargo.toml", "go.mod"):
        return True
    return name.startswith("requirements") and name.endswith(".txt")


# -- lines stage ---------------------------------------------------------------


def _lines_directive(tool_name: str, args: dict[str, Any], root_dir: Path,
                     lines_budget: Any, state: Any, session_key: str,
                     task_id: str) -> dict[str, str] | None:
    if state is None or not isinstance(lines_budget, int):
        return None
    counters = state.lines_state if hasattr(state, "lines_state") else state
    added, removed = diffcount.estimate(tool_name, args, root_dir)
    total = added + removed
    if total <= 0:
        return None
    used = counters.used(session_key, task_id)
    remaining = lines_budget - used
    if used + total > lines_budget:
        return {
            "action": "block",
            "message": _LINES_MESSAGE.format(need=total, used=used, budget=lines_budget,
                                             remaining=max(remaining, 0)),
        }
    counters.add(session_key, task_id, total)
    return None