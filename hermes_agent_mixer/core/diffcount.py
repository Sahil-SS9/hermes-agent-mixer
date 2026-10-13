"""Work out what a file-tool call would change, without writing anything.

``changes`` never fails: whatever cannot be simulated (an anchor the matcher cannot find, a file that
does not exist yet) becomes an *estimate* from line counts. Mixer never blocks only because it could
not simulate; the host reports a bad anchor itself (D4).
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

from ..core import patches
from ..core.calls import Call


@dataclass
class Change:
    path: str  # absolute, forward slashes
    before: str | None  # None: the file does not exist
    after: str | None  # None: deleted, or not simulated (see ``estimate``)
    estimate: int | None = None  # changed lines when the result could not be simulated
    old_fragment: str = ""  # what the call removes, for dependency checks without a simulation
    new_fragment: str = ""  # what the call adds

    @property
    def simulated(self) -> bool:
        return self.estimate is None

    def lines(self) -> int:
        if self.estimate is not None:
            return self.estimate
        return sum(count_diff_lines(self.before, self.after))


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


def _apply_v4a(before: str, hunks: list[list[tuple[str, str]]], ports: Any) -> str | None:
    result = before
    for section in hunks:
        find_lines = [text for kind, text in section if kind in (" ", "-")]
        replace_lines = [text for kind, text in section if kind in (" ", "+")]
        find, replacement = "\n".join(find_lines), "\n".join(replace_lines)
        if find == replacement:
            continue
        if not find_lines:
            result = (result.rstrip("\n") + "\n" if result else "") + replacement + "\n"
            continue
        updated = ports.fuzzy_replace(result, find, replacement, False)
        if updated is None:
            return None
        result = updated
    return result


def _hunk_estimate(hunks: list[list[tuple[str, str]]]) -> int:
    plus = sum(1 for hunk in hunks for kind, _ in hunk if kind == "+")
    minus = sum(1 for hunk in hunks for kind, _ in hunk if kind == "-")
    return plus + minus


def _fragments(hunks: list[list[tuple[str, str]]]) -> tuple[str, str]:
    old = "\n".join(text for hunk in hunks for kind, text in hunk if kind in ("-",))
    new = "\n".join(text for hunk in hunks for kind, text in hunk if kind in ("+",))
    return old, new


def patch_targets(call: Call, ports: Any, task_id: str | None) -> list[str] | None:
    """Absolute paths a patch touches (sources and destinations). None: the patch cannot be read."""
    try:
        operations = patches.parse(call.patch_text)
    except ValueError:
        return None
    if not operations:
        return None
    found: list[str] = []
    for op in operations:
        found.append(ports.resolve(op.path, task_id))
        if op.destination is not None:
            found.append(ports.resolve(op.destination, task_id))
    return found


def _bulk(call: Call, ports: Any, task_id: str | None) -> list[Change]:
    try:
        operations = patches.parse(call.patch_text)
    except ValueError:
        return []
    original: dict[str, str | None] = {}
    overlay: dict[str, str | None] = {}
    estimates: list[Change] = []

    def current(path: str) -> str | None:
        if path not in overlay:
            original[path] = ports.read_text(path)
            overlay[path] = original[path]
        return overlay[path]

    for op in operations:
        path = ports.resolve(op.path, task_id)
        if op.kind == "Update":
            before = current(path)
            after = _apply_v4a(before, op.hunks, ports) if before is not None else None
            if after is None:
                old, new = _fragments(op.hunks)
                estimates.append(Change(path, before, None, estimate=_hunk_estimate(op.hunks),
                                        old_fragment=old, new_fragment=new))
                continue
            if op.destination is not None:
                destination = ports.resolve(op.destination, task_id)
                current(destination)
                overlay[destination] = after
                overlay[path] = None
            else:
                overlay[path] = after
        elif op.kind == "Add":
            current(path)
            added = [text for hunk in op.hunks for kind, text in hunk if kind == "+"]
            overlay[path] = "\n".join(added) + ("\n" if added else "")
        elif op.kind == "Delete":
            current(path)
            overlay[path] = None
        elif op.kind == "Move" and op.destination is not None:
            source = current(path)
            destination = ports.resolve(op.destination, task_id)
            current(destination)
            overlay[destination] = source
            overlay[path] = None
    return [Change(path, before, overlay[path]) for path, before in original.items()] + estimates


def changes(call: Call, ports: Any, task_id: str | None = None) -> list[Change]:
    """Every proposed change for a ``write``, ``edit`` or ``patch`` call."""
    if call.kind == "patch":
        return _bulk(call, ports, task_id)
    if not call.path:
        return []
    path = ports.resolve(call.path, task_id)
    before = ports.read_text(path)
    if call.kind == "write":
        if isinstance(call.content, str):
            return [Change(path, before, call.content)]
        return [Change(path, before, None, estimate=0)]
    if call.kind == "edit":
        old, new = call.old or "", call.new or ""
        if before is not None and old:
            after = ports.fuzzy_replace(before, old, new, bool(call.replace_all))
            if after is not None:
                return [Change(path, before, after)]
        estimate = max(len(old.splitlines()), len(new.splitlines()))
        return [Change(path, before, None, estimate=estimate, old_fragment=old, new_fragment=new)]
    return []
