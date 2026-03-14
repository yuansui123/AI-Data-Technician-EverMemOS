"""Workflow: apply_rules

Applies all saved classification rules to the full signal set and writes
a predictions CSV to projects/{Name}/cache/predictions.csv.

Sequence:
  1. Bash: load feature matrix + rules → apply → write predictions.csv
  2. Think: store prediction stats to project_summary.md §Applied Rules
"""
from __future__ import annotations

from pathlib import Path


async def apply_rules(
    project_dir: str | Path,
    memory_backend=None,
    pattern: str | None = None,
    output_path: str | Path | None = None,
) -> dict:
    """Apply saved rules to all signals and persist predictions.

    Returns {predictions_path, n_classified, n_signals, stats}.
    """
    import config
    from tools.bash import bash
    from agents.think import think

    project_dir = Path(project_dir)
    output_path = Path(output_path) if output_path else project_dir / "cache" / "predictions.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rules_path = project_dir / "rules" / "classification.json"
    feature_matrix_path = project_dir / "cache" / "feature_matrix.parquet"

    apply_cmd = (
        f'python -c "'
        f'import sys, json, pandas as pd; '
        f'sys.path.insert(0, r\"{config.V4CEDARS_LIB}\"); '
        f'from rules import RuleEngine; '
        f'fm = pd.read_parquet(r\"{feature_matrix_path}\"); '
        f'rules = json.loads(open(r\"{rules_path}\").read()); '
        f're = RuleEngine(rules); '
        f'preds = re.apply(fm, pattern={repr(pattern)}); '
        f'preds.to_csv(r\"{output_path}\", index=True); '
        f'print(f\"Classified {{preds.shape[0]}} signals\")"'
    )

    result = await bash(apply_cmd, cwd=str(project_dir))

    n_classified = 0
    if result.ok and output_path.exists():
        import csv
        with output_path.open() as f:
            n_classified = sum(1 for _ in csv.reader(f)) - 1  # subtract header

    stats = {
        "n_classified": n_classified,
        "predictions_path": str(output_path),
        "bash_ok": result.ok,
        "stderr": result.stderr[:300] if result.stderr else "",
    }

    if memory_backend:
        await think(
            content=(
                f"Applied classification rules to project '{project_dir.name}'. "
                f"Pattern filter: {pattern or 'all'}. "
                f"Signals classified: {n_classified}. "
                f"Predictions saved to: {output_path}."
            ),
            section="Applied Rules",
            memory_backend=memory_backend,
        )

    return stats
