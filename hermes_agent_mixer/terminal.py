"""Quote-aware, conservative terminal classification for plan mode and deps.

This is an allowlist of ordinary reads, not a shell interpreter or a sandbox.
Only unquoted shell operators split segments or count as redirects.
"""
from __future__ import annotations

import shlex

_SIMPLE_READ_ONLY = {"ls", "cat", "head", "tail", "grep", "rg", "wc", "tree", "pwd", "which"}
_GIT_READ_ONLY_SUBS = {"status", "diff", "log", "show", "branch", "rev-parse"}
_FIND_WRITE_FLAGS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
_BRANCH_READ_FLAGS = {"-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "--list",
                      "--show-current", "--color", "--no-color", "--column", "--no-column", "--ignore-case"}
_BRANCH_VALUE_FLAGS = {"--sort", "--format", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"}


def _segments(command: str) -> list[tuple[list[str], bool]]:
    """Token lists plus a flag for unapproved shell syntax, retaining quote provenance."""
    result: list[tuple[list[str], bool]] = []
    raw: list[str] = []
    quote = ""
    escaped = False
    unsafe = False

    def finish() -> None:
        nonlocal raw, unsafe
        text = "".join(raw)
        if text.strip():
            try:
                result.append((shlex.split(text), unsafe))
            except ValueError:
                result.append(([text], True))
        raw = []
        unsafe = False

    i = 0
    while i < len(command):
        char = command[i]
        if escaped:
            raw.append(char)
            escaped = False
        elif char == "\\" and quote != "'":
            raw.append(char)
            escaped = True
        elif quote:
            raw.append(char)
            if char == quote:
                quote = ""
            elif quote == '"' and char in ("$", "`"):
                unsafe = True
        elif char in ("'", '"'):
            raw.append(char)
            quote = char
        elif char in (";", "\n", "&", "|"):
            if char == "&" and command[i:i + 2] != "&&":
                unsafe = True
            if char in ("&", "|") and command[i:i + 2] == char * 2:
                i += 1
            finish()
        else:
            raw.append(char)
            if char in (">", "<", "$", "`", "(", ")"):
                unsafe = True
        i += 1
    if quote or escaped:
        unsafe = True
    finish()
    return result


def split_segments(command: str) -> list[list[str]]:
    """Split shell chains, including attached operators, without splitting quoted literals."""
    return [tokens for tokens, _unsafe in _segments(command or "")]


def has_redirect(tokens: list[str]) -> bool:
    """Compatibility helper for unquoted token lists; classify_command retains raw quotes."""
    return bool(tokens and tokens[0] == "tee") or any(
        token.startswith((">", "2>", "1>", "&>")) for token in tokens)


def _read_only_branch(args: list[str]) -> bool:
    listing = "--list" in args
    i = 0
    while i < len(args):
        token = args[i]
        flag = token.split("=", 1)[0]
        if flag in _BRANCH_READ_FLAGS:
            i += 1
        elif flag in _BRANCH_VALUE_FLAGS:
            i += 1 if "=" in token else 2
        elif not token.startswith("-") and listing:
            i += 1
        else:
            return False
    return True


def is_read_only_segment(tokens: list[str]) -> bool:
    """Allow only known read commands and their non-writing forms."""
    if not tokens:
        return True
    program = tokens[0]
    args = tokens[1:]
    if program == "find":
        return not any(token in _FIND_WRITE_FLAGS for token in args)
    if program == "env":
        return all(token in ("-0", "--null", "--help", "--version") for token in args)
    if program == "tree" and any(token.startswith("-o") for token in args):
        return False
    if program == "rg" and any(token.split("=", 1)[0] in ("--pre", "--hostname-bin") for token in args):
        return False
    if program == "git":
        if not args:
            return True
        sub = args[0]
        if sub not in _GIT_READ_ONLY_SUBS:
            return False
        if any(token.split("=", 1)[0] in ("--output", "--ext-diff", "--textconv") for token in args[1:]):
            return False
        return _read_only_branch(args[1:]) if sub == "branch" else True
    return program in _SIMPLE_READ_ONLY


def classify_command(command: str) -> tuple[bool, int]:
    """(all read-only, first unsafe segment index); never executes the command."""
    for index, (tokens, unsafe) in enumerate(_segments(command or "")):
        if unsafe or not is_read_only_segment(tokens):
            return False, index
    return True, -1
