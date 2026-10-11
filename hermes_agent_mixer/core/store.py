"""Session state behind one interface (D9).

``MemoryStore`` serves Hermes (one long-lived process). ``FileStore`` serves the CLI harnesses, where
every hook is a separate process: one store-wide lock (``fcntl.flock(LOCK_EX)`` on the fixed file
``<state dir>/.lock``, ``msvcrt.locking`` on Windows) is held while state is read or changed (X3),
and state files are replaced atomically.

A transaction yields a ``Tx``: ``get(sid)`` returns a mutable record dict (or None), ``put`` stores
one, ``delete`` drops one, ``ids()`` lists sessions, ``touched(sid)`` and ``prune`` handle idleness.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from threading import RLock
from typing import Any, Iterator

LOCK_WAIT_SECONDS = 5.0


class StoreLockTimeout(Exception):
    """The store-wide lock could not be taken in time; callers fail closed (D12)."""


class Tx:
    def get(self, sid: str) -> dict | None:
        raise NotImplementedError

    def put(self, sid: str, record: dict) -> None:
        raise NotImplementedError

    def delete(self, sid: str) -> None:
        raise NotImplementedError

    def ids(self) -> list[str]:
        raise NotImplementedError

    def idle_since(self, sid: str) -> float:
        raise NotImplementedError

    def prune(self, now: float, max_idle: float, max_count: int) -> list[str]:
        """Drop sessions idle for longer than ``max_idle`` seconds, then the oldest beyond ``max_count``."""
        stamps = {sid: self.idle_since(sid) for sid in self.ids()}
        dropped = [sid for sid, stamp in stamps.items() if now - stamp > max_idle]
        keep = sorted((sid for sid in stamps if sid not in dropped), key=lambda s: stamps[s])
        if len(keep) > max_count:
            dropped += keep[: len(keep) - max_count]
        for sid in dropped:
            self.delete(sid)
        return dropped


class MemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, dict] = {}
        self._lock = RLock()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[Tx]:
        with self._lock:
            yield _MemoryTx(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


class _MemoryTx(Tx):
    def __init__(self, records: dict[str, dict]) -> None:
        self._records = records

    def get(self, sid: str) -> dict | None:
        return self._records.get(sid)

    def put(self, sid: str, record: dict) -> None:
        self._records[sid] = record

    def delete(self, sid: str) -> None:
        self._records.pop(sid, None)

    def ids(self) -> list[str]:
        return list(self._records)

    def idle_since(self, sid: str) -> float:
        return float(self._records[sid].get("touched", 0.0))


# -- file store ------------------------------------------------------------------------------------


def _lock_file(handle: Any) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: Any) -> None:
    if os.name == "nt":  # pragma: no cover
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_UN)


class FileStore:
    """One JSON file per session under ``root``; one fixed ``.lock`` file for the whole store."""

    def __init__(self, root: str | os.PathLike, lock_wait: float = LOCK_WAIT_SECONDS) -> None:
        self.root = os.fspath(root)
        self.lock_wait = lock_wait

    def path_of(self, sid: str) -> str:
        return os.path.join(self.root, hashlib.sha256(sid.encode("utf-8")).hexdigest()[:32] + ".json")

    def has_session_file(self, sid: str) -> bool:
        return os.path.isfile(self.path_of(sid))

    @contextlib.contextmanager
    def transaction(self) -> Iterator[Tx]:
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, ".lock"), "a+", encoding="utf-8") as handle:
            deadline = time.monotonic() + self.lock_wait
            while True:
                try:
                    _lock_file(handle)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise StoreLockTimeout(f"could not lock {self.root} within {self.lock_wait:.0f}s") from None
                    time.sleep(0.02)
            try:
                tx = _FileTx(self)
                yield tx
                tx.flush()
            finally:
                _unlock_file(handle)


class _FileTx(Tx):
    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._loaded: dict[str, tuple[dict | None, str | None]] = {}
        self._deleted: set[str] = set()

    def _read(self, sid: str) -> dict | None:
        try:
            with open(self._store.path_of(sid), encoding="utf-8") as handle:
                data = json.load(handle)
            return data.get("record") if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def get(self, sid: str) -> dict | None:
        if sid in self._deleted:
            return None
        if sid not in self._loaded:
            record = self._read(sid)
            self._loaded[sid] = (record, json.dumps(record, sort_keys=True) if record is not None else None)
        return self._loaded[sid][0]

    def put(self, sid: str, record: dict) -> None:
        self._deleted.discard(sid)
        self._loaded[sid] = (record, None)

    def delete(self, sid: str) -> None:
        self._deleted.add(sid)
        self._loaded.pop(sid, None)

    def ids(self) -> list[str]:
        found = set()
        try:
            names = os.listdir(self._store.root)
        except OSError:
            names = []
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self._store.root, name), encoding="utf-8") as handle:
                    sid = json.load(handle).get("sid")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(sid, str) and sid not in self._deleted:
                found.add(sid)
        found.update(s for s, (r, _) in self._loaded.items() if r is not None)
        return sorted(found - self._deleted)

    def idle_since(self, sid: str) -> float:
        record = self.get(sid)
        return float((record or {}).get("touched", 0.0))

    def flush(self) -> None:
        os.makedirs(self._store.root, exist_ok=True)
        for sid in self._deleted:
            with contextlib.suppress(OSError):
                os.remove(self._store.path_of(sid))
        for sid, (record, snapshot) in self._loaded.items():
            if record is None:
                continue
            if snapshot is not None and json.dumps(record, sort_keys=True) == snapshot:
                continue
            path = self._store.path_of(sid)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"sid": sid, "record": record}, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
