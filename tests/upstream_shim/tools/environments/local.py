import platform
import re

_IS_WINDOWS = platform.system() == "Windows"

def _msys_to_windows_path(cwd: str) -> str:
    """``/c/Users/x`` / ``/cygdrive/c/..`` / ``/mnt/c/..`` -> native ``C:\\Users\\x`` so
    ``isdir``/``Popen(cwd=)`` find it. No-op off Windows, for empty input and for
    multi-segment POSIX paths like ``/home/x``; idempotent on native paths."""
    m = _IS_WINDOWS and cwd and re.match(r'^/(?:(?:cygdrive|mnt)/)?([a-zA-Z])(/.*)?$', cwd)
    if not m:
        return cwd
    tail = (m.group(2) or "").replace('/', '\\')
    return f"{m.group(1).upper()}:{tail or chr(92)}"
