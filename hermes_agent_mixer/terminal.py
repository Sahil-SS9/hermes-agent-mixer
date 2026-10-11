"""Terminal command classification: splitting, read-only allowlist, redirects.

Used by plan mode (every segment must be read-only) and the deps guard
(S3). Splitting respects quotes via shlex.
"""

from __future__ import annotations

import shlex

_SIMPLE_READ_ONLY = {
    "ls", "cat", "head", "tail", "grep", "rg", "wc", "tree", "pwd", "which", "env",
}

_GIT_READ_ONLY_SUBS = {"status", "diff", "log", "show", "branch", "rev-parse"}

_GIT_BRANCH_WRITE_FLAGS = {
    "-d", "-D", "-m", "-M", "-c", "-C", "-u", "-f",
    "--delete", "--move", "--copy", "--set-upstream", "--force",
}

_FIND_WRITE_FLAGS = {"-delete", "-exec", "-execdir", "-ok", "-okdir"}

_OPERATORS = {";", "&&", "||", "|"}


def split_segments(command: str) -> list[list[str]]:
    """Split on ``;``, ``&&``, ``||`` and ``|``; quotes are respected.

    Returns a list of token lists (one per segment).
    """
    try:
        tokens = shlex.split(command or "")
    except ValueError:
        # Unbalanced quotes: treat the whole command as one segment of raw text;
        # plan mode will block it as non-read-only.
        return [[command or ""]]
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _OPERATORS:
            segments.append(current)
            current = []
            continue
        current.append(token)
    segments.append(current)
    return [seg for seg in segments if seg]


def has_redirect(tokens: list[str]) -> bool:
    """True when the segment writes anywhere: ``>``, ``>>``, ``2>``... or ``tee``."""
    program = tokens[0] if tokens else ""
    if program == "tee":
        return True
    for token in tokens:
        if token in (">", ">>"):
            return True
        if token == "&>" or token == "&>>":
            return True
    return False


def is_read_only_segment(tokens: list[str]) -> bool:
    """Whether one segment is on the plan-mode read-only allowlist."""
    if not tokens:
        return True  # empty segment (e.g. leading operator) - nothing runs
    if has_redirect(tokens):
        return False
    program = tokens[0]
    if program == "find":
        return not any(f in tokens for f in _FIND_WRITE_FLAGS)
    if program == "git":
        if len(tokens) < 2:
            return True  # bare "git" prints help
        sub = tokens[1]
        if sub not in _GIT_READ_ONLY_SUBS:
            return False
        if sub == "branch":
            return not any(f in tokens for f in _GIT_BRANCH_WRITE_FLAGS)
        return True
    return program in _SIMPLE_READ_ONLY


def classify_command(command: str) -> tuple[bool, int]:
    """Classify the whole command line.

    Returns ``(all_read_only, first_non_read_only_segment_index)``. Segments are
    split on operators with quotes respected; a redirect counts as a write.
    """
    for index, tokens in enumerate(split_segments(command)):
        if not is_read_only_segment(tokens):
            return False, index
    return True, -1