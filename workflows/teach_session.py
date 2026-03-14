"""Workflow: teach_session — web-compatible interactive signal labelling.

Emits label_signal WebSocket events one signal at a time.
Frontend shows a modal popup; user clicks a label button to respond.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

# Default Plotly reference script — used when the agent doesn't pass an explicit ref_file_path.
# CodeGen reads this as a style guide so it knows the expected output format.
_DEFAULT_PLOT_REF = Path(__file__).resolve().parent.parent / "tmpt" / "trial_view_plotly.py"


async def teach_session(
    project_dir: str | Path,
    memory_backend=None,
    pattern: str | None = None,
    data_dir: str | Path | None = None,
    n_signals: int = 10,
    on_event=None,
    answer_queue=None,
    plot_script: str | None = None,
    view_description: str | None = None,
    ref_file_path: str | Path | None = None,
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

    # ── View selection (only if no plot_script was pre-supplied) ─────────────
    if plot_script is None:
        if view_description:
            # Orchestrator already collected the user's view preference — use it directly
            view_desc = view_description
        else:
            await on_event({
                "type": "ask_user",
                "question": (
                    "**How would you like each signal displayed?**\n\n"
                    "Describe freely — for example:\n"
                    "- `default` — single channel time-series (fastest)\n"
                    "- `all channels stacked vertically for this trial`\n"
                    "- `MTL channels only, offset-stacked`\n"
                    "- `similar to my script at C:\\path\\to\\plot_script.py`\n"
                    "- `similar to the GUI in the user folder`"
                ),
            })
            try:
                view_desc = (await asyncio.wait_for(answer_queue.get(), timeout=180)).strip()
            except asyncio.TimeoutError:
                view_desc = "default"

        if view_desc.lower() not in ("default", "skip", ""):
            import numpy as np
            from subagents.reasoners.codegen import codegen
            rng_preview = np.random.default_rng()
            preview_mat = mat_files[rng_preview.integers(len(mat_files))]
            dims = await _get_dims(preview_mat, bash, project_dir)
            tr_p = int(rng_preview.integers(dims[2])) if dims else 0
            ch_p = int(rng_preview.integers(dims[1])) if dims else 0

            # CodeGen: generate → run → fix loop (shows progress in activity log via on_event)
            _ref = ref_file_path or (_DEFAULT_PLOT_REF if _DEFAULT_PLOT_REF.exists() else None)
            plot_script = await codegen(
                description=view_desc,
                mat_path=preview_mat,
                ch_idx=ch_p,
                tr_idx=tr_p,
                project_dir=project_dir,
                dims=dims,
                ref_file_path=_ref,
                on_event=on_event,
            )
            if plot_script:
                # CodeGen already verified the script runs — read the JSON it produced
                preview_json, preview_err = await _run_plot_script(
                    plot_script, preview_mat, ch_p, tr_p, bash, project_dir
                )
                if preview_json:
                    await on_event({"type": "show_plot", "plot_json": preview_json,
                                    "title": f"Preview — {preview_mat.stem} tr{tr_p}",
                                    "trial_idx": tr_p})
                    await on_event({"type": "ask_user",
                                    "question": "Does this layout look good? Reply `yes` to start, `default` to use single-channel, or describe a change."})
                    try:
                        confirm = (await asyncio.wait_for(answer_queue.get(), timeout=180)).strip().lower()
                        if confirm == "default":
                            plot_script = None
                        elif confirm != "yes":
                            # Refine: new CodeGen pass with prior script and user feedback
                            plot_script = await codegen(
                                description=confirm,
                                mat_path=preview_mat,
                                ch_idx=ch_p,
                                tr_idx=tr_p,
                                project_dir=project_dir,
                                dims=dims,
                                ref_file_path=_ref,
                                prior_script=plot_script,
                                on_event=on_event,
                            )
                            if plot_script:
                                refined_json, _ = await _run_plot_script(
                                    plot_script, preview_mat, ch_p, tr_p, bash, project_dir
                                )
                                if refined_json:
                                    await on_event({"type": "show_plot", "plot_json": refined_json,
                                                    "title": f"Refined preview — {preview_mat.stem}",
                                                    "trial_idx": tr_p})
                                else:
                                    await on_event({"type": "ask_user",
                                                    "question": "⚠️ Refined script failed. Keeping previous layout."})
                    except asyncio.TimeoutError:
                        pass  # keep current plot_script
                else:
                    await on_event({"type": "ask_user",
                                    "question": f"⚠️ Plot render failed after generation — falling back to default.\n\n`{preview_err}`"})
                    plot_script = None
            else:
                await on_event({"type": "ask_user",
                                "question": "⚠️ CodeGen could not produce a working plot script — falling back to default single-channel view."})

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

        # Generate interactive Plotly figure (custom script or default)
        if plot_script:
            plot_json, _ = await _run_plot_script(plot_script, mat_path, ch_idx, tr_idx, bash, project_dir)
        else:
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

def _extract_ref_filename(description: str) -> str | None:
    """Return just the filename if description references a file path, else None."""
    import re
    m = re.search(r'[A-Za-z]:[\\\/][^\s\'"*?]+\.(py|m|txt|md)', description)
    return Path(m.group(0)).name if m else None


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


async def _run_plot_script(script: str, mat_path: Path, ch_idx: int, tr_idx: int,
                           bash_fn, cwd) -> tuple[str | None, str | None]:
    """Run a user-supplied plot script with mat_path/ch_idx/tr_idx pre-defined.

    Returns (plot_json, error_msg). Uses base64 to avoid PowerShell here-string
    breakage from LLM-generated code containing apostrophes or '@' sequences.
    """
    import base64
    header = "\n".join([
        "import json",
        f"mat_path = r'{mat_path}'",
        f"ch_idx = {ch_idx}",
        f"tr_idx = {tr_idx}",
    ])
    py = header + "\n" + script
    encoded = base64.b64encode(py.encode("utf-8")).decode("ascii")
    # Write script via base64 decode (avoids all PowerShell quoting issues)
    write_cmd = (
        f"python -c \"import base64,pathlib; pathlib.Path('C:/Windows/Temp/custom_plot.py')"
        f".write_bytes(base64.b64decode('{encoded}'))\""
    )
    # Run script, capturing stderr separately so we can show it on failure
    run_cmd = (
        "python C:/Windows/Temp/custom_plot.py 2>C:/Windows/Temp/custom_plot_err.txt; "
        "$ec=$LASTEXITCODE; "
        "$err=if(Test-Path C:/Windows/Temp/custom_plot_err.txt)"
        "{Get-Content C:/Windows/Temp/custom_plot_err.txt -Raw}else{''}; "
        "if($ec -ne 0 -or $err){Write-Host \"STDERR:$err\" -NoNewline}"
    )
    result = await bash_fn(f"{write_cmd}\n{run_cmd}", cwd=str(cwd))
    stdout = result.stdout or ""
    # Separate plot JSON from any STDERR marker we injected
    plot_out = ""
    stderr_out = ""
    if "STDERR:" in stdout:
        parts = stdout.split("STDERR:", 1)
        plot_out = parts[0].strip()
        stderr_out = parts[1].strip()
    else:
        plot_out = stdout.strip()

    if plot_out:
        try:
            json.loads(plot_out)
            return plot_out, None
        except Exception as e:
            return None, f"Script output not valid JSON: {e}\nstdout: {plot_out[:300]}\nstderr: {stderr_out[:300]}"

    if stderr_out:
        return None, f"Script error:\n{stderr_out[:600]}"
    return None, "Script ran but produced no output (missing print(json.dumps(fig))?)."


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


async def _generate_plot_script(
    description: str,
    project_dir: Path,
    sample_mat: Path,
    dims: tuple | None,
    bash_fn,
    cwd,
    prior_script: str | None = None,
    ref_file_path: str | Path | None = None,
) -> str | None:
    """Ask an LLM to write a Plotly plot_script from the user's description."""
    import re
    from subagents.base import SubagentConfig, invoke
    import config as cfg

    # Project summary for dataset context
    summary = ""
    summary_path = project_dir / "project_summary.md"
    if summary_path.exists():
        summary = summary_path.read_text(encoding="utf-8")[:3000]

    # Reference file: prefer explicit ref_file_path, fall back to path in description
    ref_code = ""
    ref_path = None
    if ref_file_path:
        ref_path = Path(ref_file_path)
    else:
        path_match = re.search(r'[A-Za-z]:[\\\/][^\s\'"*?]+\.(py|m|txt|md)', description)
        if path_match:
            ref_path = Path(path_match.group(0))

    if ref_path and ref_path.exists():
        lang = "matlab" if ref_path.suffix == ".m" else "python"
        note = " (MATLAB — translate the visualization logic to Python/Plotly)" if lang == "matlab" else ""
        ref_code = (
            f"\n\nReference file `{ref_path.name}`{note}:\n```{lang}\n"
            f"{ref_path.read_text(errors='replace')[:6000]}\n```"
        )

    T, C, N = dims if dims else ("?", "?", "?")
    prior_section = (
        f"\n\nPrevious attempt (refine based on feedback):\n```python\n{prior_script}\n```"
        if prior_script else ""
    )

    prompt = f"""Write Python code for a signal labelling plot.

## Dataset context
{summary or "(no summary available)"}

## Sample file
Path: `{sample_mat}`
Shape: T={T} timepoints × C={C} channels × N={N} trials
h5py keys: `epoched_data` (T×C×N), `time` (T,), `new_elect_vals` (C,) — electrode region codes{ref_code}{prior_section}

## Pre-defined variables (do NOT redefine)
- `mat_path` (str) — path to the current .mat file
- `ch_idx` (int) — a randomly selected channel index
- `tr_idx` (int) — a randomly selected trial index

## User's view request
{description}

## Requirements
1. Read data with h5py using `mat_path`
2. Build a Plotly figure dict (`fig`) with keys `data` and `layout`
3. Dark theme: `paper_bgcolor='#0d1117'`, `plot_bgcolor='#161b22'`, `font=dict(color='#e2e8f0')`
4. End with exactly: `print(json.dumps(fig))`
5. Import json at the top
6. Keep the script self-contained and complete — do not truncate

Return ONLY raw Python code — no markdown fences, no explanation."""

    has_ref = bool(ref_code)
    sc = SubagentConfig(
        model=cfg.CODE_MODEL,
        system_prompt="You are a Python code generator. Return only raw Python code with no markdown fences or explanation.",
        max_tokens=4000 if has_ref else 2500,
        max_iterations=1,
    )
    result = await invoke(sc, [{"role": "user", "content": prompt}])
    code = result.text.strip()
    # Strip accidental markdown fences
    code = re.sub(r'^```\w*\s*', '', code)
    code = re.sub(r'\s*```$', '', code)
    code = code.strip()
    if not code:
        return None
    # Syntax-check before returning — catch truncated/broken code early
    try:
        compile(code, "<generated>", "exec")
    except SyntaxError as e:
        return None  # caller will surface this as a generation failure
    return code
