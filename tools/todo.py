"""Todo tool — session task list management.

Schema only — the executor lives in orchestrator/loop.py because it needs
direct access to session state (session.todos).
"""
from __future__ import annotations

# -- Anthropic tool schema --------------------------------------------------

SCHEMA: dict = {
    "name": "todo",
    "description": (
        "Create or update the session todo list. "
        "Use to track multi-step plans and record what was actually done. "
        "IMPORTANT: You may only set status='done' or status='failed' when you provide "
        "at least one evidence item containing a real tool result. "
        "Never mark a todo done without evidence."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Full replacement todo list for this session.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":     {"type": "string", "description": "Short unique id, e.g. 'a1f'"},
                        "title":  {"type": "string", "description": "Step description"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "running", "done", "failed"],
                        },
                        "evidence": {
                            "type": "array",
                            "description": "Proof this step completed. Required for done/failed.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type":   {"type": "string", "description": "bash|file|vision|text"},
                                    "name":   {"type": "string", "description": "Tool name or filename"},
                                    "result": {"type": "string", "description": "Key excerpt from result"},
                                },
                                "required": ["type", "name", "result"],
                            },
                        },
                    },
                    "required": ["id", "title", "status"],
                },
            }
        },
        "required": ["todos"],
    },
}
