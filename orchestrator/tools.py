"""Orchestrator-level tools: ask_user() — the only human-in-the-loop primitive."""
from __future__ import annotations


async def ask_user(question: str) -> str:
    """Print *question* to stdout and read a line from stdin asynchronously.

    In CLI mode this blocks until the user types a response.
    In server mode this would be replaced by a webhook / WebSocket round-trip.
    """
    import asyncio
    import sys

    loop = asyncio.get_event_loop()
    print(f"\n[AI Data Technician] {question}\n> ", end="", flush=True)
    response = await loop.run_in_executor(None, sys.stdin.readline)
    return response.strip()
