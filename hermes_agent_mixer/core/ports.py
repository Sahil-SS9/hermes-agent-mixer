"""Path, file and text services the engine needs from its host.

``Ports`` is the host-free default: harness adapters use it with the hook's cwd, and the Hermes
adapter subclasses it to ask Hermes first (hermes/ports.py). Paths come back absolute with forward
slashes, so one string works as a scope subject, a rule key and a store key on every OS.

Windows hosts use ntpath semantics and match case-insensitively (D3). ``windows`` can be forced so
that the Windows behaviour is unit-testable on any machine; on a POSIX host ``C:\\x`` is just a
relative file name, as Hermes itself treats it.
"""
from __future__ import annotations

import ntpath
import os
import sys

from ..core import fuzzy

TERMINAL_CWD_SENTINELS = frozenset({"", ".", "./", "auto", "cwd"})


def env_workspace() -> str | None:
    """``$TERMINAL_CWD`` when it names a real (absolute, non-sentinel) anchor, else None."""
    raw = os.environ.get("TERMINAL_CWD", "").strip()
    if raw.lower() in TERMINAL_CWD_SENTINELS:
        return None
    expanded = os.path.expanduser(raw)
    return expanded if os.path.isabs(expanded) else None


class Ports:
    def __init__(self, *, windows: bool | None = None, cwd: str | None = None, workspace: str | None = None):
        self.windows = (sys.platform == "win32") if windows is None else bool(windows)
        self._cwd = cwd
        self._workspace = workspace

    # -- paths -----------------------------------------------------------------------------
    def _normalise(self, path: str) -> str:
        if self.windows:
            return ntpath.normpath(path).replace("\\", "/")
        return os.path.realpath(path)

    def base_dir(self, task_id: str | None = None) -> str:
        """Where relative file paths resolve from."""
        root = self._cwd or env_workspace() or os.getcwd()
        return self._normalise(root)

    def workspace_root(self, task_id: str | None = None) -> str:
        """Where relative scope globs anchor."""
        return self._normalise(self._workspace) if self._workspace else self.base_dir(task_id)

    def resolve(self, path: str, task_id: str | None = None, base: str | None = None) -> str:
        text = os.path.expanduser(path) if path.startswith("~") else path
        if self.windows:
            if not ntpath.isabs(text):
                text = ntpath.join(base or self.base_dir(task_id), text)
            return self._normalise(text)
        if not os.path.isabs(text):
            text = os.path.join(base or self.base_dir(task_id), text)
        return self._normalise(text)

    # -- files and text --------------------------------------------------------------------
    def read_text(self, path: str) -> str | None:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            return None

    def fuzzy_replace(self, content: str, old: str, new: str, replace_all: bool = False) -> str | None:
        return fuzzy.replace(content, old, new, replace_all)
