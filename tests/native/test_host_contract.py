"""Real-host contract: loads Mixer through the real Hermes plugin loader and drives the real hook dispatch.

Marked ``native``. Skipped with a clear reason unless ``MIXER_NATIVE_PYTHON`` points at the sandbox
Hermes interpreter (the ``hermes`` launcher, which runs Hermes' own Python with its managed
environment). The plugin and config are installed fresh per run into a thin home that shares the
cached base home's tools/, cache/ and installs/ (P2). The actual checks run inside Hermes in
``host_driver.py``; this file builds the sandbox, runs it and reports
``NATIVE HOST PASS <surface> <short sha>`` for cli, tui, gateway and subagent.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from scripts import sandbox_home
from tests import test_plugin

pytestmark = pytest.mark.native

REPO = Path(__file__).resolve().parents[2]
NATIVE = os.environ.get("MIXER_NATIVE_PYTHON", "")
SURFACES = ("cli", "tui", "gateway", "subagent")

if not NATIVE or not Path(NATIVE).exists():
    pytest.skip("native host test: set MIXER_NATIVE_PYTHON to the sandbox Hermes interpreter "
                "(the `hermes` launcher) to run it against the real plugin loader", allow_module_level=True)


def _sha() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    root = tmp_path_factory.mktemp("native")
    home = sandbox_home.make_home(sandbox_home.cache_root() / "runs" / f"native-{uuid.uuid4().hex[:8]}")
    project = root / "project"
    (project / "src").mkdir(parents=True)
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - hermes-agent-mixer\n  scan_on_install: false\n",
                                      encoding="utf-8")
    user = root / "home"
    user.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.endswith(("_API_KEY", "_TOKEN", "_SECRET"))}
    env.update(HOME=str(user), HERMES_HOME=str(home), TMPDIR=str(root / "tmp"), TERMINAL_CWD=str(project),
               GIT_CEILING_DIRECTORIES=str(root), XDG_CONFIG_HOME=str(user / ".config"),
               XDG_STATE_HOME=str(user / ".local/state"), XDG_DATA_HOME=str(user / ".local/share"),
               XDG_CACHE_HOME=str(user / ".cache"), MIXER_REPO_SHA=_sha(), PYTHONDONTWRITEBYTECODE="1")
    (root / "tmp").mkdir()
    for var in ("DISPLAY", "WAYLAND_DISPLAY", "HERMES_SESSION_ID", "HERMES_SESSION_KEY"):
        env.pop(var, None)
    # Install the plugin with the real installer (a file:// clone), exactly as users do; only the plugin and
    # the config are new in this home.
    fixture = test_plugin._make_fixture_repo(root)
    installed = subprocess.run([NATIVE, "plugins", "install", f"file://{fixture}", "--enable", "--yes-deps"],
                               cwd=home, env=env, capture_output=True, text=True, timeout=600)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    # The gateway's systemd WorkingDirectory is HERMES_HOME, so run there: only the workspace root decides.
    done = subprocess.run([NATIVE, "--run-module", "unittest", "discover", "-s", str(Path(__file__).parent),
                           "-p", "host_driver.py", "-v"], cwd=home, env=env, capture_output=True, text=True,
                          timeout=600)
    output = done.stdout + done.stderr
    yield done, output
    shutil.rmtree(home, ignore_errors=True)  # removes the symlinks, never the shared base


def test_the_real_loader_loads_the_plugin_and_every_surface_passes(host):
    done, output = host
    assert done.returncode == 0, output[-3000:]
    assert "should be" not in output, "a settings-schema warning survived: " + output[-1500:]
    sha = _sha()
    for surface in SURFACES:
        line = f"NATIVE HOST PASS {surface} {sha}"
        assert line in output, f"missing {line!r}:\n{output[-2000:]}"
        print(line)
    log = os.environ.get("MIXER_NATIVE_LOG")
    if log:
        with open(log, "w", encoding="utf-8") as handle:
            handle.write("".join(f"NATIVE HOST PASS {s} {sha}\n" for s in SURFACES))
            handle.write(output)


def test_the_settings_round_trip_uses_the_real_config_writer(host):
    done, output = host
    assert f"NATIVE HOST PASS settings {_sha()}" in output, output[-2000:]
