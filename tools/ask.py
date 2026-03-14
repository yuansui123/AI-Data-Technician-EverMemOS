"""Ask user tool — human-in-the-loop input.

Schema only — the executor lives in orchestrator/loop.py because it needs
the answer_queue (WebSocket) to receive the user's response from the browser.
"""
from __future__ import annotations

# -- Anthropic tool schema --------------------------------------------------

SCHEMA: dict = {
    "name": "ask",
    "description": "Ask the user a clarifying question and wait for their answer. Use only when genuinely blocked.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question to ask"}
        },
        "required": ["question"],
    },
}
