"""Simulate file-tool changes without writes, then count real added/removed lines.

Bulk patches use separate file before-states and an in-memory overlay for
Add/Update/Delete/Move. Unknown simulations return None; active policy stages
fail closed rather than treating an unknown diff as zero.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from hermes_agent_mixer import patches


def count_diff_lines(before: str | None, after: str | None) -> tuple[int, int]:
    before_lines = (before or "").splitlines()
    after_lines = (after or "").splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    added = removed = 0
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op in ("delete", "replace"):
            removed += a2 - a1
        if op in ("insert", "replace"):
            added += b2 - b1
    return added, removed


def _replace_result(before: str, old: str, new: str, replace_all: bool) -> str | None:
    if not isinstance(old, str) or not isinstance(new, str) or old not in before:
        return None
    return before.replace(old, new) if replace_all else before.replace(old, new, 1)


def _apply_v4a(before: str, hunks: list[list[tuple[str, str]]]) -> str | None:
    result = before
    for section in hunks:
        find_lines = [text for kind, text in section if kind in (" ", "-")]
        replace_lines = [text for kind, text in section if kind in (" ", "+")]
        find, replacement = "\n".join(find_lines), "\n".join(replace_lines)
        if find == replacement:
            continue
        if not find_lines:
            result = (result.rstrip("\n") + "\n" if result else "") + replacement + "\n"
        elif find not in result:
            return None
        else:
            result = result.replace(find, replacement, 1)
    return result


def simulate_patch_result(before: str, args: dict[str, Any]) -> str | None:
    if args.get("mode") == "patch":
        try:
            operations = patches.parse(str(args.get("patch") or ""))
        except ValueError:
            return None
        if len(operations) != 1 or operations[0].kind != "Update":
            return None
        return _apply_v4a(before, operations[0].hunks)
    return _replace_result(before, args.get("old_string") or "", args.get("new_string") or "",
                           bool(args.get("replace_all")))


def _read_before(path_value: Any, root: Path | None) -> str | None:
    if not isinstance(path_value, str) or not path_value:
        return None
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute() and root is not None:
        candidate = Path(root) / candidate
    try:
        return candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_before_text(tool_name: str, args: dict[str, Any], root: Path | None = None) -> str | None:
    return _read_before(args.get("path"), root)


def simulate(tool_name: str, args: dict[str, Any], root: Path | None = None) -> str | None:
    if tool_name == "write_file":
        content = args.get("content")
        return content if isinstance(content, str) else None
    if tool_name == "patch":
        return simulate_patch_result(_read_before(args.get("path"), root) or "", args)
    return None


def _bulk_changes(args: dict[str, Any], root: Path | None) -> list[tuple[str, str | None, str | None]] | None:
    try:
        operations = patches.parse(str(args.get("patch") or ""))
    except ValueError:
        return None
    if not operations:
        return None
    original: dict[str, str | None] = {}
    overlay: dict[str, str | None] = {}

    def key(path: str) -> str:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (root or Path.cwd()) / candidate
        return str(candidate.resolve())

    def read(path: str) -> str | None:
        if path not in original:
            original[path] = _read_before(path, root)
            overlay[path] = original[path]
        return overlay[path]

    for op in operations:
        path = key(op.path)
        before = read(path)
        if op.kind == "Update":
            if before is None:
                return None
            after = _apply_v4a(before, op.hunks)
            if after is None:
                return None
            overlay[path] = after
        elif op.kind == "Add":
            if before is not None:
                return None  # host refuses Add on an occupied path
            added = [text for hunk in op.hunks for kind, text in hunk if kind == "+"]
            overlay[path] = "\n".join(added) + ("\n" if added else "")
        elif op.kind == "Delete":
            if before is None:
                return None
            overlay[path] = None
        elif op.kind == "Move":
            if before is None or op.destination is None:
                return None
            destination = key(op.destination)
            if read(destination) is not None:
                return None
            overlay[destination] = before
            overlay[path] = None
    return [(path, before, overlay[path]) for path, before in original.items()]


def changes(tool_name: str, args: dict[str, Any], root: Path | None = None) -> list[tuple[str, str | None, str | None]] | None:
    """All proposed path/before/after triples; None means policy cannot simulate."""
    if tool_name == "patch" and args.get("mode") == "patch":
        return _bulk_changes(args, root)
    path = args.get("path")
    if not isinstance(path, str) or not path:
        return None
    after = simulate(tool_name, args, root)
    if after is None:
        return None
    return [(path, _read_before(path, root), after)]


def estimate(tool_name: str, args: dict[str, Any], root: Path | None = None) -> tuple[int, int]:
    if tool_name not in ("write_file", "patch"):
        return 0, 0
    proposed = changes(tool_name, args, root)
    if proposed is None:
        return 0, 0  # estimate only; the decision engine blocks unknown active budgets
    diffs = [count_diff_lines(before, after) for _path, before, after in proposed]
    return sum(added for added, _removed in diffs), sum(removed for _added, removed in diffs)
