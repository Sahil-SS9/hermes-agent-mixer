"""The session store (X3): one store-wide lock, atomic replace, idle pruning."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from hermes_agent_mixer.core.store import FileStore, MemoryStore, StoreLockTimeout


def test_file_store_round_trips_a_record(tmp_path):
    store = FileStore(tmp_path / "state")
    with store.transaction() as tx:
        tx.put("s1", {"touched": 1.0, "n": 1})
    with store.transaction() as tx:
        record = tx.get("s1")
        assert record == {"touched": 1.0, "n": 1}
        record["n"] = 2
    with store.transaction() as tx:
        assert tx.get("s1")["n"] == 2
        assert tx.ids() == ["s1"]


def test_the_lock_is_one_fixed_file_that_is_never_replaced(tmp_path):
    store = FileStore(tmp_path / "state")
    with store.transaction() as tx:
        tx.put("a", {"touched": 1.0})
    first = os.stat(tmp_path / "state" / ".lock").st_ino
    for i in range(5):
        with store.transaction() as tx:
            tx.put(f"s{i}", {"touched": float(i)})
    assert os.stat(tmp_path / "state" / ".lock").st_ino == first


def test_a_held_lock_makes_transactions_wait_then_fail_closed(tmp_path):
    store = FileStore(tmp_path / "state", lock_wait=0.3)
    (tmp_path / "state").mkdir()
    with open(tmp_path / "state" / ".lock", "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        started = time.monotonic()
        with pytest.raises(StoreLockTimeout):
            with store.transaction():
                pass
        assert time.monotonic() - started >= 0.25


def test_a_waiting_transaction_proceeds_when_the_lock_is_released(tmp_path):
    store = FileStore(tmp_path / "state", lock_wait=3)
    (tmp_path / "state").mkdir()
    held = open(tmp_path / "state" / ".lock", "a+")
    fcntl.flock(held, fcntl.LOCK_EX)
    threading.Timer(0.3, lambda: (fcntl.flock(held, fcntl.LOCK_UN), held.close())).start()
    with store.transaction() as tx:
        tx.put("late", {"touched": 1.0})
    with store.transaction() as tx:
        assert tx.get("late") is not None


def test_parallel_processes_never_lose_an_update(tmp_path):
    state = tmp_path / "state"
    script = (
        "import sys\n"
        "from hermes_agent_mixer.core.store import FileStore\n"
        "store = FileStore(sys.argv[1])\n"
        "for _ in range(25):\n"
        "    with store.transaction() as tx:\n"
        "        rec = tx.get('counter') or {'touched': 1.0, 'n': 0}\n"
        "        rec['n'] += 1\n"
        "        tx.put('counter', rec)\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", script, str(state)]) for _ in range(6)]
    assert all(p.wait(timeout=60) == 0 for p in procs)
    with FileStore(state).transaction() as tx:
        assert tx.get("counter")["n"] == 150


def test_state_files_are_replaced_atomically_and_leave_no_temp_files(tmp_path):
    store = FileStore(tmp_path / "state")
    for i in range(10):
        with store.transaction() as tx:
            tx.put("s", {"touched": 1.0, "n": i})
    names = os.listdir(tmp_path / "state")
    assert not [n for n in names if n.endswith(".tmp")]
    data = json.loads((tmp_path / "state" / next(n for n in names if n.endswith(".json"))).read_text())
    assert data["sid"] == "s" and data["record"]["n"] == 9


def test_idle_sessions_are_pruned_after_seven_days(tmp_path):
    store = FileStore(tmp_path / "state")
    day = 86400.0
    with store.transaction() as tx:
        tx.put("old", {"touched": 0.0})
        tx.put("new", {"touched": 9 * day})
    with store.transaction() as tx:
        dropped = tx.prune(10 * day, 7 * day, 1000)
    assert dropped == ["old"]
    with store.transaction() as tx:
        assert tx.ids() == ["new"]


def test_the_oldest_sessions_go_first_beyond_the_cap():
    store = MemoryStore()
    with store.transaction() as tx:
        for i in range(10):
            tx.put(f"s{i}", {"touched": float(i)})
        tx.prune(10.0, 1e9, 4)
        assert sorted(tx.ids()) == ["s6", "s7", "s8", "s9"]


def test_a_corrupt_state_file_reads_as_a_missing_session(tmp_path):
    store = FileStore(tmp_path / "state")
    with store.transaction() as tx:
        tx.put("s", {"touched": 1.0})
    path = store.path_of("s")
    with open(path, "w") as handle:
        handle.write("{not json")
    with store.transaction() as tx:
        assert tx.get("s") is None
        assert tx.ids() == []
