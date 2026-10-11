"""Quote-aware shell reading for plan mode (a read-only allowlist) and for shell write targets.

Mixer sees tool calls, not system calls. This is a conservative reader of ordinary commands, not a
shell interpreter and not a sandbox: opaque forms (``bash -c "$X"``, ``eval``, running a script)
are allowed outside plan mode and documented as such.
"""
from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass, field


@dataclass
class Segment:
    words: list[str] = field(default_factory=list)
    redirects: list[tuple[str, str, str]] = field(default_factory=list)  # (fd, op, target)
    unsafe: str | None = None


def scan(command: str) -> list[Segment]:
    """Split a POSIX shell line into segments of words and redirects, honouring quotes."""
    segments: list[Segment] = []
    words: list[str] = []
    redirects: list[tuple[str, str, str]] = []
    state: dict = {"unsafe": None, "pending": None}
    buf: list[str] = []
    have = False
    text = command or ""
    n = len(text)
    i = 0

    def mark(reason: str) -> None:
        if state["unsafe"] is None:
            state["unsafe"] = reason

    def flush() -> None:
        nonlocal buf, have
        if have:
            word = "".join(buf)
            if state["pending"] is not None:
                fd, op = state["pending"]
                redirects.append((fd, op, word))
                state["pending"] = None
            else:
                words.append(word)
        buf, have = [], False

    def end_segment() -> None:
        nonlocal words, redirects
        flush()
        if state["pending"] is not None:
            mark("incomplete redirect")
            state["pending"] = None
        if words or redirects or state["unsafe"]:
            segments.append(Segment(words, redirects, state["unsafe"]))
        words, redirects = [], []
        state["unsafe"] = None

    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 < n:
                if text[i + 1] != "\n":
                    buf.append(text[i + 1])
                    have = True
                i += 2
            else:
                mark("trailing backslash")
                i += 1
            continue
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                mark("unterminated quote")
                buf.append(text[i + 1:])
                have = True
                i = n
            else:
                buf.append(text[i + 1:j])
                have = True
                i = j + 1
            continue
        if c == '"':
            have = True
            i += 1
            while i < n and text[i] != '"':
                ch = text[i]
                if ch == "\\" and i + 1 < n and text[i + 1] in '$`"\\\n':
                    if text[i + 1] != "\n":
                        buf.append(text[i + 1])
                    i += 2
                    continue
                if ch == "`" or (ch == "$" and text[i + 1:i + 2] == "("):
                    mark("command substitution")
                buf.append(ch)
                i += 1
            if i >= n:
                mark("unterminated quote")
            else:
                i += 1
            continue
        if c == "$":
            if text[i + 1:i + 2] == "(":
                mark("command substitution")
            buf.append(c)
            have = True
            i += 1
            continue
        if c == "`":
            mark("command substitution")
            i += 1
            continue
        if c in " \t":
            flush()
            i += 1
            continue
        if c in ";\n":
            end_segment()
            i += 1
            continue
        if c == "|":
            end_segment()
            i += 2 if text[i + 1:i + 2] in ("|", "&") else 1
            continue
        if c in "()":
            mark("subshell")
            flush()
            i += 1
            continue
        if c == "&" and text[i + 1:i + 2] != ">":
            end_segment()
            i += 2 if text[i + 1:i + 2] == "&" else 1
            continue
        if c in "<>&":
            fd = None
            if have and "".join(buf).isdigit():
                fd = "".join(buf)
                buf, have = [], False
            else:
                flush()
            if text.startswith(("<(", ">("), i):
                mark("process substitution")
                i += 2
                continue
            if text.startswith("<<", i):
                mark("heredoc or here-string")
                i += 3 if text.startswith("<<<", i) else 2
                continue
            if c == "&":  # &> / &>>
                op = "&>>" if text.startswith("&>>", i) else "&>"
                fd = "&"
            elif text.startswith(">>", i):
                op = ">>"
            elif text.startswith((">&", "<&", ">|"), i):
                op = text[i:i + 2]
            else:
                op = c
            if state["pending"] is not None:
                mark("incomplete redirect")
            state["pending"] = (fd or ("0" if c == "<" else "1"), op)
            i += len(op)
            continue
        buf.append(c)
        have = True
        i += 1
    end_segment()
    return segments


def split_segments(command: str) -> list[list[str]]:
    return [segment.words for segment in scan(command)]


def has_redirect(tokens: list[str]) -> bool:
    """Compatibility helper for unquoted token lists."""
    return bool(tokens and tokens[0] == "tee") or any(
        token.startswith((">", "2>", "1>", "&>")) for token in tokens)


