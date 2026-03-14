"""Workflow: optimize_pattern

Sequence:
  1. Statistics: compute features + baseline rule evaluation
  2. Loop (up to N_ROUNDS):
     a. Statistics: LASR optimization → candidate rules + FP/FN signals
     b. If plateau: Vision × FN signals → suggested_feature_gap
     c. If feature_gap: Code → new feature draft → Bash → recompute features
     d. Think: update project_summary.md after each round
  3. Statistics: final evaluation of best rule
  4. Think: store final rule + metrics to project_summary.md
"""
from __future__ import annotations

from pathlib import Path

N_ROUNDS = 5


async def optimize_pattern(
    pattern_name: str,
    project_dir: str | Path,
    memory_backend=None,
    context_carry: dict | None = None,
) -> dict:
    """Run the full LASR-based optimization loop for *pattern_name*.

    Returns {best_rule, fitness, metrics, rounds_run, feature_gaps_found}.
    """
    from subagents.reasoners.statistics import statistics
    from subagents.reasoners.think import think
    from subagents.primitives.vision import vision
    from subagents.primitives.code import code
    from subagents.primitives.bash import bash
    import config

    project_dir = Path(project_dir)
    cache_dir = project_dir / "cache"
    feature_matrix_path = str(cache_dir / "feature_matrix.parquet")

    carry = dict(context_carry or {})
    best_rule: str = carry.get("best_rule", "")
    best_fitness: float = 0.0
    rounds_run = 0
    feature_gaps: list[str] = []

    # Step 1 — baseline
    baseline = await statistics(
        task=f"Compute feature matrix for pattern '{pattern_name}' and evaluate current best rule if any.",
        pattern=pattern_name,
        feature_matrix_path=feature_matrix_path,
        project_dir=project_dir,
        context_carry=carry,
    )
    carry.update({k: v for k, v in baseline.items() if k != "_meta"})

    # Step 2 — optimization loop
    for round_i in range(1, N_ROUNDS + 1):
        rounds_run = round_i

        opt_result = await statistics(
            task=(
                f"Run LASR optimization for pattern '{pattern_name}'. "
                f"Current best rule: {carry.get('best_rule', 'none')}. "
                f"Identify FP and FN signals."
            ),
            pattern=pattern_name,
            feature_matrix_path=feature_matrix_path,
            project_dir=project_dir,
            context_carry=carry,
        )
        carry.update({k: v for k, v in opt_result.items() if k != "_meta"})

        new_fitness = float(opt_result.get("fitness", 0.0))
        if new_fitness > best_fitness:
            best_fitness = new_fitness
            best_rule = opt_result.get("best_rule", best_rule)

        # plateau → Vision on FN signals
        if opt_result.get("plateau"):
            fn_signals: list[str] = opt_result.get("fn_signals", [])
            feature_gap = await _vision_gap(fn_signals, pattern_name, carry, project_dir)
            if feature_gap and feature_gap != "none":
                feature_gaps.append(feature_gap)
                # Code → new feature
                await _synthesize_feature(feature_gap, project_dir, config.V4CEDARS_LIB)
                # Recompute feature matrix
                await bash(
                    f'python -c "import sys; sys.path.insert(0,r\"{config.V4CEDARS_LIB}\"); '
                    f'from feature_store import FeatureStore; '
                    f'FeatureStore(r\"{project_dir}\").recompute(force=True)"',
                    cwd=str(project_dir),
                )
                carry["new_feature"] = feature_gap

        # Think: milestone update
        if memory_backend:
            await think(
                content=f"Round {round_i} optimization result for {pattern_name}:\n{opt_result}",
                section=f"Pattern: {pattern_name}",
                memory_backend=memory_backend,
            )

        if opt_result.get("is_terminal"):
            break

    # Final evaluation
    final = await statistics(
        task=f"Final evaluation of best rule '{best_rule}' for pattern '{pattern_name}'.",
        pattern=pattern_name,
        feature_matrix_path=feature_matrix_path,
        project_dir=project_dir,
        context_carry=carry,
    )

    if memory_backend:
        await think(
            content=f"Final optimization result for {pattern_name}: {final}",
            section=f"Pattern: {pattern_name}",
            memory_backend=memory_backend,
        )

    return {
        "best_rule": best_rule,
        "fitness": best_fitness,
        "metrics": final.get("metrics", {}),
        "rounds_run": rounds_run,
        "feature_gaps_found": feature_gaps,
    }


async def _vision_gap(
    fn_signals: list[str],
    pattern_name: str,
    carry: dict,
    project_dir: Path,
) -> str:
    """Run Vision on FN signal plots and aggregate suggested feature gaps."""
    from subagents.primitives.vision import vision

    plot_dir = project_dir / "tmp" / "plots"
    gaps: list[str] = []

    for sig_id in fn_signals[:5]:  # cap at 5 to limit Gemini calls
        plot_path = plot_dir / f"{sig_id}.png"
        if not plot_path.exists():
            continue
        result = await vision(
            image_path=plot_path,
            context={
                "signal_id": sig_id,
                "pattern": pattern_name,
                "current_rule": carry.get("best_rule", ""),
            },
        )
        gap = result.get("suggested_feature_gap", "none")
        if gap and gap != "none":
            gaps.append(gap)

    if not gaps:
        return "none"
    # return most common gap
    from collections import Counter
    return Counter(gaps).most_common(1)[0][0]


async def _synthesize_feature(
    feature_gap: str,
    project_dir: Path,
    v4cedars_lib: str,
) -> None:
    """Use the Code primitive to draft a new feature and move it to v4cedars lib."""
    from subagents.primitives.code import code

    output_dir = Path(v4cedars_lib) / "features" / "derived"
    await code(
        feature_gap_description=feature_gap,
        project_dir=project_dir,
        output_dir=output_dir,
    )
