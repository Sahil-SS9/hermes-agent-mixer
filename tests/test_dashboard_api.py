"""Dashboard backend tests: the router handlers must behave exactly like the CLI (same store,
same grammar). Runs against a throwaway home via the tests.cli_driver rig."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def api_module(monkeypatch, tmp_path):
    """Import dashboard/plugin_api.py the way the dashboard server does (by path), with a
    throwaway AGENT_MIXER_HOME so the real config is never touched."""
    repo = Path(__file__).resolve().parent.parent
    monkeypatch.setenv("AGENT_MIXER_HOME", str(tmp_path / "mixer-home"))
    (tmp_path / "mixer-home").mkdir(parents=True, exist_ok=True)
    if "dashboard.plugin_api" in sys.modules:
        del sys.modules["dashboard.plugin_api"]
    monkeypatch.syspath_prepend(str(repo / "dashboard"))
    import dashboard.plugin_api as api

    yield api
    sys.modules.pop("dashboard.plugin_api", None)


def _mkproj(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    return proj


def test_state_reports_defaults(api_module, tmp_path):
    proj = _mkproj(tmp_path)
    os.chdir(proj)
    data = api_module.get_state(session="D1", saved=False)
    assert data["session"] == "D1"
    assert data["dials"]["edits"]["value"] == "auto"
    assert data["dials"]["edits"]["source"] == "default"
    assert data["presets"] == ["auditor", "builder", "explorer", "surgical"]


def test_command_applies_and_state_follows(api_module, tmp_path):
    proj = _mkproj(tmp_path)
    os.chdir(proj)
    res = api_module.post_command(api_module.CommandBody(command="edits plan", session="D2"))
    assert res["ok"] and "plan" in res["reply"]
    assert res["state"]["dials"]["edits"]["value"] == "plan"
    # the same store the CLI reads
    _rc, out, _ = rig_run(tmp_path, ["--session", "D2", "board"])
    assert "plan" in out


def test_command_saved_targets_the_saved_file(api_module, tmp_path):
    proj = _mkproj(tmp_path)
    os.chdir(proj)
    res = api_module.post_command(api_module.CommandBody(command="lines 40", saved=True))
    assert res["ok"]
    saved = Path(os.environ["AGENT_MIXER_HOME"]) / "settings.json"
    assert json.loads(saved.read_text())["lines"] == 40
    assert res["state"]["saved_mode"] is True


def test_unknown_command_is_not_ok_but_does_not_crash(api_module, tmp_path):
    proj = _mkproj(tmp_path)
    os.chdir(proj)
    res = api_module.post_command(api_module.CommandBody(command="edits plna", session="D3"))
    assert res["ok"] is False and "unknown" in res["reply"].lower()
    assert res["state"]["dials"]["edits"]["value"] == "auto"


def test_refusal_returns_not_ok(api_module, tmp_path):
    proj = _mkproj(tmp_path)
    os.chdir(proj)
    # SavedTarget.reset refuses with a polite reply (the CLI behaviour); the API marks it not-ok
    res = api_module.post_command(api_module.CommandBody(command="reset", saved=True))
    assert res["ok"] is False and "reset only applies to a session" in res["reply"]


def test_session_required_unless_saved(api_module, tmp_path):
    proj = _mkproj(tmp_path)
    os.chdir(proj)
    with pytest.raises(api_module.HTTPException) as excinfo:
        api_module.post_command(api_module.CommandBody(command="edits plan"))
    assert excinfo.value.status_code == 400


def rig_run(tmp_path, argv):
    """Reuse the CLI runner so the assertion is against the real CLI, not our own code."""
    from tests.cli_driver import Rig

    rig = Rig(tmp_path / "rig-state")
    rc, out, err = rig.run(list(argv), cwd=str(tmp_path / "proj"))
    return rc, out or err, err


def test_backend_matches_cli_board(api_module, tmp_path, monkeypatch):
    """The dashboard /state and the CLI board must agree — the no-drift guarantee.
    Both sides pointed at the SAME AGENT_MIXER_HOME for this test."""
    monkeypatch.setenv("XDG_STATE_HOME", str(Path(os.environ["AGENT_MIXER_HOME"]).parent / "xdg-state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(Path(os.environ["AGENT_MIXER_HOME"]).parent / "xdg-cfg"))
    proj = _mkproj(tmp_path)
    os.chdir(proj)
    api_module.post_command(api_module.CommandBody(command="preset surgical", session="X"))
    data = api_module.get_state(session="X")
    assert data["dials"]["scope"]["value"] == ["src/**", "tests/**"]
    assert data["dials"]["lines"]["value"] == 30
    # the CLI sees the same session state (same store root)
    from tests.cli_driver import Rig

    rig = Rig(tmp_path / "rig-shell")
    _rc, board, _err = rig.run(["--session", "X", "board"], cwd=str(proj),
                             extra_env={"XDG_STATE_HOME": os.environ["XDG_STATE_HOME"],
                                        "XDG_CONFIG_HOME": os.environ["XDG_CONFIG_HOME"],
                                        "AGENT_MIXER_HOME": os.environ["AGENT_MIXER_HOME"]})
    for needle in ("src/**, tests/**", "30"):
        assert needle in board, (needle, board[:300])
