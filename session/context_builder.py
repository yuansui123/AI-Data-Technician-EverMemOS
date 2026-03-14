"""Assembles the full context dict passed to the orchestrator each turn.

Context order (mirrors Claude Code):
  project_instructions.md  (~1-2k tokens, static)
  + project_summary.md     (~2-5k tokens, agent-maintained)
  + session turns          (grows within session)
  + todos                  (structured task list with evidence)
  + user_input

Auto-compact triggers when instructions + summary + turns > AUTO_COMPACT_THRESHOLD tokens.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.backend import MemoryBackend
    from session.session import Session


def _token_count(text: str) -> int:
    """Fast approximate token count (4 chars ≈ 1 token, no dependency needed at runtime)."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return len(text) // 4


def _turns_text(turns: list[dict]) -> str:
    return "\n".join(t.get("content", "") for t in turns)


def _read_instructions(project_dir: Path) -> str:
    path = project_dir / "project_instructions.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


async def build_context(
    project_dir: str | Path,
    session: "Session",
    memory_backend: "MemoryBackend",
    user_input: str,
) -> dict:
    """Return assembled context dict, compacting stale turns if needed.

    Returns:
        {
            "instructions": str,
            "summary":      str,
            "turns":        list[dict],
            "scratchpad":   str,
            "user_input":   str,
            "context_carry": dict,
        }
    """
    from config import AUTO_COMPACT_THRESHOLD

    project_dir = Path(project_dir)
    instructions = _read_instructions(project_dir)
    summary = await memory_backend.get_summary()
    turns = session.turns

    total = _token_count(instructions + summary + _turns_text(turns))

    if total > AUTO_COMPACT_THRESHOLD and len(turns) > 10:
        # deferred import to avoid circular dependency at load time
        from subagents.reasoners.think import compact_turns

        compact = await compact_turns(session.oldest_turns(20))
        turns = [{"role": "summary", "content": compact}] + session.recent_turns(5)
        session.replace_turns(turns)

    return {
        "instructions": instructions,
        "summary": summary,
        "turns": turns,
        "todos": session.todos,
        "user_input": user_input,
        "context_carry": session.context_carry,
    }


def format_context_for_llm(ctx: dict) -> str:
    """Flatten the context dict into a single string for the orchestrator system prompt."""
    parts: list[str] = []

    if ctx["instructions"]:
        parts.append(f"## Project Instructions\n{ctx['instructions']}")

    if ctx["summary"]:
        parts.append(f"## Project Summary\n{ctx['summary']}")

    if ctx.get("todos"):
        parts.append(f"## Current Todos\n```json\n{json.dumps(ctx['todos'], indent=2)}\n```")

    if ctx["context_carry"]:
        parts.append(f"## Context Carry\n```json\n{json.dumps(ctx['context_carry'], indent=2)}\n```")

    return "\n\n".join(parts)
