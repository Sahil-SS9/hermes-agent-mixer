"""agent-mixer doctor (X7): where things live, what is installed, and what is wrong."""
from __future__ import annotations

import os
import sys

from hermes_agent_mixer.core import settings
from hermes_agent_mixer.core.store import FileStore, StoreLockTimeout
from hermes_agent_mixer.harness import install
from hermes_agent_mixer.harness.common import HARNESSES, Paths, SettingsError, load_saved


def _installed(name: str, home: str, here: str) -> list[str]:
    found = []
    for project in (False, True):
        path = install.settings_path(name, home, here, project)
        try:
            data = install._load(path)
        except ValueError:
            found.append(f"{path} (not valid JSON)")
            continue
        hooks = data.get("hooks") or {}
        ours = [event for event, groups in hooks.items() if isinstance(groups, list)
                for group in groups if isinstance(group, dict)
                for hook in (group.get("hooks") or []) if install._is_ours(hook, name)]
        if ours:
            found.append(f"{path} ({', '.join(sorted(set(ours)))})")
    return found


def run(environ, here: str) -> int:
    from hermes_agent_mixer import __version__

    paths = Paths(environ)
    home = paths.user_home
    problems = 0
    print(f"agent-mixer {__version__}  python {sys.version.split()[0]}  {install.executable()}")
    print(f"settings: {paths.settings_file}")
    print(f"state:    {paths.state_dir}")
    try:
        saved = load_saved(paths)
        eff = settings.resolve(saved)
        shown = ", ".join(f"{k}={eff.values[k]!r} ({eff.sources[k]})" for k in settings.DIALS)
        print(f"saved:    {shown}")
        for warning in eff.warnings:
            problems += 1
            print(f"  ! {warning}")
    except SettingsError as exc:
        problems += 1
        print(f"saved:    unreadable - {exc}")
    try:
        with FileStore(paths.state_dir, lock_wait=1).transaction() as tx:
            print(f"store:    ok, {len(tx.ids())} session(s) known")
    except (StoreLockTimeout, OSError) as exc:
        problems += 1
        print(f"store:    problem - {exc}")
    for name in HARNESSES:
        where = _installed(name, home, here)
        status = "; ".join(where) if where else "not installed (agent-mixer install " + name + " --yes)"
        print(f"{name:7s} {status}")
    print("codex and gemini adapters are contract-tested only; Codex needs the hooks trusted in /hooks.")
    print("Hermes keeps its own saved values (Desktop settings form and /mixer save); this CLI's settings.json is separate.")
    print("Mixer sees tool calls, not system calls: terminal and code-running tools are best effort, not a sandbox.")
    print("Problems found: " + (str(problems) if problems else "none"))
    return 0
