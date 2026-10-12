"""Agent Mixer dashboard plugin — backend API routes, mounted at /api/plugins/agent-mixer/.

Every handler is a thin wrapper around the same code paths the CLI uses
(``core.board`` + ``core.targets`` over ``harness.common.make_mixer``), so the
dashboard console cannot drift from ``agent-mixer`` on the command line or
``/mixer`` in chat. State lives in the one CLI store (``$AGENT_MIXER_HOME`` /
XDG defaults), so a change made here is enforced by the hooks immediately.

Imported only by the web dashboard server process (fastapi is a server
dependency, not a plugin runtime dependency). This file must expose ``router``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# The dashboard server imports this file by path; make the repo's package
# importable whether the plugin runs as a directory plugin, a pip entry point,
# or a plain checkout.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hermes_agent_mixer.core import board
from hermes_agent_mixer.core import presets as presets_mod
from hermes_agent_mixer.core.store import file_lock
from hermes_agent_mixer.harness.common import (
    SettingsError,
    load_saved,
    make_mixer,
    update_saved,
)

router = APIRouter()


def _paths():
    from hermes_agent_mixer.harness.common import Paths

    return Paths(dict(os.environ))


def _target(session: str | None, saved: bool):
    """The board Target for this request — the exact objects the CLI builds."""
    from hermes_agent_mixer.core.targets import SavedTarget, SessionTarget

    paths = _paths()
    if saved:
        def read():
            return load_saved(paths)

        def write(data):
            with file_lock(paths.settings_file + ".lock"):
                # store_saved imported lazily to mirror cli._command
                from hermes_agent_mixer.harness.common import store_saved

                store_saved(paths, data)

        return SavedTarget(read, write), paths
    mixer = make_mixer(paths)
    if not session:
        raise HTTPException(status_code=400, detail="session is required unless saved=true")
    return SessionTarget(mixer, session, write_saved=lambda k, v: update_saved(paths, k, v)), paths


def _state_payload(target, session_label: str) -> dict[str, Any]:
    from hermes_agent_mixer import __version__
    from hermes_agent_mixer.core import settings

    eff = target.effective()
    lines = eff.values["lines"]
    return {
        "session": session_label,
        "saved_mode": getattr(target, "name", "") == "saved settings",
        "version": __version__,
        "presets": presets_mod.names(),
        "dials": {
            "edits": {"value": eff.values["edits"], "source": eff.sources["edits"],
                      "choices": list(settings.EDIT_MODES)},
            "deps": {"value": eff.values["deps"], "source": eff.sources["deps"],
                     "choices": list(settings.DEPS_MODES)},
            "lines": {"value": lines, "source": eff.sources["lines"], "left": eff.left},
            "scope": {"value": eff.values["scope"], "source": eff.sources["scope"]},
            "extra_write_tools": {"value": eff.values["extra_write_tools"],
                                  "source": eff.sources["extra_write_tools"]},
        },
        "warnings": list(eff.warnings),
        "board": board.render_board(eff, session_label),
    }


class CommandBody(BaseModel):
    command: str = Field(min_length=1, max_length=300)
    session: str | None = None
    saved: bool = False


@router.get("/state")
def get_state(session: str | None = None, saved: bool = False) -> dict[str, Any]:
    try:
        target, _paths = _target(session, saved)
    except SettingsError as exc:
        raise HTTPException(status_code=500, detail=f"{exc}. Run `agent-mixer doctor`.") from exc
    if saved:
        label = "saved settings"
    else:
        label = session or "no session"
        if target.name == "no session":
            raise HTTPException(status_code=400, detail=target.effective().session or "no session")
    try:
        return _state_payload(target, getattr(target, "name", label))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@router.get("/presets")
def get_presets() -> dict[str, Any]:
    return {"presets": presets_mod.names()}


@router.post("/command")
def post_command(body: CommandBody) -> dict[str, Any]:
    try:
        target, _paths = _target(body.session or None, body.saved)
    except SettingsError as exc:
        raise HTTPException(status_code=500, detail=f"{exc}. Run `agent-mixer doctor`.") from exc
    try:
        reply = board.handle_command(body.command, target)
        refused = reply.startswith("mixer: reset only applies") or reply.lower().startswith(("unknown", "usage"))
        ok = not refused and "needs" not in reply.lower()
        state = _state_payload(target, getattr(target, "name", "no session"))
    except board.Refusal as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    return {"reply": reply, "ok": ok, "state": state}
