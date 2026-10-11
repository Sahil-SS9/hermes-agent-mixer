"""Saved-default schema fidelity: what /mixer save writes is what the host accepts.

The manifest must declare a schema that matches the plugin's own saved shapes,
or ctx.set_config emits host warnings and a declared-but-wrong schema silently
blocks the Desktop/TUI settings surface (plugins_manifest.validate_config_schema).
"""
from __future__ import annotations

from pathlib import Path

from hermes_agent_mixer import board, manifest
from hermes_agent_mixer.mixer import Mixer


def _manifest_spec():
    return manifest.loads((Path(__file__).resolve().parents[1] / "plugin.yaml").read_text())["config_schema"]


_HOST_TYPES = {"str": str, "int": int, "float": float, "bool": bool,
               "list": list, "dict": dict, "secret": str}


def test_save_matches_declared_config_schema(tmp_path):
    mixer = Mixer()
    for command in ("edits ask", "scope add src/**", "lines 120", "deps block"):
        board.handle_command(command, mixer, "s")
    saved: dict = {}
    board.handle_command("save", mixer, "s", save=lambda key, value: saved.__setitem__(key, value))
    for name, spec in _manifest_spec().items():
        declared = str(spec["type"]).strip().lower()
        value = saved[name]
        expected = _HOST_TYPES[declared]
        assert isinstance(value, expected), (name, declared, type(value).__name__)
        if declared == "int":
            assert not isinstance(value, bool), name


def test_manifest_normalised_default_matches_the_declared_schema():
    from hermes_agent_mixer import settings
    defaults = settings.defaults()
    for name, spec in _manifest_spec().items():
        declared = str(spec["type"]).strip().lower()
        if name == "lines":
            # Optional budget: unset/off and any positive number are both valid.
            assert defaults[name] == "off" or isinstance(defaults[name], int)
            continue
        assert isinstance(defaults[name], _HOST_TYPES[declared]), (name, declared)
        if "default" in spec and declared not in ("list", "dict"):
            # list/dict defaults may be mutable representations; scalar defaults must agree.
            assert defaults[name] == spec["default"], name