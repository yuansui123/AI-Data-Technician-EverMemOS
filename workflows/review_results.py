"""Workflow: review_results

Sequence:
  1. Statistics: compute current classification metrics for all saved rules
  2. Vision: inspect the worst FP/FN plots
  3. Think: produce a structured review → project_summary.md §Review
"""
from __future__ import annotations

from pathlib import Path


async def review_results(
    project_dir: str | Path,
    memory_backend=None,
    pattern: str | None = None,
    context_carry: dict | None = None,
) -> dict:
    """Evaluate current rules, inspect misclassified signals, summarise.

    Returns {metrics_by_pattern, fp_examples, fn_examples, review_text}.
    """
    from subagents.reasoners.statistics import statistics
    from subagents.primitives.vision import vision
    from subagents.reasoners.think import think

    project_dir = Path(project_dir)
    carry = dict(context_carry or {})

    # Step 1 — Statistics: evaluate saved rules
    eval_result = await statistics(
        task=(
            f"Evaluate all saved rules for pattern '{pattern or 'all patterns'}'. "
            f"Return per-pattern metrics and list FP/FN signal IDs."
        ),
        pattern=pattern,
        feature_matrix_path=str(project_dir / "cache" / "feature_matrix.parquet"),
        project_dir=project_dir,
        context_carry=carry,
    )
    carry.update({k: v for k, v in eval_result.items() if k != "_meta"})

    # Step 2 — Vision: inspect worst misclassified signals (up to 4)
    vision_notes: list[dict] = []
    plot_dir = project_dir / "tmp" / "plots"
    for sig_id in (eval_result.get("fp_signals", []) + eval_result.get("fn_signals", []))[:4]:
        plot_path = plot_dir / f"{sig_id}.png"
        if plot_path.exists():
            note = await vision(
                image_path=plot_path,
                context={
                    "signal_id": sig_id,
                    "pattern": pattern or "",
                    "current_rule": eval_result.get("best_rule", ""),
                },
            )
            vision_notes.append({"signal_id": sig_id, **note})

    # Step 3 — Think
    review_text = ""
    if memory_backend:
        import json
        review_input = (
            f"Review results for project '{project_dir.name}':\n"
            f"Statistics: {json.dumps(eval_result, indent=2)}\n\n"
            f"Vision notes on misclassified signals:\n{json.dumps(vision_notes, indent=2)}"
        )
        review_text = await think(
            content=review_input,
            section="Review",
            memory_backend=memory_backend,
        )

    return {
        "metrics_by_pattern": eval_result,
        "fp_examples": eval_result.get("fp_signals", []),
        "fn_examples": eval_result.get("fn_signals", []),
        "vision_notes": vision_notes,
        "review_text": review_text,
    }
