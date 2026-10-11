"""Scope checking for file writes.

Project-root containment first, then the scope glob allow-list inside the
root. Symlinks are resolved before checking; Windows-style paths are rejected
cleanly; only an absolute glob can allow a write outside the project root.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:")


def _glob_to_regex(pattern: str) -> str:
    """Translate a shell-style glob into a path regex.

    ``**`` matches any number of path components, ``*`` stops at a separator
    and ``?`` matches exactly one non-separator character.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # Consume any run of stars as the cross-component match.
                while i < len(pattern) and pattern[i] == "*":
                    i += 1
                # A "**" flanked by separators should also match zero segments:
                # treat a following "/" as optional.
                if i < len(pattern) and pattern[i] == "/":
                    i += 1
                    out.append(".*/")
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
            i += 1
            continue
        if ch == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(ch))
        i += 1
    return "".join(out)


def _normalise_glob(pattern: str) -> str:
    return os.path.expanduser(pattern.replace("\\", "/").strip())


def _is_absolute_glob(pattern: str) -> bool:
    return pattern.startswith("/") or pattern.startswith("~") or bool(_WINDOWS_PATH_RE.match(pattern))


def _matches(candidate: str, pattern: str) -> bool:
    return re.fullmatch(_glob_to_regex(pattern), candidate) is not None


def _message_outside_root(resolved: Path, root: Path) -> str:
    return (
        f"blocked by mixer:scope: '{resolved}' resolves outside the project root ({root}). "
        "Only an absolute glob in /mixer scope can allow writes there."
    )


def _message_not_in_scope(path_text: str, globs: list[str]) -> str:
    return (
        f"blocked by mixer:scope: '{path_text}' is not in scope "
        f"(allowed globs: {', '.join(globs) or '<empty>'}). "
        "Add a glob with /mixer scope add, or write inside the allowed paths."
    )


def _message_windows(path_text: str) -> str:
    return (
        f"blocked by mixer:scope: '{path_text}' looks like a Windows path. "
        "Agent Mixer works with POSIX paths on this host; use a POSIX path instead."
    )


def check_scope(path_text: str, globs: list[str], root: Path) -> str | None:
    """Return a block message, or None when the write is allowed.

    ``globs`` are the user's scope globs; ``root`` is the project root. Paths
    are resolved (symlinks included) before any check.
    """
    if not path_text:
        # No path to check (missing argument) - let the tool itself fail later.
        return None
    norm = path_text.replace("\\", "/")
    if "\\" in path_text or _WINDOWS_PATH_RE.match(path_text):
        return _message_windows(path_text)

    patterns = [_normalise_glob(g) for g in globs if str(g).strip()]
    raw_path = Path(path_text).expanduser()
    candidate = raw_path if raw_path.is_absolute() else (Path(root) / raw_path)
    resolved = candidate.resolve()
    resolved_root = Path(root).resolve()

    try:
        relative = resolved.relative_to(resolved_root)
        inside_root = True
    except ValueError:
        inside_root = False
        relative = None

    if inside_root and not patterns:
        return None  # no scope configured: everything inside the root is allowed

    matched = False
    absolute_match_allowed = False
    for pattern in patterns:
        if _is_absolute_glob(pattern):
            if _matches(str(resolved), _expand(pattern)):
                matched = True
                absolute_match_allowed = True
        elif inside_root and relative is not None and _matches(relative.as_posix(), pattern):
            matched = True
    if matched:
        if inside_root or absolute_match_allowed:
            return None

    if not inside_root:
        return _message_outside_root(resolved, resolved_root)
    return _message_not_in_scope(path_text, patterns)


def _expand(pattern: str) -> str:
    """Expand a leading ``~`` in a pattern to the absolute home path."""
    if pattern.startswith("~"):
        return str(Path(pattern).expanduser().resolve())
    return pattern