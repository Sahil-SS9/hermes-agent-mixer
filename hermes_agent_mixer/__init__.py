"""Agent Mixer - a mixing desk for how much a coding agent may change.

Hermes plugin (``/mixer`` plus ``pre_tool_call`` / ``pre_llm_call`` hooks) and a harness-agnostic
``agent-mixer`` CLI for Claude Code, Codex and Gemini CLI. Standard library only.

``register`` imports the Hermes adapter lazily, so the CLI never pays for it.
"""

__all__ = ["register"]
__version__ = "0.2.0"


def register(ctx):
    """Hermes plugin entry point (``hermes_agent.plugins`` group)."""
    from hermes_agent_mixer.hermes.plugin import register as _register

    _register(ctx)
