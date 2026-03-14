"""Think reasoner — single-pass, extended thinking, no tools.

Model: claude-sonnet-4-6, thinking budget=5000
Input: pre-processed results as text (Vision outputs, Bash outputs, feedback)
Output: compact insight → stored via memory_backend.store()
Also used for: auto-compact (summarise oldest conversation turns)
Limit:  1 API call
"""
from __future__ import annotations

from pathlib import Path


def _load_prompt() -> str:
    p = Path(__file__).parent.parent / "prompts" / "think.md"
    return p.read_text(encoding="utf-8")


async def think(
    content: str,
    section: str = "Notes",
    memory_backend=None,
) -> str:
    """Synthesise *content* into a compact insight.

    If *memory_backend* is provided, stores the result under *section* in
    project_summary.md and returns the stored text.
    Otherwise just returns the text.
    """
    from subagents.base import SubagentConfig, invoke
    import config

    cfg = SubagentConfig(
        model=config.THINK_MODEL,
        system_prompt=_load_prompt(),
        tools=[],
        thinking_budget=config.THINK_THINKING_BUDGET,
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

    Returns a compact paragraph (≤ 200 words) preserving key findings.
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
    # strip MODE: compact prefix if model echoes it
    if result.startswith("MODE: compact"):
        result = result[len("MODE: compact"):].strip()
    return result
