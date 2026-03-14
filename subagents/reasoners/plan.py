"""Plan reasoner — single-pass, extended thinking, no tools.

Model: claude-opus-4-6, thinking budget=8000
Input: project_summary + workflow_state snapshot + user request
Output: {steps, complexity, clarifications_needed, is_terminal}
Limit:  1 API call
"""
from __future__ import annotations

import json
from pathlib import Path


def _load_prompt() -> str:
    p = Path(__file__).parent.parent / "prompts" / "plan.md"
    return p.read_text(encoding="utf-8")


async def plan(
    user_request: str,
    project_summary: str = "",
    workflow_state: dict | None = None,
) -> dict:
    """Call the Plan agent and return the structured plan dict."""
    from subagents.base import SubagentConfig, invoke
    import config

    state_text = json.dumps(workflow_state or {}, indent=2)

    user_message = (
        f"## Project Summary\n{project_summary or '(empty)'}\n\n"
        f"## Workflow State\n```json\n{state_text}\n```\n\n"
        f"## User Request\n{user_request}"
    )

    cfg = SubagentConfig(
        model=config.PLAN_MODEL,
        system_prompt=_load_prompt(),
        tools=[],
        thinking_budget=config.PLAN_THINKING_BUDGET,
        max_iterations=1,
        max_tokens=4096,
    )

    result = await invoke(cfg, [{"role": "user", "content": user_message}])

    # parse JSON from response
    text = result.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "steps": [],
            "complexity": "simple",
            "clarifications_needed": [],
            "is_terminal": False,
            "raw": result.text,
            "parse_error": True,
        }
