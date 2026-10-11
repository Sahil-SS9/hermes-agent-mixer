"""Decision engine for Agent Mixer.

Order: plan -> scope -> deps -> lines -> ask. The first deny wins. ``decide`` takes a normalised
:class:`Call` and returns a :class:`Decision` (deny or ask), or None for "no opinion" (D10: Mixer
only restricts, it never says allow).
"""

from __future__ import annotations

import posixpath
from typing import Any

from hermes_agent_mixer.core import depsguard, diffcount, scope as scope_mod, shell
from hermes_agent_mixer.core.calls import Call, Decision

NO_BYPASS = "Don't retry this through terminal or execute_code."

_PLAN_WRITE = (
    "blocked by mixer:edits: plan mode is read-only; {tool} was prevented. " + NO_BYPASS +
    " Leave plan mode with /mixer edits auto (or ask)."
)
_PLAN_SHELL = (
    "blocked by mixer:edits: plan mode limits terminal to read-only commands; segment {index} is not "
    "read-only. " + NO_BYPASS + " Leave plan mode with /mixer edits auto (or ask)."
)
_ASK = (
    "mixer:edits needs your approval for {tool} on {path}. The call waits for you - approve, "
    "always-allow (remembered for this file only) or deny."
)
_DEPS_BLOCK = (
    "blocked by mixer:deps: this would add new dependencies ({names}). " + NO_BYPASS +
    " Raise it deliberately with /mixer deps ask or allow."
)
_DEPS_ASK = (
    "mixer:deps: this would add new dependencies ({names}). The call waits for your approval - "
    "deny it if you did not intend a new dependency."
)
_LINES = (
    "blocked by mixer:lines: this change is {need} lines (added+removed). You have used {used} of the "
    "{budget}-line budget this turn, {remaining} remain. " + NO_BYPASS +
    " Stop and summarise the turn, or raise the budget with /mixer lines N."
)
_SCOPE_UNREADABLE = (
    "blocked by mixer:scope: cannot identify the files this patch touches. " + NO_BYPASS +
    " Use a valid patch or separate path-based edits."
)
_SCOPE_SHELL = (
    "blocked by mixer:scope: this command writes '{target}' (best-effort read of the command), which is not "
    "in scope (allowed globs: {globs}). " + NO_BYPASS + " Add a glob with /mixer scope add <glob>, or "
    "write inside the allowed paths."
)

_MANIFESTS = ("package.json", "pyproject.toml", "cargo.toml", "go.mod")
_FILE_KINDS = ("write", "edit", "patch")
_SHELL_ECOSYSTEM = {"npm": "npm", "pnpm": "npm", "yarn": "npm", "bun": "npm", "cargo": "cargo", "go": "go"}


def _deny(stage: str, message: str) -> Decision:
    return Decision("deny", message, stage=stage)


def _is_manifest(path_text: str) -> bool:
    name = posixpath.basename(path_text.replace("\\", "/")).lower()
    return name in _MANIFESTS or (name.startswith("requirements") and name.endswith(".txt"))


def file_targets(call: Call, ports: Any, task_id: str | None) -> list[str] | None:
    if call.kind == "patch":
        return diffcount.patch_targets(call, ports, task_id)
    if not call.path:
        return []
    return [ports.resolve(call.path, task_id)]


def decide(call: Call, knobs: dict[str, Any], ports: Any, budget: Any, task_id: str | None = None) -> Decision | None:
    """Run the ordered stages for one call."""
    edits = str(knobs.get("edits") or "auto").lower()
    if call.kind in _FILE_KINDS:
        return _file_call(call, knobs, edits, ports, budget, task_id)
    if call.kind == "code":
        if edits == "plan":
            return _deny("edits", _PLAN_WRITE.format(tool=call.label))
        return None
    if call.kind == "shell":
        return _shell_call(call, knobs, edits, ports, task_id)
    return None


# -- file tools -----------------------------------------------------------------------------


