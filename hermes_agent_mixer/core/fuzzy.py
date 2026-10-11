"""Host-free approximation of the Hermes patch tool's match chain: exact, then line-trimmed.

Used only to count what a patch would change when the host's own matcher cannot be imported.
Returns None when the replacement cannot be worked out; callers then estimate from line counts.
"""
from __future__ import annotations


def replace(content: str, old: str, new: str, replace_all: bool = False) -> str | None:
    if not old or old == new:
        return None
    if old in content:
        count = content.count(old)
        if count > 1 and not replace_all:
            return None
        return content.replace(old, new) if replace_all else content.replace(old, new, 1)
    lines = content.split("\n")
    pattern = [line.strip() for line in old.split("\n")]
    size = len(pattern)
    hits = [i for i in range(len(lines) - size + 1)
            if all(lines[i + j].strip() == pattern[j] for j in range(size))]
    if not hits or (len(hits) > 1 and not replace_all):
        return None
    replacement = new.split("\n")
    for start in reversed(hits if replace_all else hits[:1]):
        lines[start:start + size] = replacement
    return "\n".join(lines)
