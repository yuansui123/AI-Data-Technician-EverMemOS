"""Recall tool — active semantic search over long-term memory (EverMemOS).

Schema only — the executor lives in orchestrator/loop.py because it needs
the memory_backend, global_backend, Think agent, and on_event callback.
"""
from __future__ import annotations

SCHEMA: dict = {
    "name": "recall",
    "description": (
        "Search long-term memory (EverMemOS) for previously taught knowledge, "
        "past findings, or procedures. Use when the current task could benefit "
        "from something taught or discovered in a previous session. "
        "Searches both project memory and global cross-project memory."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "What you need to accomplish that requires recalled knowledge",
            },
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "1-3 search queries targeting different aspects of the needed knowledge. "
                    "Use natural language with key domain terms."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": "Max memories per query (default 8)",
            },
        },
        "required": ["objective", "queries"],
    },
}
