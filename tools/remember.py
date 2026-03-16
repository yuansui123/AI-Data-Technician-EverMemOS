"""Remember tool — explicitly save user-specified knowledge to long-term memory.

Schema only — the executor lives in orchestrator/loop.py because it needs
the memory_backend (and optionally global_backend) to persist the memory.
"""
from __future__ import annotations

SCHEMA: dict = {
    "name": "remember",
    "description": (
        "Save important information to long-term memory so it can be recalled in future sessions. "
        "Use when the user explicitly asks you to remember something — preferences, parameters, "
        "procedures, domain knowledge, or any reusable fact. The memory is stored in both "
        "project-scoped and (if hybrid mode) file-based memory for durability."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": (
                    "The knowledge to remember. Be detailed and structured — include "
                    "parameter values, code snippets, rationale, and context so the "
                    "memory is self-contained and useful when recalled later."
                ),
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Keywords/tags for retrieval (e.g. ['spectrogram', 'iEEG', 'plotting']). "
                    "Include domain terms, tool names, and topic keywords."
                ),
            },
            "scope": {
                "type": "string",
                "enum": ["project", "global"],
                "description": (
                    "Where to store: 'project' (default) for project-specific knowledge, "
                    "'global' for cross-project preferences/procedures."
                ),
            },
        },
        "required": ["content", "tags"],
    },
}
