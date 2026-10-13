"""Shared Hermes session storage; CLI harness storage remains independent."""
from __future__ import annotations

from pathlib import Path

from . import host
from ..core.store import FileStore


def state_store() -> FileStore:
    home = host.hermes_home()
    if home is None:
        raise RuntimeError("Hermes home is unavailable; refusing to use a separate panel store")
    return FileStore(Path(home) / "plugin-data" / "hermes-agent-mixer" / "sessions", strict=True)


def config_context():
    """Use the host's public namespaced facade, including its managed-config guards.

    This context is used only for config access. No plugins are loaded or hooks
    registered by the API process.
    """
    from hermes_cli.plugins import PluginContext, PluginManifest, PluginManager

    return PluginContext(PluginManifest(name="hermes-agent-mixer"), PluginManager())
