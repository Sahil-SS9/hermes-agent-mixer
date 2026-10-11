"""Command targets shared by the CLI and the tests: a live session, or the saved settings."""
from __future__ import annotations

from typing import Any, Callable

from hermes_agent_mixer.core import board, settings
from hermes_agent_mixer.core.mixer import Mixer


class SessionTarget(board.Target):
    """Changes land in one session's overrides; ``save`` goes through ``write_saved(key, value)``."""

    def __init__(self, mixer: Mixer, session_id: str, *,
                 write_saved: Callable[[str, Any], None] | None = None) -> None:
        self.mixer = mixer
        self.session_id = session_id
        self.name = session_id
        self._write_saved = write_saved

    def effective(self) -> settings.Effective:
        return self.mixer.effective(self.session_id)

    def set(self, knob: str, value: Any) -> str:
        self.mixer.set_session(self.session_id, knob, value)
        return f" (this session only: {self.session_id})"

    def reset(self) -> str:
        self.mixer.reset_session(self.session_id)
        return "mixer: reset to the saved defaults for this session."

    def _writer(self) -> Callable[[str, Any], None]:
        if not callable(self._write_saved):
            raise board.Refusal("mixer: save is not available here (config writer missing).")
        return self._write_saved

    def save_current(self) -> str:
        write = self._writer()
        eff = self.effective()
        for knob in settings.DIALS:
            write(knob, eff.values[knob])
        return "mixer: saved these as the defaults (all new sessions start here)."

    def save_one(self, knob: str, value: Any) -> str:
        self._writer()(knob, value)
        shown = ", ".join(value) if isinstance(value, list) else value
        return f"mixer: saved {knob} = {shown or '(none)'} as the default (all new sessions start here)."

    def saved_list(self, knob: str) -> list[str]:
        return list(self.mixer.effective(None)[knob])


class SavedTarget(board.Target):
    """``agent-mixer --saved``: dial changes edit the saved settings directly."""

    name = "saved settings"

    def __init__(self, load: Callable[[], dict], store: Callable[[dict], None]) -> None:
        self._load = load
        self._store = store

    def effective(self) -> settings.Effective:
        return settings.resolve(self._load(), None, session="saved settings")

    def set(self, knob: str, value: Any) -> str:
        data = dict(self._load())
        data[knob] = value
        self._store(data)
        return " (saved: new sessions start here)"

    def reset(self) -> str:
        raise board.Refusal("mixer: reset only applies to a session; use --session ID reset.")

    def save_current(self) -> str:
        raise board.Refusal("mixer: --saved already edits the saved settings; give a dial and a value.")

    def save_one(self, knob: str, value: Any) -> str:
        self.set(knob, value)
        return f"mixer: saved {knob} as the default (all new sessions start here)."

    def saved_list(self, knob: str) -> list[str]:
        return list(settings.coerce(knob, self._load().get(knob) or [])[0])
