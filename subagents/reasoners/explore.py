"""Explore reasoner — agentic tool-use loop [Bash, Vision], max 10 iterations.

Model: claude-sonnet-4-6
Tools: bash_execute, vision_analyze
Input: paths to explore + task description
Output: {n_signals, fs, duration_s, file_types, quality_flags, domain_notes, suggested_patterns}
"""
from __future__ import annotations

import json
from pathlib import Path


def _load_prompt() -> str:
    p = Path(__file__).parent.parent / "prompts" / "explore.md"
    return p.read_text(encoding="utf-8")


async def explore(
    data_dir: str | Path,
    task: str = "Explore this dataset and produce a structured report.",
    project_dir: str | Path | None = None,
    context_carry: dict | None = None,
    on_event=None,
) -> dict:
    """Run the Explore agent on *data_dir* and return the exploration report dict."""
    from subagents.base import SubagentConfig, ToolExecutor, invoke
    from tools import EXPLORE_TOOLS
    import config

    carry_text = ""
    if context_carry:
        carry_text = f"\n\n## Context from prior steps\n```json\n{json.dumps(context_carry, indent=2)}\n```"

    user_message = (
        f"## Data directory\n{data_dir}\n\n"
        f"## Task\n{task}"
        + carry_text
    )

    cfg = SubagentConfig(
        model=config.EXPLORE_MODEL,
        system_prompt=_load_prompt(),
        tools=EXPLORE_TOOLS,
        thinking_budget=0,  # regular inference for tool-use loop
        max_iterations=config.EXPLORE_MAX_ITER,
        max_tokens=4096,
    )

    executor = ToolExecutor(project_dir=str(project_dir) if project_dir else None)

    # Wrap on_event so explore's tool calls appear as sub_tool_call/sub_tool_result
    sub_on_event = None
    if on_event:
        async def sub_on_event(event: dict):
            if event["type"] == "tool_call":
                await on_event({"type": "sub_tool_call", "subagent": "explore",
                                "tool": event["tool"], "input": event["input"]})
            elif event["type"] == "tool_result":
                await on_event({"type": "sub_tool_result", "subagent": "explore",
                                "tool": event["tool"], "result": event["result"]})
            # skip text_delta from subagents — not user-facing

    result = await invoke(cfg, [{"role": "user", "content": user_message}],
                          tool_executor=executor, on_event=sub_on_event)

    # parse JSON from final response
    text = result.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        report = {"raw": result.text, "parse_error": True}

    report["_meta"] = {
        "iterations": result.iterations,
        "tool_calls": len(result.tool_calls),
    }
    return report
