"""Periodic memory update — calls Think every N turns to sync project_memory.md.

The orchestrator calls maybe_update_memory() after each turn. If enough turns
have passed since the last update, Think is invoked to merge new information
into project_memory.md, prune stale facts, and keep it under ~3k tokens.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.backend import MemoryBackend
    from session.session import Session


async def maybe_update_memory(
    session: "Session",
    memory_backend: "MemoryBackend",
) -> None:
    """Check if it's time for a periodic memory update. If yes, call Think."""
    import config

    turn_count = len(session.turns)
    interval = config.MEMORY_UPDATE_INTERVAL * 2  # *2 because turns has user+assistant

    if turn_count - session.last_memory_turn < interval:
        return

    await _run_memory_update(session, memory_backend)
    session.last_memory_turn = turn_count


async def force_update_memory(
    session: "Session",
    memory_backend: "MemoryBackend",
) -> None:
    """Force a memory update (called at session end)."""
    if not session.turns:
        return
    await _run_memory_update(session, memory_backend)
    session.last_memory_turn = len(session.turns)


async def _run_memory_update(
    session: "Session",
    memory_backend: "MemoryBackend",
) -> None:
    """Call Think to update project_memory.md from recent conversation."""
    current_memory = await memory_backend.get_summary()

    # Last ~10 turns (20 entries)
    recent = session.turns[-20:] if len(session.turns) > 20 else session.turns
    turns_text = "\n".join(
        f"[{t['role'].upper()}] {t.get('content', '')[:300]}" for t in recent
    )

    if not turns_text.strip():
        return

    from pathlib import Path
    template = (Path(__file__).parent.parent / "prompts" / "templates" / "memory_update.md").read_text(encoding="utf-8")
    prompt = template.format(
        current_memory=current_memory or "(empty)",
        turns_text=turns_text,
    )

    from agents.think import think
    await think(prompt, section="__multi__", memory_backend=memory_backend)
