"""Workflow: explore_dataset

Sequence:
  1. Task agent → dataset structure + suggested patterns
  2. Think agent → store findings to project_memory.md
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
    """Explore *data_dir* and update project_memory.md.

    Returns the exploration report as a dict.
    """
    import json
    from agents.task import task
    from agents.think import think

    # Step 1 — Task agent: explore the dataset
    task_desc = (
        f"Explore the dataset at {data_dir}.\n\n"
        "List directory contents, identify file types and data format, "
        "load a sample file, compute basic statistics (file count, signal dimensions, "
        "sampling rate, duration, channel count, amplitude range). "
        "Plot 2-3 sample signals and pass them to vision for morphological description. "
        "Identify likely patterns and suggest which to target.\n\n"
        "Return a JSON object with keys: n_signals, fs, duration_s, file_types, "
        "channel_count, quality_flags, domain_notes, suggested_patterns."
    )
    result_text = await task(
        task_description=task_desc,
        project_dir=project_dir,
        on_event=on_event,
    )

    # Parse JSON from response
    text = result_text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        report = {"raw": result_text, "parse_error": True}

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
