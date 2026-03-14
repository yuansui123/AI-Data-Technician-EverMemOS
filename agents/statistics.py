"""Statistics agent — agentic tool-use loop [Bash, Vision], max 15 iterations.

Model: claude-sonnet-4-6
Tools: bash_execute, vision_analyze + feature/rule/optimization tools
Input: task + feature_matrix path + labeled signal IDs + pattern context
Output: {findings, best_rule?, fitness?, fp_signals, fn_signals, plateau?, suggested_feature_gap?}
"""
from __future__ import annotations

import json
from pathlib import Path


def _load_prompt() -> str:
    p = Path(__file__).parent / "prompts" / "statistics.md"
    return p.read_text(encoding="utf-8")


async def statistics(
    task: str,
    pattern: str | None = None,
    feature_matrix_path: str | None = None,
    labeled_signal_ids: list[str] | None = None,
    project_dir: str | Path | None = None,
    context_carry: dict | None = None,
    extra_tools: list[dict] | None = None,
) -> dict:
    """Run the Statistics agent and return a structured findings dict."""
    from agents.runner import SubagentConfig, ToolExecutor, invoke
    from tools import STATISTICS_TOOLS
    import config

    parts = [f"## Task\n{task}"]
    if pattern:
        parts.append(f"## Pattern\n{pattern}")
    if feature_matrix_path:
        parts.append(f"## Feature matrix path\n{feature_matrix_path}")
    if labeled_signal_ids:
        parts.append(f"## Labeled signal IDs\n{json.dumps(labeled_signal_ids)}")
    if context_carry:
        parts.append(f"## Context carry\n```json\n{json.dumps(context_carry, indent=2)}\n```")

    user_message = "\n\n".join(parts)

    tools = STATISTICS_TOOLS + (extra_tools or [])

    cfg = SubagentConfig(
        model=config.STATISTICS_MODEL,
        system_prompt=_load_prompt(),
        tools=tools,
        thinking_budget=0,
        max_iterations=config.STATISTICS_MAX_ITER,
        max_tokens=4096,
    )

    executor = ToolExecutor(project_dir=str(project_dir) if project_dir else None)

    result = await invoke(cfg, [{"role": "user", "content": user_message}], tool_executor=executor)

    text = result.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        findings = json.loads(text)
    except json.JSONDecodeError:
        findings = {"raw": result.text, "parse_error": True}

    findings["_meta"] = {
        "iterations": result.iterations,
        "tool_calls": len(result.tool_calls),
    }
    return findings
