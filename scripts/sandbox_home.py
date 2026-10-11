"""One cached sandbox Hermes home for every slow lane (P2).

Building a Hermes home from nothing costs about 40 s and 1.6 GB (``tools/``, ``cache/`` and
``installs/``). Build it once under ``MIXER_SANDBOX_CACHE`` (default
``$XDG_CACHE_HOME/agent-mixer-tests``), then give each run a fresh home that symlinks those three
directories and holds only its own plugin and config. The base home must never be moved: the
managed environments inside ``installs/`` record absolute paths.
"""
from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path

SHARED = ("tools", "cache", "installs")
MARKER = ".mixer-base-ready"


def cache_root() -> Path:
    explicit = os.environ.get("MIXER_SANDBOX_CACHE")
    if explicit:
        return Path(explicit)
    xdg = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(xdg) / "agent-mixer-tests"


def hermes_bin() -> str:
    return os.environ.get("HERMES_BIN", "/home/kensei/.local/bin/hermes")


def base_env(base: Path, cache: Path) -> dict:
    env = dict(os.environ)
    user = cache / "user-home"
    tmp = cache / "tmp"
    for folder in (user, tmp):
        folder.mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(user), HERMES_HOME=str(base), TMPDIR=str(tmp), GIT_CEILING_DIRECTORIES=str(tmp),
               XDG_CONFIG_HOME=str(user / ".config"), XDG_DATA_HOME=str(user / ".local/share"),
               XDG_STATE_HOME=str(user / ".local/state"), XDG_CACHE_HOME=str(user / ".cache"))
    for var in ("DISPLAY", "WAYLAND_DISPLAY", "TERMINAL_CWD", "HERMES_SESSION_ID", "HERMES_SESSION_KEY"):
        env.pop(var, None)
    return env


def ensure_base_home() -> Path:
    """Return the cached base home, building it on first use (serialised across processes)."""
    cache = cache_root()
    cache.mkdir(parents=True, exist_ok=True)
    base = cache / "hermes-base-home"
    with open(cache / ".base.lock", "a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (base / MARKER).is_file():
            base.mkdir(parents=True, exist_ok=True)
            done = subprocess.run([hermes_bin(), "plugins", "list"], env=base_env(base, cache),
                                  capture_output=True, text=True, timeout=600, check=False)
            if done.returncode != 0 or not all((base / name).is_dir() for name in SHARED):
                raise RuntimeError(f"cannot build the base Hermes home: {done.stdout[-400:]}{done.stderr[-400:]}")
            (base / MARKER).write_text("ready\n", encoding="utf-8")
    return base


def make_home(dest: Path) -> Path:
    """A fresh Hermes home at ``dest`` that shares tools/, cache/ and installs/ with the base home."""
    base = ensure_base_home()
    dest.mkdir(parents=True, exist_ok=True)
    for name in SHARED:
        link = dest / name
        if not link.exists() and not link.is_symlink():
            link.symlink_to(base / name, target_is_directory=True)
    return dest
