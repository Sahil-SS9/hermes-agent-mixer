"""Hermes' answers to the engine's path and text questions (D3, D4), with host-free fallbacks."""
from __future__ import annotations

import os

from hermes_agent_mixer.core import fuzzy
from hermes_agent_mixer.core.ports import Ports, env_workspace
from hermes_agent_mixer.hermes import host


class HermesPorts(Ports):
    def _posix(self, text: str) -> str:
        return text.replace("\\", "/") if self.windows else text

    def base_dir(self, task_id: str | None = None) -> str:
        root = host.workspace_root(task_id) or env_workspace() or os.getcwd()
        return self._normalise(root)

    def workspace_root(self, task_id: str | None = None) -> str:
        return self.base_dir(task_id)

    def resolve(self, path: str, task_id: str | None = None, base: str | None = None) -> str:
        if base is None:
            resolved = host.resolve_path(path, task_id)
            if resolved is not None:
                return self._posix(resolved)
        return super().resolve(path, task_id, base)

    def fuzzy_replace(self, content: str, old: str, new: str, replace_all: bool = False) -> str | None:
        if host.has_fuzzy():
            return host.fuzzy_replace(content, old, new, replace_all)
        return fuzzy.replace(content, old, new, replace_all)
