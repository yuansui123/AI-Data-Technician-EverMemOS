"""Think — single-pass Claude utility for summarization, compaction, and any structured reasoning.

This is the universal single-pass LLM call. Callers provide the prompt content;
Think sends it to Claude with optional extended thinking and returns the text.

Used for: milestone summaries, auto-compact, LASR mutation/crossover prompts,
concept abstraction, planning — anything that needs one LLM pass.
"""
from __future__ import annotations

from pathlib import Path


def _load_prompt() -> str:
    p = Path(__file__).parent / "prompts" / "think.md"
    return p.read_text(encoding="utf-8")


async def think(
    content: str,
    section: str = "Notes",
    memory_backend=None,
    thinking_budget: int | None = None,
) -> str:
    """Single-pass Claude call. Returns the response text.

    If *memory_backend* is provided, stores the result under *section* in
    project_summary.md.
    If *thinking_budget* is None, uses config.THINK_THINKING_BUDGET.
    """
    from agents.runner import SubagentConfig, invoke
    import config

    budget = thinking_budget if thinking_budget is not None else config.THINK_THINKING_BUDGET

    cfg = SubagentConfig(
        model=config.THINK_MODEL,
        system_prompt=_load_prompt(),
        tools=[],
        thinking_budget=budget,
        max_iterations=1,
        max_tokens=2048,
    )

    result = await invoke(cfg, [{"role": "user", "content": content}])
    text = result.text.strip()

    if memory_backend and not text.startswith("MODE: no_update"):
        await memory_backend.store(text, {"section": section})

    return text


async def compact_turns(turns: list[dict]) -> str:
    """Summarise the oldest conversation turns for auto-compact.

    Returns a compact paragraph (<=200 words) preserving key findings.
    """
    if not turns:
        return ""

    turns_text = "\n".join(
        f"[{t['role'].upper()}] {t.get('content', '')}" for t in turns
    )
    prompt = (
        "MODE: compact\n\n"
        "Summarise the following conversation turns. "
        "Preserve: key findings, feature names, rule strings, accuracy metrics, decisions made, open questions.\n\n"
        + turns_text
    )
    result = await think(prompt)
    if result.startswith("MODE: compact"):
        result = result[len("MODE: compact"):].strip()
    return result
