"""What every CLI harness shares: where files live, saved settings, the event model and the hook runner.

Each harness module only maps its own payloads to an :class:`Event` and renders replies in its own
JSON dialect. Mixer never emits "allow" (D10): it denies, asks, or says nothing. Where a harness
cannot ask (Codex, Gemini) ``ask`` becomes deny with the reason why (D11).
"""
from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from typing import Any

from hermes_agent_mixer.core import board, settings
from hermes_agent_mixer.core.calls import Call, Decision
from hermes_agent_mixer.core.mixer import Mixer
from hermes_agent_mixer.core.ports import Ports
from hermes_agent_mixer.core.store import FileStore, file_lock
from hermes_agent_mixer.core.targets import SessionTarget

HARNESSES = ("claude", "codex", "gemini")
IDLE_SECONDS = 7 * 24 * 3600.0


class SettingsError(Exception):
    """settings.json exists but cannot be used."""


# -- locations -----------------------------------------------------------------------------------


class Paths:
    """Where Mixer keeps saved settings and per-session state (X2)."""

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        env = os.environ if environ is None else environ
        self.env = env
        explicit = env.get("AGENT_MIXER_HOME")
        windows = os.name == "nt"
        user = env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")
        self.user_home = user
        if explicit:
            self.config_dir = explicit
            self.state_dir = os.path.join(explicit, "state")
        elif windows:
            self.config_dir = os.path.join(env.get("APPDATA") or os.path.join(user, "AppData", "Roaming"), "agent-mixer")
            self.state_dir = os.path.join(env.get("LOCALAPPDATA") or os.path.join(user, "AppData", "Local"),
                                          "agent-mixer", "state")
        else:
            self.config_dir = os.path.join(env.get("XDG_CONFIG_HOME") or os.path.join(user, ".config"), "agent-mixer")
            self.state_dir = os.path.join(env.get("XDG_STATE_HOME") or os.path.join(user, ".local", "state"), "agent-mixer")

    @property
    def settings_file(self) -> str:
        return os.path.join(self.config_dir, "settings.json")


