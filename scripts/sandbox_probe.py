"""Checked sandbox install/E2E receipts. All writes stay in the evidence dir.

Uses the real installed Hermes by default. It never removes an old sandbox,
never changes the live profile, and never treats transcript prose as a block
receipt. Tests use an explicitly labelled fake executable only for failure paths.
"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
NAME = "hermes-agent-mixer"
BASE_URL = "http://127.0.0.1:8091/v1"


def run_receipt(mode: str, evidence: Path) -> None:
    evidence = evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix=f"{mode}-", dir=evidence))
    home, hermes_home, tmp, project = (sandbox / name for name in ("home", "hermes-home", "tmp", "project"))
    for folder in (home, hermes_home, tmp, project / "src"):
        folder.mkdir(parents=True, exist_ok=True)
    # Retain non-secret runtime/process settings but prevent accidental provider
    # or platform credential inheritance in the disposable CLI.
    env = {key: value for key, value in os.environ.items()
           if not key.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))}
    env.update(HOME=str(home), HERMES_HOME=str(hermes_home), TMPDIR=str(tmp),
               GIT_CEILING_DIRECTORIES=str(tmp), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local/share"), XDG_STATE_HOME=str(home / ".local/state"),
               XDG_CACHE_HOME=str(home / ".cache"), PYTHONDONTWRITEBYTECODE="1")
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    hermes = os.environ.get("HERMES_BIN", "/home/kensei/.local/bin/hermes")
    log = evidence / ("e2e.log" if mode == "e2e" else "plugin-load.log")
    if log.exists():
        prior = log.read_bytes()
        (sandbox / "previous-receipt.log").write_bytes(prior)
    log.write_text(f"# Agent Mixer {mode} receipt {datetime.now().astimezone().isoformat()}\n"
                   f"# repo: {REPO}\n# sandbox: {sandbox}\n", encoding="utf-8")

    def append(text: str) -> None:
        with log.open("a", encoding="utf-8") as stream:
            stream.write(text)

    def command(*args: str, cwd: Path = REPO) -> str:
        argv = [hermes, *args]
        append(f"\n## {shlex.join(argv)}\n")
        try:
            result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
        except (OSError, subprocess.TimeoutExpired) as exc:
            append(f"COMMAND FAIL: {exc}\n")
            raise SystemExit(1) from exc
        output = result.stdout + result.stderr
        append(output + f"\nexit={result.returncode}\n")
        if result.returncode:
            raise SystemExit(result.returncode)
        return output

    config = "plugins:\n  enabled: [hermes-agent-mixer]\n  scan_on_install: false\n"
    if mode == "e2e":
        config = (f"model:\n  provider: custom\n  default: auto\n  base_url: {BASE_URL}\n"
                  "  api_key: local-only\n" + config +
                  "  entries:\n    hermes-agent-mixer:\n      settings:\n"
                  "        edits: auto\n        scope: ['src/**']\n        lines: off\n        deps: ask\n"
                  "memory:\n  memory_enabled: false\n  user_profile_enabled: false\n")
        env.update(OPENAI_BASE_URL=BASE_URL, OPENAI_API_KEY="local-only")
        append(f"# Only model route: {BASE_URL}, model auto\n")
    (hermes_home / "config.yaml").write_text(config, encoding="utf-8")
    version = command("--version")
    (evidence / "hermes-version.txt").write_text(version, encoding="utf-8")
    command("plugins", "install", REPO.as_uri(), "--enable", "--yes-deps")
    listing = command("plugins", "list")
    if not any(NAME in line and "enabled" in line for line in listing.splitlines()):
        append("INSTALL FAIL: list did not show Mixer enabled\n")
        raise SystemExit(1)
    command("plugins", "doctor", NAME, "--ci")

    if mode == "install":
        append("INSTALL PASS\n")
    else:
        command("chat", "-q", "Create notes.txt in the project root containing hi",
                "--provider", "custom", "--model", "auto", "--max-turns", "6", cwd=project)
        agent_log = hermes_home / "logs" / "agent.log"
        lines = agent_log.read_text(encoding="utf-8", errors="replace").splitlines() if agent_log.exists() else []
        receipts = [line for line in lines if "Tool write_file returned error:" in line
                    and "blocked by mixer:scope" in line]
        append("\n## Actual host tool error delivered to the model\n" + "\n".join(receipts) + "\n")
        if not receipts:
            append("E2E FAIL: no real write_file scope-block receipt\n")
            raise SystemExit(1)
        note = project / "notes.txt"
        if note.exists():
            append(f"Documented terminal workaround: notes.txt exists, content={note.read_text()!r}\n")
        else:
            append("notes.txt absent after run\n")
        append("E2E PASS\n")
    print(f"{mode} receipt: {log}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("install", "e2e"):
        raise SystemExit("usage: sandbox_probe.py install|e2e <evidence-dir>")
    run_receipt(sys.argv[1], Path(sys.argv[2]))
