"""Ask user tool — human-in-the-loop input, no LLM.

In CLI mode: prints question and reads stdin.
In web mode: the orchestrator uses answer_queue instead (handled in loop.py).
"""
from __future__ import annotations


async def ask_user(question: str) -> str:
    """Print *question* to stdout and read a line from stdin asynchronously."""
    import asyncio
    import sys

    loop = asyncio.get_event_loop()
    print(f"\n[AI Data Technician] {question}\n> ", end="", flush=True)
    response = await loop.run_in_executor(None, sys.stdin.readline)
    return response.strip()


# -- Anthropic tool schema --------------------------------------------------

SCHEMA: dict = {
    "name": "ask_user",
    "description": "Ask the user a clarifying question and wait for their answer. Use only when genuinely blocked.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question to ask"}
        },
        "required": ["question"],
    },
}
