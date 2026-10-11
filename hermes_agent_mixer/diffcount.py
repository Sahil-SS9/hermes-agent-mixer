"""Diff-based lines counting for the lines knob.

Counts from a simulated before/after diff (added + removed lines) per call;
the budget accumulates the sum per turn upstream. The V4A patch dialect is
parsed into hunks and applied to the in-memory file content so the count
matches a real diff; unparseable patches fall back to counting +/- lines.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any


def count_diff_lines(before: str | None, after: str | None) -> tuple[int, int]:
    """(added, removed) between two file states via one unified diff."""
    before_lines = (before or "").splitlines(keepends=False)
    after_lines = (after or "").splitlines(keepends=False)
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    added = removed = 0
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op in ("delete", "replace"):
            removed += a2 - a1
        if op in ("insert", "replace"):
            added += b2 - b1
    return added, removed


# -- simulations -------------------------------------------------------------


def _replace_result(before: str, old: str, new: str, replace_all: bool) -> str | None:
    if not isinstance(old, str) or not isinstance(new, str):
        return None
    if old not in before:
        # The real patch will fail; count nothing.
        return None
    if replace_all:
        return before.replace(old, new)
    return before.replace(old, new, 1)


def _parse_v4a_updates(patch_text: str) -> list[tuple[str, list[list[tuple[str, str]]]]]:
    """Extract (path, hunk_sections) from a V4A patch body.

    Each ``@@``-separated section contributes one (find, replace) pair:
    context+removed lines form the find text, context+added the replacement.
    """
    updates: list[tuple[str, list[list[tuple[str, str]]]]] = []
    current_path: str | None = None
    sections: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    saw_body = False
    for raw in (patch_text or "").splitlines():
        if raw.startswith("*** Update File:"):
            if current_path and current:
                sections.append(current)
            if current_path and sections:
                updates.append((current_path, sections))
            current_path = raw.split(":", 1)[1].strip()
            sections = []
            current = []
            saw_body = True
        elif raw.startswith("@@"):
            if current:
                sections.append(current)
            current = []
        elif raw.startswith("*** Begin Patch") or raw.startswith("*** End Patch"):
            continue
        elif raw.startswith("*** "):
            continue
        elif raw:
            kind = raw[0]
            if kind in (" ", "-", "+"):
                current.append(("context" if kind == " " else
                                ("removed" if kind == "-" else "added"), raw[1:]))
            saw_body = True
    if current:
        sections.append(current)
    if current_path and sections:
        updates.append((current_path, sections))
    return updates if saw_body else []


def _apply_v4a(before: str, hunks: list[list[tuple[str, str]]]) -> str | None:
    """Apply parsed hunk sections to the file content; None when an anchor is missing."""
    result = before
    for hunks_section in hunks:
        find_lines: list[str] = []
        replace_lines: list[str] = []
        for kind, text in hunks_section:
            if kind in ("context", "removed"):
                find_lines.append(text)
            if kind in ("context", "added"):
                replace_lines.append(text)
        find = "\n".join(find_lines) + "\n" if find_lines else ""
        replace = "\n".join(replace_lines) + "\n" if replace_lines else ""
        if not find and not replace:
            continue
        if not find:
            result = result.rstrip("\n") + "\n" + replace
        elif find not in result:
            return None  # anchor missing: conservative fallback upstream
        else:
            result = result.replace(find, replace, 1)
    return result


def simulate_patch_result(before: str, args: dict[str, Any]) -> str | None:
    """Proposed file content for a patch call; None when not simulatable."""
    mode = (args.get("mode") or "replace")
    if mode == "patch":
        text = args.get("patch")
        if not isinstance(text, str):
            return None
        updates = _parse_v4a_updates(text)
        result = before
        for _path, hunks in updates:
            applied = _apply_v4a(result, hunks)
            if applied is None:
                return None
            result = applied
        return result
    return _replace_result(before, args.get("old_string") or "", args.get("new_string") or "",
                           bool(args.get("replace_all")))


def read_before_text(tool_name: str, args: dict[str, Any], root: Path | None = None) -> str | None:
    """Current on-disk content for the call's path (None when it has none)."""
    path_value = args.get("path") if isinstance(args, dict) else None
    return _read_before(path_value, root)


def simulate(tool_name: str, args: dict[str, Any], root: Path | None = None) -> str | None:
    """Proposed after-text for a write_file/patch call; None when unknown/unreadable."""
    if not isinstance(args, dict):
        args = {}
    if tool_name == "write_file":
        content = args.get("content")
        return content if isinstance(content, str) else None
    if tool_name == "patch":
        before = _read_before(args.get("path"), root)
        before_text = before if before is not None else ""
        return simulate_patch_result(before_text, args)
    return None


def _estimate_patch(before_text: str, args: dict[str, Any], root: Path | None) -> tuple[int, int]:
    after = simulate_patch_result(before_text, args if isinstance(args, dict) else {})
    if after is None:
        # Not simulatable: conservative +/- count for V4A patches, zero otherwise.
        if (args.get("mode") or "replace") == "patch" and isinstance(args.get("patch"), str):
            added = sum(1 for line in args["patch"].splitlines() if line.startswith("+"))
            removed = sum(1 for line in args["patch"].splitlines() if line.startswith("-"))
            return (added, removed)
        return (0, 0)
    return count_diff_lines(before_text, after)


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


def estimate(tool_name: str, args: dict[str, Any], root: Path | None = None) -> tuple[int, int]:
    """Simulated (added, removed) for a write_file/patch call, (0, 0) if unknown."""
    if tool_name not in ("write_file", "patch"):
        return (0, 0)
    path_value = args.get("path") if isinstance(args, dict) else None
    before = _read_before(path_value, root) if tool_name == "patch" else _read_before(path_value, root)
    if tool_name == "write_file":
        new_content = args.get("content") if isinstance(args, dict) else None
        if not isinstance(new_content, str):
            return (0, 0)
        return count_diff_lines(before, new_content)
    # patch: simulate the result from the real before-state
    before_text = before if before is not None else ""
    return _estimate_patch(before_text, args, root)