# ---------------------------------------------------------------------------------------------
# Plan mode: read-only allowlist
# ---------------------------------------------------------------------------------------------

_PLAIN_READ = {
    "ls", "cat", "head", "tail", "wc", "grep", "rg", "tree", "pwd", "which", "echo", "printf", "basename",
    "dirname", "realpath", "cut", "diff", "cmp", "stat", "du", "df", "file", "jq", "cd", "true", "false",
    "date", "whoami", "id", "uname", "readlink", "nproc", "hostname", "sleep",
}
_FIND_WRITE_FLAGS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
_GIT_READ_SUBS = {"status", "diff", "log", "show", "ls-files", "ls-tree", "blame", "describe", "shortlog",
                  "rev-parse", "grep"}
_GIT_BAD_FLAGS = {"--output", "--ext-diff", "--textconv", "-O", "--open-files-in-pager"}
_BRANCH_READ_FLAGS = {"-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "--list", "--show-current",
                      "--color", "--no-color", "--column", "--no-column", "--ignore-case", "-l"}
_BRANCH_VALUE_FLAGS = {"--sort", "--format", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"}
_TAG_READ_FLAGS = {"-l", "--list", "-n", "--sort", "--contains", "--no-contains", "--merged", "--no-merged",
                   "--points-at", "--format", "--color", "--no-color", "--column", "--no-column", "--ignore-case", "-i"}
_CONFIG_READ_FLAGS = {"--get", "--get-all", "--get-regexp", "--list", "-l", "--local", "--global", "--system",
                      "--show-origin", "--show-scope", "--null", "-z", "--name-only", "--includes", "--no-includes"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SED_SCRIPT = re.compile(
    r"\s*(?:(?:\d+|\$|/[^/]*/)(?:,(?:\d+|\$|/[^/]*/))?)?\s*!?\s*(?:[pPdq=l]|s/[^/]*/[^/]*/[gpiI0-9]*)\s*")


def _flag_of(token: str) -> str:
    return token.split("=", 1)[0]


def _read_only_branch(args: list[str]) -> bool:
    listing = "--list" in args or "-l" in args
    i = 0
    while i < len(args):
        token = args[i]
        flag = _flag_of(token)
        if flag in _BRANCH_READ_FLAGS:
            i += 1
        elif flag in _BRANCH_VALUE_FLAGS:
            i += 1 if "=" in token else 2
        elif not token.startswith("-") and listing:
            i += 1
        else:
            return False
    return True


def _read_only_tag(args: list[str]) -> bool:
    listing = "-l" in args or "--list" in args
    i = 0
    while i < len(args):
        token = args[i]
        flag = _flag_of(token)
        if flag in _TAG_READ_FLAGS:
            i += 1 if (flag in ("-l", "--list", "-i", "--ignore-case") or "=" in token or flag.startswith("--no-")
                       or flag in ("--color", "--column")) else 2
        elif not token.startswith("-") and listing:
            i += 1
        else:
            return False
    return True


def _read_only_git(args: list[str]) -> bool:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in ("--no-pager", "--no-optional-locks"):
            i += 1
        elif args[i] == "-C" and i + 1 < len(args):
            i += 2
        else:
            return False
    if i >= len(args):
        return True
    sub, rest = args[i], args[i + 1:]
    if any(_flag_of(token) in _GIT_BAD_FLAGS for token in rest):
        return False
    if sub in _GIT_READ_SUBS:
        return True
    if sub == "branch":
        return _read_only_branch(rest)
    if sub == "tag":
        return _read_only_tag(rest)
    if sub == "remote":
        return rest in ([], ["-v"], ["-vv"], ["--verbose"])
    if sub == "config":
        flags = [t for t in rest if t.startswith("-")]
        if any(_flag_of(t) not in _CONFIG_READ_FLAGS for t in flags):
            return False
        reading_key = any(_flag_of(t) in ("--get", "--get-all", "--get-regexp") for t in flags)
        return reading_key or not [t for t in rest if not t.startswith("-")]
    return False


def _read_only_sed(args: list[str]) -> bool:
    quiet = False
    scripts: list[str] = []
    positional: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in ("-e", "--expression"):
            if i + 1 >= len(args):
                return False
            scripts.append(args[i + 1])
            i += 2
            continue
        if token.startswith("--expression="):
            scripts.append(token.split("=", 1)[1])
        elif token in ("-n", "--quiet", "--silent"):
            quiet = True
        elif token.startswith("-") and not token.startswith("--") and len(token) > 1:
            letters = token[1:]
            if any(ch in letters for ch in "ifsz") or "e" in letters:
                return False
            quiet = quiet or "n" in letters
            if any(ch not in "nEr" for ch in letters):
                return False
        elif token.startswith("-"):
            if token not in ("--regexp-extended", "--posix", "--null-data", "--debug", "--sandbox"):
                return False
        else:
            positional.append(token)
        i += 1
    if not scripts:
        if not positional:
            return False
        scripts.append(positional.pop(0))
    if not quiet and not any(s.strip().endswith("p") for s in scripts):
        pass  # a script without -n prints and never writes; the script check below is what matters
    for script in scripts:
        for part in re.split(r"[;\n]", script):
            if part.strip() and not _SED_SCRIPT.fullmatch(part):
                return False
    return True


def _read_only_sort(args: list[str]) -> bool:
    for token in args:
        if token == "--":
            break
        if token.startswith("--"):
            if _flag_of(token) in ("--output", "--compress-program", "--files0-from"):
                return False
        elif token.startswith("-") and len(token) > 1 and "o" in token[1:] and not token[1:].startswith(("k", "t")):
            return False
    return True


def _read_only_uniq(args: list[str]) -> bool:
    value_flags = {"-f", "-s", "-w", "--skip-fields", "--skip-chars", "--check-chars"}
    positional = 0
    i = 0
    while i < len(args):
        token = args[i]
        if token in value_flags:
            i += 2
            continue
        if not token.startswith("-") or token == "-":
            positional += 1
        i += 1
    return positional <= 1


def is_read_only_segment(words: list[str]) -> bool:
    """Allow only known read commands and their non-writing forms."""
    if not words:
        return True
    program, args = words[0], words[1:]
    if _ASSIGNMENT.match(program) or "/" in program:
        return False
    if program == "find":
        return not any(_flag_of(token) in _FIND_WRITE_FLAGS or token.startswith("-fprint") for token in args)
    if program == "sed":
        return _read_only_sed(args)
    if program == "sort":
        return _read_only_sort(args)
    if program == "uniq":
        return _read_only_uniq(args)
    if program == "git":
        return _read_only_git(args)
    if program == "tree":
        return not any(token.startswith("-o") for token in args)
    if program == "rg":
        return not any(_flag_of(token) in ("--pre", "--hostname-bin") for token in args)
    if program == "file":
        return not any(token in ("-C", "--compile") for token in args)
    if program == "env":
        return all(token in ("-0", "--null", "--help", "--version") for token in args)
    return program in _PLAIN_READ


def _harmless_redirect(fd: str, op: str, target: str) -> bool:
    if op == "<":
        return True
    if op in (">", ">>", "&>", "&>>", ">|"):
        return target == "/dev/null"
    if op in (">&", "<&"):
        return target.isdigit() or target == "-"
    return False


def classify_plan(command: str, flavour: str = "posix") -> tuple[bool, int]:
    """(all read-only, index of the first unsafe segment); never executes the command."""
    if flavour == "powershell":
        return _classify_powershell(command)
    for index, segment in enumerate(scan(command)):
        if segment.unsafe:
            return False, index
        if not all(_harmless_redirect(*redirect) for redirect in segment.redirects):
            return False, index
        if not is_read_only_segment(segment.words):
            return False, index
    return True, -1


classify_command = classify_plan  # 0.1 name


_PS_ALLOWED = re.compile(r"^(?:Get-[A-Za-z]+|Select-String)$", re.IGNORECASE)


def _classify_powershell(command: str) -> tuple[bool, int]:
    """Allow ``Get-*`` cmdlets and ``Select-String``; block everything else, quote-aware."""
    segments: list[list[str]] = []
    words: list[str] = []
    buf: list[str] = []
    have = False
    quote = ""
    bad = False
    for ch in command or "":
        if quote:
            if ch == quote:
                quote = ""
            else:
                if quote == '"' and ch in "`$":
                    bad = bad or ch == "`" or False
                buf.append(ch)
            continue
        if ch in "'\"":
            quote, have = ch, True
        elif ch == "`":
            bad = True
        elif ch in "<>&{}":
            bad = True
        elif ch in ";|\n":
            if have:
                words.append("".join(buf))
            buf, have = [], False
            segments.append(words)
            words = []
        elif ch in " \t":
            if have:
                words.append("".join(buf))
            buf, have = [], False
        else:
            buf.append(ch)
            have = True
    if have:
        words.append("".join(buf))
    segments.append(words)
    segments = [s for s in segments if s]
    if bad or quote or "$(" in (command or ""):
        return False, 0
    for index, words in enumerate(segments):
        if not _PS_ALLOWED.match(words[0]):
            return False, index
    return True, -1


# ---------------------------------------------------------------------------------------------
# Write targets (best effort, scope check outside plan mode)
# ---------------------------------------------------------------------------------------------


@dataclass
class Target:
    path: str
    base: str | None = None  # a directory reached with ``cd`` inside the same command, else None
    source: str = ""  # the command that writes it
    directory: bool = False  # the path is (or may be) a directory: files inside it count


_OPAQUE = re.compile(r"[$`*?\[]|^-$")


def _positionals(args: list[str], value_flags: set[str]) -> list[str]:
    out: list[str] = []
    skip = False
    after_dd = False
    for token in args:
        if skip:
            skip = False
            continue
        if after_dd:
            out.append(token)
            continue
        if token == "--":
            after_dd = True
        elif token in value_flags:
            skip = True
        elif token.startswith("-") and len(token) > 1:
            continue
        else:
            out.append(token)
    return out


def _flag_value(args: list[str], short: str, long: str) -> str | None:
    for i, token in enumerate(args):
        if token == short and i + 1 < len(args):
            return args[i + 1]
        if token.startswith(long + "="):
            return token.split("=", 1)[1]
    return None


def _segment_targets(words: list[str]) -> list[str]:
    program, args = words[0], words[1:]
    if program == "tee":
        return _positionals(args, set())
    if program == "sed":
        in_place = any(t in ("-i", "--in-place") or t.startswith(("-i", "--in-place="))
                       or (t.startswith("-") and not t.startswith("--") and "i" in t[1:] and len(t) > 1)
                       for t in args if t.startswith("-"))
        if not in_place:
            return []
        has_script_flag = any(t in ("-e", "-f", "--expression", "--file") or t.startswith(("--expression=", "--file="))
                              for t in args)
        positional = _positionals(args, {"-e", "-f", "--expression", "--file", "-l", "--line-length"})
        return positional if has_script_flag else positional[1:]
    if program in ("cp", "mv", "ln", "install"):
        values = {"-S", "--suffix", "-t", "--target-directory", "-m", "--mode", "-o", "--owner", "-g", "--group"}
        if program == "install" and any(t in ("-d", "--directory") for t in args):
            return _positionals(args, values)
        positional = _positionals(args, values)
        directory = _flag_value(args, "-t", "--target-directory")
        if directory is not None:
            targets = [directory]
        else:
            targets = positional[-1:] if len(positional) >= (1 if program == "ln" else 2) else []
        if program == "mv":
            targets = targets + (positional[:-1] if directory is None else positional)
        return targets
    if program in ("touch",):
        return _positionals(args, {"-d", "--date", "-t", "-r", "--reference"})
    if program in ("rm", "rmdir"):
        return _positionals(args, set())
    if program == "mkdir":
        return _positionals(args, {"-m", "--mode"})
    if program == "truncate":
        return _positionals(args, {"-s", "--size", "-r", "--reference"})
    if program == "dd":
        return [t[3:] for t in args if t.startswith("of=")]
    return []


def write_targets(command: str) -> list[Target]:
    """Best-effort paths a POSIX command line writes, with ``cd`` tracked inside the line."""
    found: list[Target] = []
    base: str | None = None
    for segment in scan(command):
        if segment.unsafe and not segment.words:
            continue
        for fd, op, target in segment.redirects:
            if op in (">", ">>", "&>", "&>>", ">|") and target != "/dev/null":
                found.append(Target(target, base, "redirect"))
            elif op == ">&" and not (target.isdigit() or target == "-"):
                found.append(Target(target, base, "redirect"))
        if not segment.words:
            continue
        program = segment.words[0]
        if program == "cd":
            argument = segment.words[1] if len(segment.words) == 2 else None
            if argument and not _OPAQUE.search(argument) and argument != "-":
                base = argument if base is None or posixpath.isabs(argument) else posixpath.join(base, argument)
            else:
                base = None
            continue
        dir_flag = _flag_value(segment.words[1:], "-t", "--target-directory")
        for target in _segment_targets(segment.words):
            found.append(Target(target, base, program, program in ("mkdir", "rmdir", "rm", "mv", "cp", "install")
                                or target == dir_flag))
    return [t for t in found if t.path and not _OPAQUE.search(t.path)]


def quote_words(words: list[str]) -> str:
    try:
        return shlex.join(words)
    except Exception:  # pragma: no cover - defensive
        return " ".join(words)
