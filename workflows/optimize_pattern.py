"""Workflow: optimize_pattern

Sequence:
  1. Task agent: compute features + baseline rule evaluation
  2. Loop (up to N_ROUNDS):
     a. Task agent: LASR optimization → candidate rules + FP/FN signals
     b. If plateau: Vision × FN signals → suggested_feature_gap
     c. If feature_gap: Task agent → new feature draft → Bash → recompute features
     d. Think: update project_memory.md after each round
  3. Task agent: final evaluation of best rule
  4. Think: store final rule + metrics to project_memory.md
"""
from __future__ import annotations

import json
from pathlib import Path

N_ROUNDS = 5


def _parse_task_json(text: str) -> dict:
    """Parse JSON from task agent response, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text, "parse_error": True}


async def optimize_pattern(
    pattern_name: str,
    project_dir: str | Path,
    memory_backend=None,
    context_carry: dict | None = None,
) -> dict:
    """Run the full LASR-based optimization loop for *pattern_name*.

    Returns {best_rule, fitness, metrics, rounds_run, feature_gaps_found}.
    """
    from agents.task import task
    from agents.think import think
    from tools.vision import vision
    from tools.bash import bash
    import config

    project_dir = Path(project_dir)
    cache_dir = project_dir / "cache"
    feature_matrix_path = str(cache_dir / "feature_matrix.parquet")

    best_rule: str = (context_carry or {}).get("best_rule", "")
    best_fitness: float = 0.0
    rounds_run = 0
    feature_gaps: list[str] = []

    # Step 1 — baseline
    baseline_text = await task(
        task_description=(
            f"Compute feature matrix for pattern '{pattern_name}' and evaluate "
            f"current best rule if any.\n"
            f"Feature matrix path: {feature_matrix_path}\n"
            f"Project directory: {project_dir}\n\n"
            "Return JSON with keys: best_rule, fitness, fp_signals, fn_signals."
        ),
        project_dir=project_dir,
    )
    baseline = _parse_task_json(baseline_text)

    # Step 2 — optimization loop
    for round_i in range(1, N_ROUNDS + 1):
        rounds_run = round_i

        opt_text = await task(
            task_description=(
                f"Run LASR optimization for pattern '{pattern_name}'.\n"
                f"Feature matrix path: {feature_matrix_path}\n"
                f"Project directory: {project_dir}\n"
                f"Current best rule: {best_rule or 'none'}\n"
                f"Current best fitness: {best_fitness}\n\n"
                "Identify FP and FN signals. Set plateau=true if fitness "
                "has not improved over 3 iterations.\n\n"
                "Return JSON with keys: best_rule, fitness, fp_signals, fn_signals, "
                "plateau, is_terminal."
            ),
            project_dir=project_dir,
        )
        opt_result = _parse_task_json(opt_text)

        new_fitness = float(opt_result.get("fitness", 0.0))
        if new_fitness > best_fitness:
            best_fitness = new_fitness
            best_rule = opt_result.get("best_rule", best_rule)

        # plateau → Vision on FN signals
        if opt_result.get("plateau"):
            fn_signals: list[str] = opt_result.get("fn_signals", [])
            feature_gap = await _vision_gap(fn_signals, pattern_name, best_rule, project_dir)
            if feature_gap and feature_gap != "none":
                feature_gaps.append(feature_gap)
                # Task agent → new feature
                await _synthesize_feature(feature_gap, project_dir, config.V4CEDARS_LIB)
                # Recompute feature matrix
                await bash(
                    f'python -c "import sys; sys.path.insert(0,r\"{config.V4CEDARS_LIB}\"); '
                    f'from feature_store import FeatureStore; '
                    f'FeatureStore(r\"{project_dir}\").recompute(force=True)"',
                    cwd=str(project_dir),
                )

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
    final_text = await task(
        task_description=(
            f"Final evaluation of best rule '{best_rule}' for pattern '{pattern_name}'.\n"
            f"Feature matrix path: {feature_matrix_path}\n"
            f"Project directory: {project_dir}\n\n"
            "Return JSON with keys: best_rule, fitness, metrics."
        ),
        project_dir=project_dir,
    )
    final = _parse_task_json(final_text)

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
    current_rule: str,
    project_dir: Path,
) -> str:
    """Run Vision on FN signal plots and aggregate suggested feature gaps."""
    from tools.vision import vision

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
                "current_rule": current_rule,
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
    """Use the Task agent to draft a new feature and write it to v4cedars lib."""
    from agents.task import task

    output_dir = Path(v4cedars_lib) / "features" / "derived"
    output_dir.mkdir(parents=True, exist_ok=True)

    await task(
        task_description=(
            f"Write a Python feature extraction function for: {feature_gap}\n\n"
            f"Use the v4cedars @feature decorator pattern:\n"
            "```python\n"
            "import numpy as np\n"
            "from features import feature\n\n"
            '@feature(name="my_feature", category="spectral")\n'
            "def my_feature(signal: np.ndarray, fs: float, **kwargs) -> float:\n"
            '    """One-sentence description."""\n'
            "    return float(result)\n"
            "```\n\n"
            f"Write the file to: {output_dir}\n"
            "Use only numpy, scipy, antropy, mne — no new pip installs.\n"
            "Handle edge cases (empty signal, NaN) → return np.nan."
        ),
        project_dir=project_dir,
    )
