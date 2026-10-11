"""Map Hermes tool calls onto the engine's normalised calls."""
from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from hermes_agent_mixer.core.calls import Call, Decision

_PATH_KEYS = ("path", "file_path", "filename", "target")
_TEXT_KEYS = ("content", "text", "data")


def to_call(tool_name: str, args: dict[str, Any] | None, extra_globs: list[str] | None = None) -> Call | None:
    args = args if isinstance(args, dict) else {}
    if tool_name == "write_file":
        return Call("write", tool_name, path=str(args.get("path") or ""),
                    content=args["content"] if isinstance(args.get("content"), str) else None)
    if tool_name == "patch":
        if args.get("mode") == "patch":
            return Call("patch", tool_name, patch_text=str(args.get("patch") or ""))
        return Call("edit", tool_name, path=str(args.get("path") or ""), old=_str(args.get("old_string")),
                    new=_str(args.get("new_string")), replace_all=bool(args.get("replace_all")))
    if tool_name == "terminal":
        workdir = args.get("workdir")
        return Call("shell", tool_name, command=str(args.get("command") or ""),
                    cwd=workdir if isinstance(workdir, str) and workdir else None)
    if tool_name == "execute_code":
        return Call("code", tool_name)
    if extra_globs and any(fnmatchcase(tool_name, glob) for glob in extra_globs):
        path = next((str(args[k]) for k in _PATH_KEYS if isinstance(args.get(k), str) and args[k]), "")
        content = next((args[k] for k in _TEXT_KEYS if isinstance(args.get(k), str)), None)
        return Call("write", tool_name, path=path, content=content)
    return None


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def to_directive(decision: Decision | None) -> dict[str, str] | None:
    """Hermes pre_tool_call directive: block, approve (with the rule key that sets 'always' grain), or None."""
    if decision is None:
        return None
    if decision.action == "ask":
        return {"action": "approve", "message": decision.message, "rule_key": decision.rule_key}
    return {"action": "block", "message": decision.message}
