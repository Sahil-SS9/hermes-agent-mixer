"""Direct drivers for the harness-agnostic engine (no Hermes, no hooks)."""
from __future__ import annotations

from threading import RLock

from hermes_agent_mixer.core import decisions, settings
from hermes_agent_mixer.core.calls import Call
from hermes_agent_mixer.core.ports import Ports


class Counter:
    """In-memory per-turn line budget with atomic reserve (same contract as the engine's)."""

    def __init__(self) -> None:
        self.n = 0
        self._lock = RLock()

    def used(self) -> int:
        return self.n

    def reserve(self, lines: int, budget: int):
        with self._lock:
            if self.n + lines > budget:
                return False, self.n
            self.n += lines
            return True, self.n - lines


def knobs(**kw) -> dict:
    return settings.resolve(kw).values


def run(call: Call, root=None, windows: bool = False, budget: Counter | None = None, **kw):
    ports = Ports(windows=windows, cwd=str(root) if root is not None else None)
    return decisions.decide(call, knobs(**kw), ports, budget if budget is not None else Counter())


def write(path, content="x\n") -> Call:
    return Call("write", tool="write_file", path=str(path), content=content)


def edit(path, old, new, replace_all=False) -> Call:
    return Call("edit", tool="patch", path=str(path), old=old, new=new, replace_all=replace_all)


def shell(command, cwd=None, flavour="posix") -> Call:
    return Call("shell", tool="terminal", command=command, cwd=cwd, shell=flavour)


def action(decision) -> str:
    return "allow" if decision is None else decision.action