def load_saved(paths: Paths) -> dict[str, Any]:
    try:
        with open(paths.settings_file, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise SettingsError(f"cannot read {paths.settings_file}: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{paths.settings_file} must hold a JSON object")
    return data


def store_saved(paths: Paths, data: dict[str, Any]) -> None:
    os.makedirs(paths.config_dir, exist_ok=True)
    target = paths.settings_file
    tmp = f"{target}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, target)


def update_saved(paths: Paths, key: str, value: Any) -> None:
    with file_lock(paths.settings_file + ".lock"):
        data = load_saved(paths)
        data[key] = value
        store_saved(paths, data)


def make_mixer(paths: Paths, saved: dict[str, Any] | None = None) -> Mixer:
    loader = (lambda: saved) if saved is not None else (lambda: load_saved(paths))
    return Mixer(FileStore(paths.state_dir), loader, max_idle=IDLE_SECONDS)


# -- events ------------------------------------------------------------------------------------------


@dataclass
class Event:
    kind: str  # "tool" | "prompt"
    session: str
    cwd: str
    workspace: str
    turn: str | None = None
    call: Call | None = None
    mixer_args: str | None = None  # set when the prompt is a /mixer command
    hook_event: str = ""


def mixer_command_args(prompt: str) -> str | None:
    """The arguments of a typed ``/mixer ...`` prompt, or None for any other prompt."""
    text = (prompt or "").strip()
    if text == "/mixer":
        return ""
    if text.startswith("/mixer") and text[6:7].isspace():
        return text[6:].strip()
    return None


def write_call(tool: str, args: dict[str, Any], path_keys=("file_path", "path", "filename", "target"),
               text_keys=("content", "text", "data", "new_source")) -> Call:
    path = next((str(args[k]) for k in path_keys if isinstance(args.get(k), str) and args[k]), "")
    content = next((args[k] for k in text_keys if isinstance(args.get(k), str)), None)
    return Call("write", tool, path=path, content=content)


def degrade_message(decision: Decision, display: str) -> str:
    hint = "agent-mixer deps allow" if decision.stage == "deps" else "agent-mixer edits auto"
    return (f"{decision.message} Agent Mixer 'ask' can't prompt in {display}, so it denies instead. "
            f"To allow this, run `{hint}` (or approve the change another way).")


# -- the runner ----------------------------------------------------------------------------------------


def load_harness(name: str):
    return importlib.import_module(f"hermes_agent_mixer.harness.{name}")


def run_hook(name: str, raw: str, paths: Paths, environ: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Handle one hook event: (exit code, stdout, stderr). Reads nothing but its arguments."""
    env = os.environ if environ is None else environ
    mod = load_harness(name)
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object")
    except ValueError as exc:
        return 2, "", f"agent-mixer: cannot read the {name} hook input ({exc}). Run `agent-mixer doctor`.\n"
    saved: dict[str, Any] | None = None
    problem: Exception | None = None
    try:
        saved = load_saved(paths)
    except SettingsError as exc:
        problem = exc
    extras = settings.coerce("extra_write_tools", (saved or {}).get("extra_write_tools") or [])[0]
    try:
        event = mod.parse(payload, env, extras)
    except Exception as exc:  # noqa: BLE001 - a payload we cannot read is unreadable input
        return 2, "", f"agent-mixer: cannot read the {name} hook input ({type(exc).__name__}: {exc}). Run `agent-mixer doctor`.\n"
    if event is None:
        return 0, "", ""
    try:
        if problem is not None:
            raise problem
        return 0, _handle(mod, event, make_mixer(paths, saved), paths), ""
    except Exception as exc:  # noqa: BLE001 - every failure is reported, never swallowed silently
        return _fail(mod, event, exc, paths, saved)


def _dump(data: dict | None) -> str:
    return "" if not data else json.dumps(data) + "\n"


def _handle(mod: Any, event: Event, mixer: Mixer, paths: Paths) -> str:
    if event.kind == "tool":
        ports = Ports(cwd=event.cwd, workspace=event.workspace)
        decision = mixer.decide(event.session, event.call, ports, turn_id=event.turn, cwd=event.cwd)
        if decision is None:
            return ""
        if decision.action == "ask":
            if mod.CAN_ASK:
                return _dump(mod.render_tool("ask", decision.message, event))
            return _dump(mod.render_tool("deny", degrade_message(decision, mod.DISPLAY), event))
        return _dump(mod.render_tool("deny", decision.message, event))
    if event.mixer_args is not None:
        mixer.touch(event.session, event.cwd)
        target = SessionTarget(mixer, event.session, write_saved=lambda k, v: update_saved(paths, k, v))
        return _dump(mod.render_command(board.handle_command(event.mixer_args, target), event))
    mixer.begin_turn(event.session, event.turn, cwd=event.cwd)
    line = mixer.rules_line(event.session)
    return _dump(mod.render_context(line, event)) if line else ""


def _fail(mod: Any, event: Event, exc: Exception, paths: Paths, saved: dict | None) -> tuple[int, str, str]:
    """D12: unreadable input is exit 2; an internal error denies when any dial is off its default."""
    detail = f"{type(exc).__name__}: {exc}"
    if event.kind == "tool":
        if _might_be_restricted(paths, saved, event.session):
            message = (f"Agent Mixer could not check this call ({detail}), so it blocks it. "
                       "Run `agent-mixer doctor` to see what is wrong.")
            return 0, _dump(mod.render_tool("deny", message, event)), ""
        return 0, "", ""
    if event.mixer_args is not None:
        message = f"Agent Mixer could not run that command ({detail}). Run `agent-mixer doctor`."
        return 0, _dump(mod.render_command(message, event)), ""
    return 0, "", ""


def _might_be_restricted(paths: Paths, saved: dict | None, session: str) -> bool:
    try:
        values = settings.resolve(saved if saved is not None else load_saved(paths))
    except Exception:  # noqa: BLE001 - cannot tell what is configured: fail closed
        return True
    if not values.is_default():
        return True
    try:
        return FileStore(paths.state_dir).has_session_file(session)
    except Exception:  # noqa: BLE001
        return True
