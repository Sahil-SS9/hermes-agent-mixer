"""Black-box checks that operator receipts cannot turn command failures into PASS.

The fake executable is an explicitly labelled test double, never delivery evidence.
Final install and E2E receipts must be generated using the real installed Hermes.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script,stage", [
    ("sandbox_install_load_check.sh", "install"),
    ("sandbox_install_load_check.sh", "doctor"),
    ("e2e_run.sh", "install"),
    ("e2e_run.sh", "chat"),
    ("e2e_run.sh", "missing-block-receipt"),
])
def test_receipt_runner_fails_closed(tmp_path, script, stage):
    fake = tmp_path / "fake-hermes"
    fake.write_text('''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
stage = os.environ["FIXTURE_FAILURE"]
if args == ["--version"]:
    print("FIXTURE ONLY VERSION")
elif args[:2] == ["plugins", "install"]:
    sys.exit(7 if stage == "install" else 0)
elif args[:2] == ["plugins", "list"]:
    print("hermes-agent-mixer enabled FIXTURE ONLY")
elif args[:2] == ["plugins", "doctor"]:
    print("0 errors FIXTURE ONLY")
    sys.exit(8 if stage == "doctor" else 0)
elif args[:1] == ["chat"]:
    # A transcript claim is not the host's actual write_file error receipt.
    print("blocked by mixer:scope FIXTURE ONLY")
    sys.exit(9 if stage == "chat" else 0)
''', encoding="utf-8")
    fake.chmod(0o700)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    env = {**os.environ, "HERMES_BIN": str(fake), "FIXTURE_FAILURE": stage}
    result = subprocess.run(["bash", str(REPO / "scripts" / script), str(evidence)],
        env=env, cwd=REPO, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, f"failed {stage} was reported as success:\n{result.stdout}\n{result.stderr}"
    log = evidence / ("e2e.log" if script == "e2e_run.sh" else "plugin-load.log")
    assert log.exists()
    assert "E2E PASS" not in log.read_text() and "INSTALL PASS" not in log.read_text()


@pytest.mark.parametrize("timing", ["", " (0.01s)"])
def test_e2e_accepts_only_real_host_block_log_with_optional_timing(tmp_path, timing):
    fake = tmp_path / "fake-hermes"
    fake.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
if args == ["--version"]:
    print("FIXTURE ONLY VERSION")
elif args[:2] == ["plugins", "list"]:
    print("hermes-agent-mixer enabled FIXTURE ONLY")
elif args[:1] == ["chat"]:
    log = Path(os.environ["HERMES_HOME"]) / "logs" / "agent.log"
    log.parent.mkdir()
    log.write_text('WARNING agent.tool_executor: Tool write_file returned error'
        + os.environ["FIXTURE_TIMING"] + ': {"error": "blocked by mixer:scope FIXTURE ONLY"}\\n')
''', encoding="utf-8")
    fake.chmod(0o700)
    evidence = tmp_path / "evidence"
    env = {**os.environ, "HERMES_BIN": str(fake), "FIXTURE_TIMING": timing}
    result = subprocess.run(["bash", str(REPO / "scripts" / "e2e_run.sh"), str(evidence)],
        env=env, cwd=REPO, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert (evidence / "e2e.log").read_text().splitlines()[-1] == "E2E PASS"


def test_e2e_overrides_inherited_terminal_cwd(tmp_path):
    fake = tmp_path / "fake-hermes"
    fake.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
if args == ["--version"]:
    print("FIXTURE ONLY VERSION")
elif args[:2] == ["plugins", "list"]:
    print("hermes-agent-mixer enabled FIXTURE ONLY")
elif args[:1] == ["chat"]:
    project = Path(os.environ["HERMES_HOME"]).parent / "project"
    assert os.environ.get("TERMINAL_CWD") == str(project), "inherited cwd escaped the sandbox"
    log = Path(os.environ["HERMES_HOME"]) / "logs" / "agent.log"
    log.parent.mkdir()
    log.write_text('Tool write_file returned error: {"error": "blocked by mixer:scope FIXTURE ONLY"}\\n')
''', encoding="utf-8")
    fake.chmod(0o700)
    evidence = tmp_path / "evidence"
    env = {**os.environ, "HERMES_BIN": str(fake), "TERMINAL_CWD": str(tmp_path / "unrelated")}
    result = subprocess.run(["bash", str(REPO / "scripts" / "e2e_run.sh"), str(evidence)],
        env=env, cwd=REPO, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (result.stdout, result.stderr)