def _file_call(call: Call, knobs: dict, edits: str, ports: Any, budget: Any, task_id: str | None) -> Decision | None:
    if edits == "plan":
        return _deny("edits", _PLAN_WRITE.format(tool=call.label))
    globs = [str(g) for g in (knobs.get("scope") or [])]
    deps_mode = str(knobs.get("deps") or "ask").lower()
    lines_budget = knobs.get("lines") or 0

    targets = file_targets(call, ports, task_id)
    if globs:
        if targets is None:
            return _deny("scope", _SCOPE_UNREADABLE)
        root = ports.workspace_root(task_id)
        for target in targets:
            if not scope_mod.allowed(target, globs, root, windows=ports.windows):
                return _deny("scope", scope_mod.not_in_scope_message(target, globs, NO_BYPASS))

    proposed: list[diffcount.Change] | None = None

    def changes() -> list[diffcount.Change]:
        nonlocal proposed
        if proposed is None:
            proposed = diffcount.changes(call, ports, task_id)
        return proposed

    deps_decision = _manifest_deps(changes, deps_mode, targets) if deps_mode in ("block", "ask") else None
    if deps_decision and deps_decision.action == "deny":
        return deps_decision
    if lines_budget and budget is not None:
        total = sum(change.lines() for change in changes())
        if total > 0:
            allowed, used = budget.reserve(total, lines_budget)
            if not allowed:
                return _deny("lines", _LINES.format(need=total, used=used, budget=lines_budget,
                                                    remaining=max(lines_budget - used, 0)))
    # Approval cannot bypass a later hard limit: the permitted diff is reserved before prompting.
    if deps_decision:
        return deps_decision
    if edits == "ask":
        shown = ", ".join(targets) if targets else (call.path or call.label)
        key = "mixer:edit:" + ";".join(sorted(targets or [call.path or call.label]))
        return Decision("ask", _ASK.format(tool=call.label, path=shown), key, "edits")
    return None


def _manifest_deps(changes: Any, deps_mode: str, targets: list[str] | None) -> Decision | None:
    if not any(_is_manifest(t) for t in (targets or [])):
        return None
    found: dict[str, set[str]] = {}
    for change in changes():
        if not _is_manifest(change.path):
            continue
        names: list[str] | None = None
        if change.simulated:
            names = depsguard.compare_names(change.path, change.before, change.after)
        if names is None:  # not simulated, or a side that does not parse: compare the call's own text
            before = depsguard.fragment_names(change.path, change.old_fragment)
            after = depsguard.fragment_names(change.path, change.new_fragment)
            names = sorted(after - before)
        if names:
            found.setdefault(depsguard.ecosystem(change.path), set()).update(names)
    return _deps_decision(found, deps_mode)


def _deps_decision(found: dict[str, set[str]], deps_mode: str) -> Decision | None:
    if not found:
        return None
    pairs = [(eco, name) for eco, names in sorted(found.items()) for name in sorted(names)]
    shown = ", ".join(name for _eco, name in pairs)
    if deps_mode == "block":
        return _deny("deps", _DEPS_BLOCK.format(names=shown))
    key = "mixer:dep:" + ",".join(f"{eco}:{name}" for eco, name in pairs)
    return Decision("ask", _DEPS_ASK.format(names=shown), key, "deps")


# -- shell --------------------------------------------------------------------------------------


def _shell_call(call: Call, knobs: dict, edits: str, ports: Any, task_id: str | None) -> Decision | None:
    command = call.command or ""
    deps_mode = str(knobs.get("deps") or "ask").lower()
    if edits == "plan":
        ok, bad = shell.classify_plan(command, call.shell)
        if not ok:
            return _deny("edits", _PLAN_SHELL.format(index=bad + 1))
    globs = [str(g) for g in (knobs.get("scope") or [])]
    if globs and edits != "plan" and call.shell == "posix":
        base = ports.resolve(call.cwd, task_id) if call.cwd else None
        root = ports.workspace_root(task_id)
        for target in shell.write_targets(command):
            where = ports.resolve(target.base, task_id, base=base) if target.base is not None else base
            resolved = ports.resolve(target.path, task_id, base=where)
            inside = scope_mod.allowed(resolved, globs, root, windows=ports.windows) or (
                target.directory and scope_mod.allowed(resolved.rstrip("/") + "/x", globs, root, windows=ports.windows))
            if not inside:
                return _deny("scope", _SCOPE_SHELL.format(target=resolved, globs=", ".join(globs)))
    if call.shell == "posix" and deps_mode in ("block", "ask"):
        for words in shell.split_segments(command):
            classified = depsguard.classify_install(shell.quote_words(words))
            if not classified or classified[0] != "new" or not classified[1]:
                continue
            eco = _SHELL_ECOSYSTEM.get(words[0].rsplit("/", 1)[-1], "pypi")
            return _deps_decision({eco: set(classified[1])}, deps_mode)
    return None
