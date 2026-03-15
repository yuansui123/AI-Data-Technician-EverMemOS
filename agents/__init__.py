"""Agents — two agent types: think (single-pass) and task (multi-turn tool loop)."""

from agents.runner import (
    SubagentConfig,
    SubagentResult,
    ToolExecutor,
    invoke,
)
from agents.think import think, compact_turns
from agents.task import task

__all__ = [
    "SubagentConfig", "SubagentResult", "ToolExecutor",
    "invoke",
    "think", "compact_turns",
    "task",
]
