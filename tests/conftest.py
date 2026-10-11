"""Shared test fixtures for Agent Mixer tests."""

from __future__ import annotations

import pytest


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
        }

    def get_config(self, key, default=None):
        return self._settings.get(key, default)

    def set_config(self, key, value):
        self._settings[key] = value

    def on_unload(self, callback):
        self.unload_callbacks.append(callback)


@pytest.fixture
def fake_ctx():
    return FakeCtx()