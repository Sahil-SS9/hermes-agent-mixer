"""Shared test fixtures for Agent Mixer tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SHIM = Path(__file__).resolve().parent / "upstream_shim"
SHIM_PACKAGES = ("gateway", "tools", "agent")


class FakeCtx:
    """Minimal stand-in for the Hermes PluginContext.

    Records every registration and supports plugin-relative get/set_config
    the way the host does (a flat mapping of knob key -> value).
    """

    def __init__(self, settings: dict | None = None):
        self.hooks: dict[str, list] = {}
        self.commands: dict[str, dict] = {}
        self.unload_callbacks: list = []
        self._settings: dict = dict(settings or {})

    def register_hook(self, hook_name, callback):
        self.hooks.setdefault(hook_name, []).append(callback)

    def register_command(self, name, handler, description="", args_hint="", **kwargs):
        if name in self.commands:
            raise ValueError("conflict")
        self.commands[name] = {
            "handler": handler,
            "description": description,
            "args_hint": args_hint,
            **kwargs,
        }

    def get_config(self, key, default=None):
        return self._settings.get(key, default)

    def set_config(self, key, value):
        self._settings[key] = value

    def on_unload(self, callback):
        self.unload_callbacks.append(callback)


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch):
    """No test may inherit a host workspace or session from the shell that runs pytest."""
    for var in ("TERMINAL_CWD", "HERMES_SESSION_ID", "HERMES_SESSION_KEY", "AGENT_MIXER_HOME"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def fake_ctx():
    return FakeCtx()


def _purge_shim_modules() -> None:
    for name in list(sys.modules):
        if name.split(".")[0] in SHIM_PACKAGES:
            del sys.modules[name]


@pytest.fixture
def host_shim(monkeypatch):
    """Verbatim upstream Hermes host modules (tests/upstream_shim) on sys.path for one test."""
    from hermes_agent_mixer.hermes import host

    _purge_shim_modules()
    monkeypatch.syspath_prepend(str(SHIM))
    host.reset_cache()
    yield SHIM
    _purge_shim_modules()
    host.reset_cache()


@pytest.fixture
def no_host(monkeypatch):
    """No Hermes host modules at all: every guarded import in hermes/host.py falls back."""
    from hermes_agent_mixer.hermes import host

    _purge_shim_modules()
    host.reset_cache()
    monkeypatch.setattr(host, "_import", lambda _name: None)
    yield
    host.reset_cache()


@pytest.fixture
def fresh_plugin():
    """Registers the Hermes adapter on a new FakeCtx and returns ``new(settings) -> ctx``."""
    from hermes_agent_mixer.hermes import plugin

    def new(settings: dict | None = None) -> FakeCtx:
        plugin.reset_mixer()
        ctx = FakeCtx(settings)
        plugin.register(ctx)
        return ctx

    yield new
    plugin.reset_mixer()
