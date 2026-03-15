"""End-of-session deep reflection — updates L2 project memory and promotes insights to L3 global memory."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.backend import MemoryBackend
    from session.session import Session


async def end_of_session_reflection(
    session: "Session",
    memory_backend: "MemoryBackend",
    global_backend: "MemoryBackend",
) -> None:
    """Run at session end. Force L2 update, then promote to L3 if warranted."""

    # Force a final L2 update
    from orchestrator.memory_gate import force_update_memory
    await force_update_memory(session, memory_backend)

    # Only do L3 reflection if the session had substantial content
    if len(session.turns) < 6:
        return

    current_memory = await memory_backend.get_summary()
    current_global = await global_backend.get_summary()

    turns_text = "\n".join(
        f"[{t['role'].upper()}] {t.get('content', '')[:200]}" for t in session.turns[-20:]
    )

    from pathlib import Path
    template = (Path(__file__).parent.parent / "prompts" / "templates" / "session_reflection.md").read_text(encoding="utf-8")
    prompt = template.format(
        turns_text=turns_text,
        current_memory=current_memory,
        current_global=current_global or "(empty)",
    )

    from agents.think import think
    result = await think(prompt, thinking_budget=2000)

    if result.startswith("MODE: no_update"):
        return

    # Parse and route to global backend
    _TAGS = [
        ("GLOBAL_PROCEDURES:", "Reusable Procedures"),
        ("GLOBAL_PREFERENCES:", "User Preferences"),
        ("GLOBAL_INSIGHTS:", "Cross-Project Insights"),
    ]
    all_tag_names = [tag for tag, _ in _TAGS]

    for tag, section in _TAGS:
        if tag not in result:
            continue
        start = result.index(tag) + len(tag)
        # Find end: next tag or end of string
        end = len(result)
        for other_tag in all_tag_names:
            if other_tag != tag and other_tag in result:
                idx = result.index(other_tag)
                if idx > start:
                    end = min(end, idx)
        text = result[start:end].strip()
        if text:
            await global_backend.store(text, {"section": section})
