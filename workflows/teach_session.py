"""Workflow: teach_session — web-compatible interactive signal labelling.

Emits label_signal WebSocket events one signal at a time.
Frontend shows a modal popup; user clicks a label button to respond.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path


async def teach_session(
    project_dir: str | Path,
    memory_backend=None,
    pattern: str | None = None,
    data_dir: str | Path | None = None,
    n_signals: int = 10,
    on_event=None,
    answer_queue=None,
) -> dict:
    """Show signals one-by-one via modal popup, collect user labels.

    Returns {labels_added, total_labels, labels_path, summary_updated}.
    """
    from subagents.primitives.bash import bash
    from subagents.reasoners.think import think

    project_dir = Path(project_dir)
    labels_path = project_dir / "feedback" / "labels.json"
    labels_path.parent.mkdir(parents=True, exist_ok=True)

    if answer_queue is None or on_event is None:
        return {
            "response": (
                "Interactive labelling requires the web interface. "
                "Open the system at http://localhost:8000 and try again."
            )
        }

    # Find .mat files
    mat_files = _find_mat_files(data_dir)
    if not mat_files:
        return {
            "response": (
                f"No .mat files found in data_dir={data_dir!r}. "
                "Please provide a valid data_dir pointing to a folder or file."
            )
        }

    # Load existing labels
    existing: dict = {}
    if labels_path.exists():
        try:
            existing = json.loads(labels_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    new_labels = dict(existing)

    # Build button options
    if pattern:
        options = [pattern, f"not_{pattern}", "unsure", "skip"]
    else:
        options = ["clean", "artifact", "noise", "unsure", "skip"]

    labelled_count = 0
    import numpy as np
    rng = np.random.default_rng()

    for i in range(n_signals):
        mat_path = mat_files[rng.integers(len(mat_files))]

        # Get tensor dimensions
        dims = await _get_dims(mat_path, bash, project_dir)
        if dims is None:
            continue
        T, C, N = dims
        ch_idx = int(rng.integers(C))
        tr_idx = int(rng.integers(N))

        # Generate interactive Plotly figure
        plot_json = await _plot_signal(mat_path, ch_idx, tr_idx, bash, project_dir)
        if not plot_json:
            continue

        signal_id = f"{mat_path.parent.name}/{mat_path.stem}/ch{ch_idx}/tr{tr_idx}"

        # Emit label_signal event — frontend shows popup with interactive chart
        await on_event({
            "type": "label_signal",
            "plot_json": plot_json,
            "signal_id": signal_id,
            "options": options,
            "context_text": f"{mat_path.parent.name} · {mat_path.stem} · channel {ch_idx} · trial {tr_idx}",
            "progress": f"{i + 1} / {n_signals}",
        })

        # Wait for user to click a button (5-minute timeout per signal)
        try:
            label = await asyncio.wait_for(answer_queue.get(), timeout=300)
        except asyncio.TimeoutError:
            await on_event({
                "type": "ask_user",
                "question": "Labelling session timed out. Saving labels collected so far.",
            })
            break

        label = label.strip().lower()
        if label == "skip":
            continue

        new_labels[signal_id] = {
            "label": label,
            "mat_path": str(mat_path),
            "ch_idx": ch_idx,
            "tr_idx": tr_idx,
            "pattern": pattern or "general",
        }
        labelled_count += 1

    # Persist labels
    labels_path.write_text(json.dumps(new_labels, indent=2), encoding="utf-8")

    # Update project summary
    if memory_backend:
        await think(
            content=(
                f"Labelling session completed. Added {labelled_count} new labels "
                f"({len(new_labels)} total). Pattern: {pattern or 'general'}."
            ),
            section="Labeling History",
            memory_backend=memory_backend,
        )

    return {
        "labels_added": labelled_count,
        "total_labels": len(new_labels),
        "labels_path": str(labels_path),
        "summary_updated": memory_backend is not None,
        "response": (
            f"Labelling session complete. Added {labelled_count} new labels "
            f"({len(new_labels)} total in {labels_path.name})."
        ),
    }


# ── helpers ────────────────────────────────────────────────────────────────────

def _find_mat_files(data_dir) -> list[Path]:
    if not data_dir:
        return []
    p = Path(data_dir)
    if p.is_file() and p.suffix == ".mat":
        return [p]
    return sorted(p.rglob("*.mat")) if p.is_dir() else []


async def _get_dims(mat_path: Path, bash_fn, cwd) -> tuple | None:
    py = "\n".join([
        "import h5py, numpy as np",
        f"with h5py.File(r'{mat_path}', 'r') as f:",
        "    s = f['epoched_data'].shape",
        "print(s[0], s[1], s[2])",
    ])
    cmd = (
        f"$code = @'\n{py}\n'@\n"
        "$code | Out-File -Encoding utf8 C:\\Windows\\Temp\\get_dims.py\n"
        "python C:\\Windows\\Temp\\get_dims.py"
    )
    result = await bash_fn(cmd, cwd=str(cwd))
    if result.ok and result.stdout.strip():
        try:
            parts = result.stdout.strip().split()
            return int(parts[0]), int(parts[1]), int(parts[2])
        except Exception:
            pass
    return None


async def _plot_signal(mat_path: Path, ch_idx: int, tr_idx: int,
                       bash_fn, cwd) -> str | None:
    """Return a Plotly figure as a JSON string, or None on failure."""
    subj = mat_path.parent.name
    epoch = mat_path.stem.replace("epoched_data_", "")
    title = f"{subj} {epoch} ch{ch_idx} tr{tr_idx}"
    py = "\n".join([
        "import h5py, numpy as np, json",
        f"with h5py.File(r'{mat_path}', 'r') as f:",
        "    data = f['epoched_data'][:]",
        "    time = np.array(f['time']).squeeze().tolist()",
        f"sig = data[:, {ch_idx}, {tr_idx}].astype(float).tolist()",
        "fig = dict(",
        "    data=[dict(",
        "        type='scatter', x=time, y=sig,",
        "        mode='lines',",
        "        line=dict(color='#4fc3f7', width=1),",
        f"        name='ch{ch_idx} tr{tr_idx}',",
        "    )],",
        "    layout=dict(",
        "        paper_bgcolor='#0d1117',",
        "        plot_bgcolor='#161b22',",
        "        font=dict(color='#e2e8f0'),",
        "        xaxis=dict(",
        "            title='Time (s)', color='#94a3b8', gridcolor='#30363d',",
        "            zerolinecolor='#f85149', zerolinewidth=2,",
        "        ),",
        "        yaxis=dict(title='uV', color='#94a3b8', gridcolor='#30363d'),",
        f"        title=dict(text='{title}', font=dict(size=13)),",
        "        margin=dict(l=60, r=20, t=40, b=50),",
        "        hovermode='x unified',",
        "    )",
        ")",
        "print(json.dumps(fig))",
    ])
    cmd = (
        f"$code = @'\n{py}\n'@\n"
        "$code | Out-File -Encoding utf8 C:\\Windows\\Temp\\plot_label.py\n"
        "python C:\\Windows\\Temp\\plot_label.py"
    )
    result = await bash_fn(cmd, cwd=str(cwd))
    if result.ok and result.stdout.strip():
        try:
            json.loads(result.stdout.strip())  # validate
            return result.stdout.strip()
        except Exception:
            pass
    return None
