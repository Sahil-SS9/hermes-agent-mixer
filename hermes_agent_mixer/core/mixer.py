"""The engine: session state over a store, with saved settings underneath.

Each session record holds its dial overrides, its parent link (subagents), the current turn and the
lines used so far in that turn. A child resolves to its root session: it reads the root's dials live
and draws from the root's per-turn budget (D2).
"""
from __future__ import annotations

import time
from typing import Any, Callable

from hermes_agent_mixer.core import decisions, settings
from hermes_agent_mixer.core.calls import Call, Decision
from hermes_agent_mixer.core.store import MemoryStore

MAX_DEPTH = 16
TOUCH_EVERY = 3600.0


class TurnBudget:
    """The root session's per-turn line counter, with atomic reserve inside the open transaction."""

    def __init__(self, record: dict) -> None:
        self._record = record

    def used(self) -> int:
        return int(self._record.get("used", 0))

    def reserve(self, lines: int, budget: int) -> tuple[bool, int]:
        used = self.used()
        if used + lines > budget:
            return False, used
        self._record["used"] = used + lines
        return True, used


class Mixer:
    def __init__(self, store: Any = None, saved: Callable[[], dict] | None = None, *,
                 clock: Callable[[], float] = time.time, max_idle: float = 24 * 3600.0,
                 max_sessions: int = 1000, config_get: Callable[[str, Any], Any] | None = None):
        self.store = store if store is not None else MemoryStore()
        if saved is None:
            if config_get is not None:
                saved = lambda: {k: v for k in settings.SAVED_KEYS if (v := config_get(k, None)) is not None}  # noqa: E731
            else:
                saved = dict
        self._saved = saved
        self._clock = clock
        self.max_idle = max_idle
        self.max_sessions = max_sessions

    # -- records ---------------------------------------------------------------------------
    @staticmethod
    def _key(session_id: str | None) -> str:
        return (session_id or "").strip()

    def _ensure(self, tx: Any, sid: str, cwd: str | None = None) -> dict:
        record = tx.get(sid)
        now = self._clock()
        if record is None:
            record = {"overrides": {}, "parent": None, "turn": None, "used": 0, "touched": now, "cwd": cwd}
            tx.put(sid, record)
        else:
            if now - float(record.get("touched", 0.0)) > TOUCH_EVERY or "touched" not in record:
                record["touched"] = now
            if cwd and record.get("cwd") != cwd:
                record["cwd"] = cwd
        return record

    def _root(self, tx: Any, sid: str) -> str:
        seen = {sid}
        current = sid
        for _ in range(MAX_DEPTH):
            record = tx.get(current)
            parent = (record or {}).get("parent")
            if not parent or parent in seen or tx.get(parent) is None:
                return current
            seen.add(parent)
            current = parent
        return current

    # -- effective view --------------------------------------------------------------------
    def _effective(self, tx: Any, sid: str) -> settings.Effective:
        root = self._root(tx, sid)
        record = tx.get(root) or {}
        eff = settings.resolve(self._saved(), record.get("overrides"), session=sid)
        budget = eff.values["lines"]
        if budget:
            eff.left = max(budget - int(record.get("used", 0)), 0)
        return eff

    def effective(self, session_id: str | None) -> settings.Effective:
        """Dials in force for a session; with no session, saved settings and defaults only."""
        sid = self._key(session_id)
        with self.store.transaction() as tx:
            if not sid:
                return settings.resolve(self._saved(), None)
            return self._effective(tx, sid)

    # -- lifecycle -------------------------------------------------------------------------
    def link_child(self, child: str, parent: str, *, cwd: str | None = None) -> None:
        child, parent = self._key(child), self._key(parent)
        if not child or not parent or child == parent:
            return
        with self.store.transaction() as tx:
            self._link(tx, child, parent, cwd)

    def _link(self, tx: Any, child: str, parent: str, cwd: str | None = None) -> None:
        root = self._root(tx, parent)
        if root == child:  # would close a loop
            return
        self._ensure(tx, root, cwd)
        record = self._ensure(tx, child, cwd)
        record["parent"] = root
        record["touched"] = self._clock()
        tx.get(root)["touched"] = self._clock()

    def drop(self, session_id: str) -> None:
        sid = self._key(session_id)
        if sid:
            with self.store.transaction() as tx:
                tx.delete(sid)

    def begin_turn(self, session_id: str, turn_id: str | None = None, *, parent: str | None = None,
                   cwd: str | None = None) -> None:
        """A new turn: reset the lines used so far. A child's turn never resets its root's budget."""
        sid = self._key(session_id)
        if not sid:
            return
        with self.store.transaction() as tx:
            record = self._ensure(tx, sid, cwd)
            if parent and self._key(parent) != sid:
                self._link(tx, sid, self._key(parent), cwd)
                record = tx.get(sid)
            if not record.get("parent"):
                record["used"] = 0
                record["turn"] = turn_id
            record["touched"] = self._clock()
            tx.prune(self._clock(), self.max_idle, self.max_sessions)

    def decide(self, session_id: str, call: Call, ports: Any, *, turn_id: str | None = None,
               task_id: str | None = None, cwd: str | None = None, extra: dict | None = None) -> Decision | None:
        """Evaluate one tool call against the session's dials and charge its lines."""
        sid = self._key(session_id)
        with self.store.transaction() as tx:
            own = self._ensure(tx, sid, cwd)
            root = self._root(tx, sid)
            record = own if root == sid else self._ensure(tx, root)
            if turn_id is not None and root == sid and record.get("turn") != turn_id:
                record["turn"], record["used"] = turn_id, 0
            eff = self._effective(tx, sid)
            knobs = dict(eff.values)
            if extra:
                knobs.update(extra)
            return decisions.decide(call, knobs, ports, TurnBudget(record), task_id)

    def rules_line(self, session_id: str | None) -> str:
        return rules_line(self.effective(session_id))

    # -- changes ---------------------------------------------------------------------------
    def set_session(self, session_id: str, knob: str, value: Any) -> None:
        if not settings.is_valid_knob(knob):
            raise KeyError(f"unknown knob: {knob}")
        coerced, ok = settings.coerce(knob, value)
        if not ok:
            raise ValueError(f"{value!r} is not a valid {knob}")
        sid = self._key(session_id)
        with self.store.transaction() as tx:
            record = self._ensure(tx, self._root(tx, sid) if tx.get(sid) else sid)
            if knob == "lines":
                record["used"] = int(record.get("used", 0))
            record["overrides"][knob] = coerced

    def reset_session(self, session_id: str) -> None:
        sid = self._key(session_id)
        with self.store.transaction() as tx:
            root = self._root(tx, sid)
            record = tx.get(root)
            if record is not None:
                record["overrides"] = {}

    def parent_of(self, session_id: str) -> str | None:
        with self.store.transaction() as tx:
            return (tx.get(self._key(session_id)) or {}).get("parent")

    def session_ids(self) -> list[str]:
        with self.store.transaction() as tx:
            return tx.ids()

    def latest_session(self, cwd: str) -> str | None:
        """The most recently touched session seen in this folder (or a parent or child folder)."""
        best: tuple[float, str] | None = None
        with self.store.transaction() as tx:
            for sid in tx.ids():
                record = tx.get(sid) or {}
                where = record.get("cwd") or ""
                if not where or not _related(where, cwd) or record.get("parent"):
                    continue
                stamp = float(record.get("touched", 0.0))
                if best is None or stamp >= best[0]:
                    best = (stamp, sid)
        return best[1] if best else None

    def on_unload(self) -> None:
        clear = getattr(self.store, "clear", None)
        if callable(clear):
            clear()


def _related(a: str, b: str) -> bool:
    a, b = a.rstrip("/\\"), b.rstrip("/\\")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def rules_line(eff: settings.Effective) -> str:
    """One line for the model, only when a dial is off its default (QW2). Under 300 characters."""
    if eff.is_default():
        return ""
    parts = []
    v = eff.values
    if v["edits"] != settings.DEFAULTS["edits"]:
        parts.append(f"edits={v['edits']}")
    if v["scope"]:
        shown = ",".join(v["scope"])
        parts.append("scope=" + (shown if len(shown) <= 60 else shown[:57] + "..."))
    if v["lines"]:
        left = eff.left if eff.left is not None else v["lines"]
        parts.append(f"lines={v['lines']}/turn ({left} left)")
    if v["deps"] != settings.DEFAULTS["deps"]:
        parts.append(f"deps={v['deps']}")
    text = ("Agent Mixer: " + "; ".join(parts) +
            ". Blocks apply to file tools and are best effort on terminal and execute_code; don't work "
            "around a block with terminal or execute_code.")
    return text if len(text) <= 300 else text[:297] + "..."
