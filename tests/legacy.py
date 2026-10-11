"""Adapters that let the 0.1 decision tests drive the 0.2 engine unchanged where behaviour is unchanged.

``evaluate`` has the 0.1 signature (Hermes tool name and args, a knobs dict, a per-turn counter) and
returns the Hermes directive dict, so the same assertions run against the new core.
"""
from __future__ import annotations

from threading import RLock

from hermes_agent_mixer.core import decisions as core_decisions
from hermes_agent_mixer.core import settings
from hermes_agent_mixer.core.ports import Ports
from hermes_agent_mixer.hermes import tools


class LinesState:
    """The 0.1 per-turn counter, keyed by (session, task)."""

    def __init__(self) -> None:
        self._used: dict[tuple[str, str], int] = {}
        self._lock = RLock()

    def used(self, session_id: str, task_id: str) -> int:
        with self._lock:
            return self._used.get((session_id or "", task_id or ""), 0)

    def add(self, session_id: str, task_id: str, lines: int) -> None:
        if lines > 0:
            with self._lock:
                key = (session_id or "", task_id or "")
                self._used[key] = self._used.get(key, 0) + lines

    def reserve(self, session_id: str, task_id: str, lines: int, budget: int):
        key = (session_id or "", task_id or "")
        with self._lock:
            used = self._used.get(key, 0)
            if used + lines > budget:
                return False, used
            self._used[key] = used + lines
            return True, used

    def reset_turn(self, session_id: str, task_id: str) -> None:
        with self._lock:
            self._used = {k: v for k, v in self._used.items() if k[0] != (session_id or "")}

    def session_used(self, session_id: str) -> int:
        with self._lock:
            return sum(v for (s, _t), v in self._used.items() if s == (session_id or ""))


class _Budget:
    def __init__(self, state, session_id, task_id):
        self.state, self.session_id, self.task_id = state, session_id, task_id

    def used(self) -> int:
        return self.state.used(self.session_id, self.task_id)

    def reserve(self, lines, budget):
        return self.state.reserve(self.session_id, self.task_id, lines, budget)


def evaluate(tool_name, args, knobs, state=None, *, root=None, session_id="", task_id=""):
    call = tools.to_call(tool_name, args)
    if call is None:
        return None
    state = getattr(state, "lines_state", state)
    saved = {k: v for k, v in knobs.items() if k in settings.SAVED_KEYS}
    values = settings.resolve(saved).values
    root = root if root is not None else knobs.get("root")
    ports = Ports(cwd=str(root) if root else None)
    budget = _Budget(state, session_id or task_id, task_id) if state is not None else None
    decision = core_decisions.decide(call, values, ports, budget, task_id or None)
    return tools.to_directive(decision)


def estimate(tool_name, args, root=None):
    """0.1 ``diffcount.estimate``: (added, removed) of what a file-tool call would change."""
    from hermes_agent_mixer.core import diffcount

    call = tools.to_call(tool_name, args)
    if call is None or call.kind not in ("write", "edit", "patch"):
        return 0, 0
    added = removed = 0
    for change in diffcount.changes(call, Ports(cwd=str(root) if root else None)):
        if change.estimate is not None:
            added += change.estimate
            continue
        a, r = diffcount.count_diff_lines(change.before, change.after)
        added, removed = added + a, removed + r
    return added, removed


class decisions:  # noqa: N801 - mirrors the 0.1 module name used by the tests
    evaluate = staticmethod(evaluate)
