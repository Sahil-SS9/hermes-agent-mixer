"""Run the agent-mixer CLI and its hooks in-process against a throwaway home (no real config touched)."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from hermes_agent_mixer import cli


class Rig:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.proj = root / "proj"
        (self.proj / "src").mkdir(parents=True)
        (self.proj / "src" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        self.env = {
            "HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "config"), "XDG_STATE_HOME": str(root / "state"),
            "XDG_DATA_HOME": str(root / "data"), "XDG_CACHE_HOME": str(root / "cache"), "PATH": "/usr/bin:/bin",
        }
        for value in self.env.values():
            if value != self.env["PATH"]:
                Path(value).mkdir(parents=True, exist_ok=True)

    @property
    def state_dir(self) -> Path:
        return self.root / "state" / "agent-mixer"

    @property
    def settings_file(self) -> Path:
        return self.root / "config" / "agent-mixer" / "settings.json"

    def run(self, argv, stdin: str = "", cwd: Path | None = None, extra_env: dict | None = None):
        out, err = io.StringIO(), io.StringIO()
        env = {**self.env, **(extra_env or {})}
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(list(argv), stdin=stdin, env=env, cwd=str(cwd or self.proj))
        return rc, out.getvalue(), err.getvalue()

    def hook(self, harness: str, payload, cwd: Path | None = None, extra_env: dict | None = None):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        rc, out, err = self.run(["hook", harness], raw, cwd, extra_env)
        data = json.loads(out) if out.strip() else None
        return rc, data, err

