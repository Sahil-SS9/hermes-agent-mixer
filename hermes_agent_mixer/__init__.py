"""Agent Mixer - a mixing desk for how much a Hermes agent may change.

Hermes plugin exposing the ``/mixer`` slash command and ``pre_tool_call`` /
``pre_llm_call`` hooks. Standard library only.
"""

from .plugin import register

__all__ = ["register"]
__version__ = "0.1.0"