"""Scope globs (D3).

An empty scope means no restriction. A relative glob anchors at the workspace root; an absolute
glob (``/...``, ``~/...``, or a drive path on a Windows host) matches absolute paths anywhere.
Subjects are absolute, forward-slash paths already resolved by the ports (symlinks followed on
POSIX, ntpath-normalised on Windows). Windows hosts match case-insensitively.
"""
from __future__ import annotations

import os
import re

_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def glob_to_regex(pattern: str) -> str:
    """``**`` spans path components, ``*`` stops at a separator, ``?`` is one non-separator character."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i + 1:i + 2] == "*":
                while i < len(pattern) and pattern[i] == "*":
                    i += 1
                if pattern[i:i + 1] == "/":
                    i += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)


def normalise_glob(pattern: str, windows: bool) -> str:
    text = pattern.strip()
    if text.startswith("~"):
        text = os.path.expanduser(text)
    if windows:
        text = text.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def is_absolute_glob(pattern: str, windows: bool) -> bool:
    if pattern.startswith("/"):
        return True
    return windows and bool(_DRIVE.match(pattern))


def allowed(path: str, globs: list[str], root: str, *, windows: bool = False) -> bool:
    """True when ``path`` is permitted. No globs means everything is."""
    patterns = [normalise_glob(g, windows) for g in globs if str(g).strip()]
    if not patterns:
        return True
    flags = re.IGNORECASE if windows else 0
    anchor = re.escape(root.rstrip("/"))
    for pattern in patterns:
        if is_absolute_glob(pattern, windows):
            regex = glob_to_regex(pattern)
        else:
            regex = anchor + "/" + glob_to_regex(pattern)
        if re.fullmatch(regex, path, flags):
            return True
    return False


def not_in_scope_message(path_text: str, globs: list[str], no_bypass: str) -> str:
    return (f"blocked by mixer:scope: '{path_text}' is not in scope "
            f"(allowed globs: {', '.join(globs) or '<empty>'}). {no_bypass} "
            "Add a glob with /mixer scope add <glob>, or write inside the allowed paths.")
