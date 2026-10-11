"""Drive the registered Hermes hooks the way the host does (kwargs mirror hermes_cli.plugins)."""
from __future__ import annotations

import contextlib
import contextvars

FUTURE = {"future_field": "test"}  # hooks must accept kwargs they do not know yet


def tool(ctx, name, args, sid, turn="t1", task="task-1"):
    out = None
    for cb in ctx.hooks.get("pre_tool_call", []):
        r = cb(tool_name=name, args=args, task_id=task, session_id=sid, tool_call_id="call-1",
               turn_id=turn, api_request_id="req", middleware_trace=[], **FUTURE)
        if r and out is None:
            out = r
    return out


def verdict(r) -> str:
    return "allow" if not r else str(r.get("action"))


def turn(ctx, sid, turn_id="t1", parent="", platform="cli", task="task-1") -> list:
    return [cb(session_id=sid, task_id=task, turn_id=turn_id, user_message="go", conversation_history=[],
               is_first_turn=turn_id == "t1", model="m", platform=platform, parent_session_id=parent,
               sender_id="", **FUTURE) for cb in ctx.hooks.get("pre_llm_call", [])]


def subagent_start(ctx, parent, child, parent_turn="t1"):
    for cb in ctx.hooks.get("subagent_start", []):
        cb(parent_session_id=parent, parent_turn_id=parent_turn, parent_subagent_id="",
           child_session_id=child, child_subagent_id="sa-1", child_role="leaf", child_goal="g", **FUTURE)


def subagent_stop(ctx, parent, child):
    for cb in ctx.hooks.get("subagent_stop", []):
        cb(parent_session_id=parent, child_session_id=child, **FUTURE)


def mixer(ctx, raw="") -> str:
    return str(ctx.commands["mixer"]["handler"](raw))


@contextlib.contextmanager
def bound(**kw):
    from gateway.session_context import clear_session_vars, set_session_vars

    tokens = set_session_vars(**kw)
    try:
        yield
    finally:
        clear_session_vars(tokens)


def unbound(fn):
    """Run fn in a fresh contextvars context, like a worker thread that never copied the turn's context."""
    return contextvars.Context().run(fn)
