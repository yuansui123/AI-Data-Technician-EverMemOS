"""Dispatcher — routes a plan action string to the correct subagent or workflow call."""
from __future__ import annotations

from pathlib import Path
from typing import Any


# Map action name → async callable signature
# All callables receive (action_desc, project_dir, memory_backend, context_carry, **kwargs)

async def dispatch(
    action: str,
    description: str,
    project_dir: str | Path,
    memory_backend=None,
    context_carry: dict | None = None,
    **kwargs: Any,
) -> dict:
    """Execute *action* and return its result dict.

    Raises ValueError for unknown action names.
    """
    carry = dict(context_carry or {})

    if action == "explore_dataset":
        from workflows.explore_dataset import explore_dataset
        data_dir = carry.get("data_dir") or kwargs.get("data_dir", str(project_dir))
        return await explore_dataset(data_dir, project_dir, memory_backend, carry)

    if action == "ingest_documents":
        from workflows.ingest_documents import ingest_documents
        file_paths = carry.get("file_paths") or kwargs.get("file_paths", [])
        data_dir = carry.get("data_dir") or kwargs.get("data_dir")
        return await ingest_documents(file_paths, project_dir, memory_backend, data_dir, carry)

    if action == "optimize_pattern":
        from workflows.optimize_pattern import optimize_pattern
        pattern = carry.get("pattern") or kwargs.get("pattern", "")
        return await optimize_pattern(pattern, project_dir, memory_backend, carry)

    if action == "teach_session":
        from workflows.teach_session import teach_session
        pattern = carry.get("pattern") or kwargs.get("pattern")
        return await teach_session(project_dir, memory_backend, pattern)

    if action == "review_results":
        from workflows.review_results import review_results
        pattern = carry.get("pattern") or kwargs.get("pattern")
        return await review_results(project_dir, memory_backend, pattern, carry)

    if action == "apply_rules":
        from workflows.apply_rules import apply_rules
        pattern = carry.get("pattern") or kwargs.get("pattern")
        return await apply_rules(project_dir, memory_backend, pattern)

    if action == "statistics":
        from subagents.reasoners.statistics import statistics
        return await statistics(
            task=description,
            pattern=carry.get("pattern") or kwargs.get("pattern"),
            feature_matrix_path=str(Path(project_dir) / "cache" / "feature_matrix.parquet"),
            project_dir=project_dir,
            context_carry=carry,
        )

    if action == "explore":
        from subagents.reasoners.explore import explore
        data_dir = carry.get("data_dir") or kwargs.get("data_dir", str(project_dir))
        return await explore(data_dir, description, project_dir, carry)

    if action == "think":
        from subagents.reasoners.think import think
        content = carry.get("think_input") or description
        section = kwargs.get("section", "Notes")
        text = await think(content, section, memory_backend)
        return {"think_output": text}

    if action == "bash":
        from subagents.primitives.bash import bash
        cmd = carry.get("bash_cmd") or kwargs.get("cmd", description)
        result = await bash(cmd, cwd=str(project_dir))
        return {"stdout": result.stdout, "stderr": result.stderr, "ok": result.ok}

    if action == "code":
        from subagents.primitives.code import code
        import config
        gap = carry.get("feature_gap") or description
        return await code(
            feature_gap_description=gap,
            project_dir=project_dir,
            output_dir=Path(config.V4CEDARS_LIB) / "features" / "derived",
        )

    if action == "ask_user":
        from orchestrator.tools import ask_user
        answer = await ask_user(description)
        return {"user_answer": answer}

    if action == "respond":
        return {"response": description}

    raise ValueError(f"Unknown action: {action!r}")
