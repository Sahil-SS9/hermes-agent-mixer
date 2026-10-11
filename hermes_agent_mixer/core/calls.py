"""The normalised tool call every adapter produces and the engine consumes."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Call:
    """One tool call, host-neutral.

    kind: ``write`` (whole file), ``edit`` (old/new string replace), ``patch`` (V4A / apply_patch
    text), ``shell`` (a command), ``code`` (run model-written code). Anything else is not Mixer's
    business and never reaches the engine.
    """

    kind: str
    tool: str = ""
    path: str = ""
    content: str | None = None
    old: str | None = None
    new: str | None = None
    replace_all: bool = False
    patch_text: str = ""
    command: str = ""
    shell: str = "posix"  # "posix" or "powershell"
    cwd: str | None = None  # the command's own cwd (Gemini dir_path, Hermes workdir)

    @property
    def label(self) -> str:
        return self.tool or self.kind


@dataclass
class Decision:
    """What Mixer says about a call. No decision at all means "no opinion", never "allow"."""

    action: str  # "deny" or "ask"
    message: str
    rule_key: str = ""
    stage: str = ""  # edits, scope, deps or lines
