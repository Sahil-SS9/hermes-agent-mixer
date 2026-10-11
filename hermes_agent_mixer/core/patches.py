"""Standard-library policy view of the host's V4A patch operations.

Recognises the documented Add/Update/Delete/Move headers, including the host's
whitespace tolerance. It never writes files or imports the host patch engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

_HEADER = re.compile(r"^\*\*\*\s*(Update|Add|Delete|Move)\s+File:\s*(.+)")
_BEGIN = re.compile(r"^\*\*\*\s*Begin\s+Patch\s*$")
_END = re.compile(r"^\*\*\*\s*End\s+Patch\s*$")
_MOVE = re.compile(r"(.+?)\s*->\s*(.+)")
_MOVE_TO = re.compile(r"^\*\*\*\s*Move\s+to:\s*(.+)")
_EOF = re.compile(r"^\*\*\*\s*End\s+of\s+File\s*$")


@dataclass
class Operation:
    kind: str
    path: str
    destination: str | None = None
    hunks: list[list[tuple[str, str]]] = field(default_factory=list)


def parse(text: str) -> list[Operation]:
    lines = text.splitlines()
    start, end = 0, len(lines)
    for i, line in enumerate(lines):
        if _BEGIN.match(line):
            start = i + 1
        elif _END.match(line):
            end = i
            break
    result: list[Operation] = []
    current: Operation | None = None
    for line in lines[start:end]:
        move_to = _MOVE_TO.match(line)
        if move_to:  # Codex apply_patch: "*** Move to:" follows an Update File header
            if current is None or current.kind != "Update":
                raise ValueError("Move to without an Update File header")
            current.destination = move_to.group(1).strip()
            continue
        if _EOF.match(line):
            continue
        match = _HEADER.match(line)
        if match:
            kind, path = match.groups()
            path = path.strip()
            destination = None
            if kind == "Move":
                move = _MOVE.fullmatch(path)
                if not move:
                    raise ValueError("Move File needs a source and destination")
                path, destination = (value.strip() for value in move.groups())
            current = Operation(kind, path, destination)
            result.append(current)
        elif line.startswith("@@"):
            if current:
                current.hunks.append([])
        elif current and line and not line.startswith("\\"):
            if line.startswith("***"):
                raise ValueError("unknown patch header")
            if not current.hunks:
                current.hunks.append([])
            kind, content = (line[0], line[1:]) if line[0] in " +-" else (" ", line)
            current.hunks[-1].append((kind, content))
    return result


def paths(text: str) -> list[str]:
    result: list[str] = []
    for op in parse(text):
        result.append(op.path)
        if op.destination is not None:
            result.append(op.destination)
    return result
