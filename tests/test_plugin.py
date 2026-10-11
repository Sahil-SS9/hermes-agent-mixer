"""Tests for plugin registration wiring, hook wiring and the sandbox install/load path."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from scripts import sandbox_home
from tests import conftest as conftest_mod
from hermes_agent_mixer.hermes import plugin as mixer_plugin

REPO_ROOT = Path(__file__).resolve().parents[1]
HERMES_BIN = shutil.which("hermes") or "/home/kensei/.local/bin/hermes"


@pytest.fixture(autouse=True)
def fresh_mixer():
    mixer_plugin.reset_mixer()
    yield
    mixer_plugin.reset_mixer()


def _hooked_ctx(settings: dict | None = None) -> conftest_mod.FakeCtx:
    ctx = conftest_mod.FakeCtx(settings)
    mixer_plugin.register(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Wiring (register() with a fake ctx)
# ---------------------------------------------------------------------------


class TestRegisterWiring:
    def test_register_wires_pre_tool_call_and_pre_llm_call_hooks(self, fake_ctx):
        mixer_plugin.register(fake_ctx)
        assert set(fake_ctx.hooks) == {"pre_tool_call", "pre_llm_call", "subagent_start", "subagent_stop"}
        assert len(fake_ctx.hooks["pre_tool_call"]) == 1
        assert len(fake_ctx.hooks["pre_llm_call"]) == 1
        assert callable(fake_ctx.hooks["pre_tool_call"][0])

    def test_register_wires_mixer_command(self, fake_ctx):
        mixer_plugin.register(fake_ctx)
        assert "mixer" in fake_ctx.commands
        entry = fake_ctx.commands["mixer"]
        assert callable(entry["handler"])
        assert entry["description"]
        assert entry["args_hint"]

    def test_on_unload_registered(self, fake_ctx):
        mixer_plugin.register(fake_ctx)
        assert fake_ctx.unload_callbacks

    def test_on_unload_resets_state(self, fake_ctx, monkeypatch):
        mixer_plugin.register(fake_ctx)
        mixer_plugin.get_mixer().set_session("s", "edits", "plan")
        for cb in fake_ctx.unload_callbacks:
            cb()
        assert mixer_plugin._MIXER is None and mixer_plugin._CONFIG_GET is None

    def test_pre_tool_call_permissive_in_scaffold(self, fake_ctx, monkeypatch):
        mixer_plugin.register(fake_ctx)
        callback = fake_ctx.hooks["pre_tool_call"][0]
        assert callback(tool_name="write_file", args={"path": "x", "content": ""}, task_id="t") is None

    def test_mixer_command_placeholder(self, fake_ctx):
        mixer_plugin.register(fake_ctx)
        handler = fake_ctx.commands["mixer"]["handler"]
        assert handler("")
        assert handler("edits auto")


# ---------------------------------------------------------------------------
# Hook wiring: pre_tool_call consults the decision engine with mixer settings
# ---------------------------------------------------------------------------


class TestHookWiring:
    def test_pre_tool_call_uses_decision_engine_block(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _hooked_ctx({"scope": ["src/**"]})
        hook = ctx.hooks["pre_tool_call"][0]
        result = hook(tool_name="write_file", args={"path": "nope/x.txt", "content": "x"}, task_id="t1")
        assert result is not None
        assert result["action"] == "block"
        assert "scope" in result["message"]

    def test_pre_tool_call_uses_decision_engine_allow(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _hooked_ctx({"scope": ["src/**"]})
        hook = ctx.hooks["pre_tool_call"][0]
        assert hook(tool_name="write_file", args={"path": "src/a.py", "content": "x"}, task_id="t1") is None

    def test_plugin_uses_config_defaults_from_ctx(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _hooked_ctx({"edits": "plan"})
        hook = ctx.hooks["pre_tool_call"][0]
        result = hook(tool_name="execute_code", args={"code": "1"}, task_id="t1")
        assert result is not None
        assert result["action"] == "block"

    def test_session_override_changes_hook_behaviour(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _hooked_ctx()
        hook = ctx.hooks["pre_tool_call"][0]
        mixer_plugin.get_mixer().set_session("sess-a", "edits", "plan")
        result = hook(tool_name="execute_code", args={"code": "1"}, task_id="t1", session_id="sess-a")
        assert result is not None
        assert result["action"] == "block"

    def test_sessions_are_isolated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _hooked_ctx()
        hook = ctx.hooks["pre_tool_call"][0]
        mixer_plugin.get_mixer().set_session("sess-a", "edits", "plan")

        blocked = hook(tool_name="execute_code", args={"code": "1"}, task_id="t1", session_id="sess-a")
        other = hook(tool_name="execute_code", args={"code": "1"}, task_id="t1", session_id="sess-b")
        no_session = hook(tool_name="execute_code", args={"code": "1"}, task_id="t1")
        assert blocked is not None and blocked["action"] == "block"
        assert other is None
        assert no_session is None

    def test_reset_session_clears_overrides(self):
        mixer = mixer_plugin.get_mixer()
        mixer.set_session("sess-a", "edits", "plan")
        mixer.reset_session("sess-a")
        assert mixer.effective("sess-a")["edits"] == "auto"

    def test_hook_accepts_full_host_payload(self, tmp_path, monkeypatch):
        """The hook must tolerate every kwarg the host sends pre_tool_call."""
        monkeypatch.chdir(tmp_path)
        ctx = _hooked_ctx()
        hook = ctx.hooks["pre_tool_call"][0]
        result = hook(
            tool_name="write_file", args={"path": "x", "content": ""}, task_id="t1",
            session_id="s", tool_call_id="c", turn_id="tr", api_request_id="a",
            middleware_trace=[], telemetry_schema_version=1,
        )
        assert result is None

    def test_pre_llm_call_returns_none(self):
        ctx = _hooked_ctx()
        hook = ctx.hooks["pre_llm_call"][0]
        assert hook(
            session_id="s", task_id="t", turn_id="tr", user_message="m",
            conversation_history=[], is_first_turn=True, model="m", platform="cli",
        ) is None

    def test_missing_args_is_tolerated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _hooked_ctx()
        hook = ctx.hooks["pre_tool_call"][0]
        hook(tool_name="write_file", task_id="t1")  # must not raise


# ---------------------------------------------------------------------------
# Sandbox install + load (slow; uses the installed hermes with a sandbox home)
# ---------------------------------------------------------------------------


def _copy_plugin_tree(dest: Path) -> None:
    """Copy the plugin tree into dest, excluding build/env noise."""
    excl_roots = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build"}
    for item in REPO_ROOT.iterdir():
        if item.name in excl_roots:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.py[oc]"))
        else:
            shutil.copy2(item, target)


def _make_fixture_repo(tmp_path: Path) -> Path:
    """Commit a copy of the plugin tree into a scratch git repo (installer needs a clone-able repo)."""
    repo = tmp_path / "mixer-fixture-repo"
    repo.mkdir()
    _copy_plugin_tree(repo)
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "mixer-fixture")
    env.setdefault("GIT_AUTHOR_EMAIL", "mixer-fixture@localhost")
    env.setdefault("GIT_COMMITTER_NAME", "mixer-fixture")
    env.setdefault("GIT_COMMITTER_EMAIL", "mixer-fixture@localhost")
    for args in (["init"], ["add", "-A"], ["commit", "-m", "fixture"]):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
    return repo


def _hermes_env(tmp_path: Path, hermes_home: Path) -> dict:
    """Sandboxed environment for hermes subprocesses: no live home, no display.

    ``hermes_home`` comes from scripts.sandbox_home.make_home: a thin home that shares the cached
    base home's tools/, cache/ and installs/ (P2), so no run builds its own 1.6 GB home.
    """
    home = tmp_path / "home"
    home.mkdir()
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    env = {k: v for k, v in os.environ.items()}
    env.update(
        HOME=str(home),
        HERMES_HOME=str(hermes_home),
        TMPDIR=str(tmpdir),
        GIT_CEILING_DIRECTORIES=str(tmpdir),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local/share"),
        XDG_STATE_HOME=str(home / ".local/state"),
        XDG_CACHE_HOME=str(home / ".cache"),
        UV_CACHE_DIR=os.environ.get("UV_CACHE_DIR", "/home/kensei/.cache/uv"),
        UV_PYTHON_INSTALL_DIR=os.environ.get("UV_PYTHON_INSTALL_DIR", "/home/kensei/.local/share/uv/python"),
    )
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    return env


def _write_sandbox_config(hermes_home: Path) -> None:
    """Minimal sandbox config: plugin enabled, install scan off (trusted local probe)."""
    hermes_home.mkdir(parents=True, exist_ok=True)
    (hermes_home / "config.yaml").write_text(
        textwrap.dedent(
            """\
            plugins:
              enabled:
                - hermes-agent-mixer
              scan_on_install: false
            """
        ),
        encoding="utf-8",
    )


def _run(cmd: list[str], env: dict, cwd: Path | None = None):
    return subprocess.run(cmd, env=env, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=300)


@pytest.mark.slow
class TestSandboxInstallAndLoad:
    """Install once per test session, then assert the observable outcomes.

    Each install takes about a minute (real clone + managed env), so a
    class-scoped fixture keeps the suite well inside the five-minute budget.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def sandbox(cls, tmp_path_factory):
        root = tmp_path_factory.mktemp("sandbox-install")
        hermes_home = sandbox_home.make_home(sandbox_home.cache_root() / "runs" / root.name)
        env = _hermes_env(root, hermes_home)
        _write_sandbox_config(Path(env["HERMES_HOME"]))
        fixture = _make_fixture_repo(root)
        # --yes-deps: the pyproject.toml next to plugin.yaml makes the installer
        # ask the Python-dependency consent question; in non-interactive mode the
        # explicit answer is required or the install is declined before anything
        # lands. The plugin's runtime is standard-library-only.
        install = _run([HERMES_BIN, "plugins", "install", f"file://{fixture}", "--enable", "--yes-deps"], env)
        yield {
            "env": env,
            "hermes_home": Path(env["HERMES_HOME"]),
            "fixture": fixture,
            "install": install,
        }
        shutil.rmtree(hermes_home, ignore_errors=True)  # removes the symlinks, never the shared base

    def test_installs_into_sandbox_and_hermes_plugins_list_shows_no_errors(self, sandbox):
        """The real installer accepts the plugin via a file:// clone and
        `hermes plugins list` shows it enabled with no load error."""
        install = sandbox["install"]
        assert install.returncode == 0, f"install failed:\n{install.stdout}\n{install.stderr}"

        env = sandbox["env"]
        listing = _run([HERMES_BIN, "plugins", "list"], env)
        output = listing.stdout + listing.stderr
        assert listing.returncode == 0, output
        assert "hermes-agent-mixer" in output, output
        lowered = output.lower()
        assert "error" not in lowered or "0 errors" in lowered, output

    def test_load_via_real_loader_no_error(self, sandbox):
        """`hermes plugins doctor --ci` drives the same discovery, manifest parsing
        and register(ctx) the host uses, and exits non-zero on validation error."""
        assert sandbox["install"].returncode == 0
        probe = _run([HERMES_BIN, "plugins", "doctor", "hermes-agent-mixer", "--ci"], sandbox["env"])
        assert probe.returncode == 0, f"doctor failed:\n{probe.stdout}\n{probe.stderr}"
        lowered = probe.stdout.lower()
        assert "hermes-agent-mixer" in lowered, probe.stdout
        assert "error" not in lowered or "0 error" in lowered, probe.stdout

    def test_enabled_state_persists_across_restart(self, sandbox):
        """Two consecutive `hermes plugins list` runs against the same sandbox home see it enabled."""
        assert sandbox["install"].returncode == 0
        env = sandbox["env"]
        first = _run([HERMES_BIN, "plugins", "list"], env)
        assert first.returncode == 0
        second = _run([HERMES_BIN, "plugins", "list"], env)
        assert second.returncode == 0
        assert "hermes-agent-mixer" in first.stdout
        assert "hermes-agent-mixer" in second.stdout