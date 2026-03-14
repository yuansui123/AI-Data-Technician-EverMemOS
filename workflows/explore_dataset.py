"""Workflow: explore_dataset

Sequence:
  1. Explore subagent → dataset structure + suggested patterns
  2. Think subagent → store findings to project_summary.md
"""
from __future__ import annotations

from pathlib import Path


async def explore_dataset(
    data_dir: str | Path,
    project_dir: str | Path,
    memory_backend=None,
    context_carry: dict | None = None,
    on_event=None,
) -> dict:
    """Explore *data_dir* and update project_summary.md.

    Returns the exploration report dict.
    """
    from agents.explore import explore
    from agents.think import think

    # Step 1 — Explore
    report = await explore(
        data_dir=data_dir,
        project_dir=project_dir,
        context_carry=context_carry,
        on_event=on_event,
    )

    # Step 2 — Think: store findings + produce user-readable summary
    summary_input = (
        "Summarise the following dataset exploration findings for the user. "
        "Write 3-6 bullet points covering: file count/types, signal dimensions, "
        "key statistics, data quality, and suggested next steps. "
        "Be concrete — include actual numbers.\n\n"
        + _format_report(report)
    )
    human_summary = await think(
        content=summary_input,
        section="Dataset Overview",
        memory_backend=memory_backend,
    )

    report["response"] = human_summary
    return report


def _format_report(report: dict) -> str:
    import json
    return json.dumps({k: v for k, v in report.items() if not k.startswith("_")}, indent=2)
