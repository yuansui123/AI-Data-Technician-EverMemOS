"""
Web-UI-compatible trial view — Plotly version of trial_view_gui.py.

Loads all channel .npy signals for one trial, builds a stacked Plotly figure
grouped by brain region, color-coded by label status (reject=red, accept=dim,
unlabeled=region color). Existing labels are read from the LabelStore.

Can be used two ways:
  1. As a script — prints Plotly figure JSON to stdout:
       python trial_view_plotly.py --project-dir projects/CedarsP81 --trial-idx 0

  2. As an importable function:
       from tmpt.trial_view_plotly import build_trial_figure
       fig_dict = build_trial_figure(project_dir, trial_idx, ...)

The returned figure dict has `data` and `layout` keys (standard Plotly JSON).
Each trace has `customdata=[ch_idx]` so the web UI can identify clicked channels
via Plotly's plotly_click event.

Labeling is NOT handled here — that goes through the web app's WebSocket events
(label_signal, ask_user). This script only renders the view.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# ── Region definitions (mirrors trial_view_gui.py) ────────────────────────────

REGION_GROUPS = [
    {"name": "MTL Left",  "ids": [1, 3],       "color": "#00cc66", "color_dim": "#009944"},
    {"name": "MTL Right", "ids": [2, 4],       "color": "#99ff99", "color_dim": "#66dd88"},
    {"name": "MFC Left",  "ids": [5, 7, 9],    "color": "#3399ff", "color_dim": "#0066cc"},
    {"name": "MFC Right", "ids": [6, 8, 10],   "color": "#99ccff", "color_dim": "#6699dd"},
    {"name": "OFC Left",  "ids": [16],         "color": "#ff9933", "color_dim": "#cc6600"},
    {"name": "OFC Right", "ids": [17],         "color": "#ffcc88", "color_dim": "#ddaa55"},
    {"name": "IT Left",   "ids": [11],         "color": "#cc66ff", "color_dim": "#9933cc"},
    {"name": "IT Right",  "ids": [12],         "color": "#dd99ff", "color_dim": "#bb77dd"},
]

REJECT_COLOR   = "#ef4444"
BG_COLOR       = "#0d1117"
PLOT_BG_COLOR  = "#161b22"
TEXT_COLOR     = "#e2e8f0"
DIM_COLOR      = "#3a3a3a"


# ── Data loading helpers ───────────────────────────────────────────────────────

def _load_signals(signal_dir: Path, trial_idx: int, n_channels: int) -> dict[int, np.ndarray]:
    """Load all channel .npy files for a trial. Returns {ch_idx: signal_array}."""
    signals = {}
    for ch in range(n_channels):
        p = signal_dir / f"t{trial_idx:03d}_ch{ch:03d}.npy"
        if p.exists():
            signals[ch] = np.load(str(p)).astype(np.float64)
    return signals


def _load_labels(project_dir: Path) -> tuple[dict, dict]:
    """Load existing labels. Returns (rejected, accepted) dicts keyed by trial_idx."""
    rejected: dict[int, set] = {}   # trial_idx -> set(ch_idx)
    accepted: dict[int, set] = {}

    # Try label_store via v4cedars lib first
    v4cedars_lib = Path(r"C:\Users\yuans\Desktop\ClaudeCode\v4cedars\lib")
    if v4cedars_lib.exists() and str(v4cedars_lib) not in sys.path:
        sys.path.insert(0, str(v4cedars_lib.parent.parent))
    try:
        from lib.label_store import LabelStore
        ls = LabelStore(str(project_dir))
        for sig_id, info in ls.get_all_labels().items():
            parts = sig_id.split("_")
            if len(parts) < 2 or not parts[0].startswith("t") or not parts[1].startswith("ch"):
                continue
            try:
                t = int(parts[0][1:])
                ch = int(parts[1][2:])
            except ValueError:
                continue
            if info.get("category") == "reject":
                rejected.setdefault(t, set()).add(ch)
            elif info.get("category") == "accept":
                accepted.setdefault(t, set()).add(ch)
        return rejected, accepted
    except Exception:
        pass

    # Fallback: read feedback.json directly
    fb_path = project_dir / "feedback" / "feedback.json"
    if fb_path.exists():
        try:
            data = json.loads(fb_path.read_text())
            for entry in data:
                sig_id = entry.get("signal_id", "")
                parts = sig_id.split("_")
                if len(parts) < 2 or not parts[0].startswith("t") or not parts[1].startswith("ch"):
                    continue
                try:
                    t = int(parts[0][1:])
                    ch = int(parts[1][2:])
                except ValueError:
                    continue
                cat = entry.get("category", "")
                if cat == "reject":
                    rejected.setdefault(t, set()).add(ch)
                elif cat == "accept":
                    accepted.setdefault(t, set()).add(ch)
        except Exception:
            pass
    return rejected, accepted


def _build_plot_order(electrode_regions: np.ndarray) -> tuple[list, dict, dict]:
    """
    Build channel plot order grouped by brain region.
    Returns (plot_order, channel_colors, channel_regions).
    """
    plot_order = []
    channel_colors: dict[int, str] = {}
    channel_regions: dict[int, str] = {}

    n_channels = len(electrode_regions)
    assigned = set()
    for group in REGION_GROUPS:
        channels = [ch for ch in range(n_channels)
                    if int(electrode_regions[ch]) in group["ids"]]
        for ch in channels:
            plot_order.append(ch)
            channel_colors[ch] = group["color"]
            channel_regions[ch] = group["name"]
            assigned.add(ch)

    # Append any channels not in a known region
    for ch in range(n_channels):
        if ch not in assigned:
            plot_order.append(ch)
            channel_colors[ch] = "#888888"
            channel_regions[ch] = "Other"

    return plot_order, channel_colors, channel_regions


# ── Main figure builder ────────────────────────────────────────────────────────

def build_trial_figure(
    project_dir: str | Path,
    trial_idx: int,
    fs: float = 1000.0,
    channel_meta: dict | None = None,
    electrode_regions: np.ndarray | None = None,
    ground_truth: np.ndarray | None = None,
    rejected_override: dict | None = None,
    accepted_override: dict | None = None,
    selected_channels: set | None = None,
) -> dict:
    """
    Build a Plotly figure dict for one trial — all channels stacked vertically.

    Parameters
    ----------
    project_dir       Path to the project directory (contains signals/, feedback/).
    trial_idx         Trial index to display.
    fs                Sampling frequency in Hz.
    channel_meta      Dict of {chNNN: {region_name: ...}}. Auto-loaded if None.
    electrode_regions Numpy array of electrode region IDs per channel. Auto-loaded if None.
    ground_truth      Optional (n_channels, n_trials) binary bad-channel matrix.
    rejected_override Pre-loaded rejected labels dict (trial -> set(ch)) to skip file IO.
    accepted_override Pre-loaded accepted labels dict (trial -> set(ch)).
    selected_channels Set of currently selected channel indices (rendered white/bold).

    Returns
    -------
    dict with keys 'data' and 'layout' (valid Plotly figure JSON).
    """
    project_dir = Path(project_dir)
    signal_dir = project_dir / "signals"

    # ── Load metadata ──────────────────────────────────────────────────────────
    if electrode_regions is None:
        regions_path = signal_dir / "electrode_regions.npy"
        if regions_path.exists():
            electrode_regions = np.load(str(regions_path))
        else:
            raise FileNotFoundError(f"electrode_regions.npy not found in {signal_dir}")

    if channel_meta is None:
        meta_path = signal_dir / "channel_metadata.json"
        if meta_path.exists():
            channel_meta = json.loads(meta_path.read_text())
        else:
            channel_meta = {}

    n_channels = len(electrode_regions)

    # ── Labels ────────────────────────────────────────────────────────────────
    if rejected_override is not None and accepted_override is not None:
        rejected_all, accepted_all = rejected_override, accepted_override
    else:
        rejected_all, accepted_all = _load_labels(project_dir)

    rejected_chs = rejected_all.get(trial_idx, set())
    accepted_chs = accepted_all.get(trial_idx, set())
    selected_chs = selected_channels or set()

    # ── Plot order + colors ───────────────────────────────────────────────────
    plot_order, channel_colors, channel_regions = _build_plot_order(electrode_regions)

    # ── Load signals ──────────────────────────────────────────────────────────
    signals = _load_signals(signal_dir, trial_idx, n_channels)
    if not signals:
        return {
            "data": [],
            "layout": {
                "title": f"Trial {trial_idx} — No signals found",
                "paper_bgcolor": BG_COLOR,
                "plot_bgcolor": PLOT_BG_COLOR,
                "font": {"color": TEXT_COLOR},
            }
        }

    # ── Compute vertical spacing ──────────────────────────────────────────────
    all_ranges = [np.percentile(np.abs(sig), 99) for sig in signals.values()]
    spacing = float(np.median(all_ranges) * 3) if all_ranges else 500.0

    n_samples = len(next(iter(signals.values())))
    t = (np.arange(n_samples) / fs).tolist()

    # Epoch boundaries (samples)
    stim1_end = 3001 / fs
    stim2_end = 6002 / fs

    # ── Build Plotly traces ───────────────────────────────────────────────────
    traces = []
    shapes = []
    annotations = []
    current_region = None
    y_max = 0.0

    for plot_idx, ch in enumerate(plot_order):
        if ch not in signals:
            continue

        offset = plot_idx * spacing
        sig = (signals[ch] + offset).tolist()
        region = channel_regions[ch]
        y_max = max(y_max, max(sig))

        # Region separator line
        if region != current_region:
            if current_region is not None:
                sep_y = offset - spacing * 0.5
                shapes.append({
                    "type": "line",
                    "x0": 0, "x1": 1, "xref": "paper",
                    "y0": sep_y, "y1": sep_y,
                    "line": {"color": "#333", "width": 1, "dash": "dot"},
                })
            current_region = region

        # Color based on label status
        if ch in selected_chs:
            color = "#ffffff"
            lw = 2.5
            opacity = 1.0
        elif ch in rejected_chs:
            color = REJECT_COLOR
            lw = 1.0
            opacity = 1.0
        elif ch in accepted_chs:
            color = DIM_COLOR
            lw = 0.4
            opacity = 0.5
        else:
            color = channel_colors[ch]
            lw = 0.6
            opacity = 1.0

        # Label text for hover and right-axis annotation
        ch_name = channel_meta.get(f"ch{ch:03d}", {}).get("region_name", f"ch{ch}")
        status = ""
        if ch in selected_chs:
            status = " [SEL]"
        elif ch in rejected_chs:
            status = " [BAD]"
        elif ch in accepted_chs:
            status = " [OK]"
        label_text = f"ch{ch:02d} {ch_name}{status}"

        # Ground truth marker (prepend to label)
        if (ground_truth is not None
                and ch < ground_truth.shape[0]
                and trial_idx < ground_truth.shape[1]):
            gt_bad = bool(ground_truth[ch, trial_idx])
            label_text = ("⬤ " if gt_bad else "○ ") + label_text

        traces.append({
            "type": "scatter",
            "x": t,
            "y": sig,
            "mode": "lines",
            "line": {"color": color, "width": lw},
            "opacity": opacity,
            "name": label_text,
            "customdata": [[ch, region, ch_name, trial_idx]] * len(t),
            "hovertemplate": f"<b>{label_text}</b><br>t=%{{x:.3f}}s<extra></extra>",
            "showlegend": False,
        })

        # Right-side channel label annotation
        annotations.append({
            "x": 1.0,
            "y": offset,
            "xref": "paper",
            "yref": "y",
            "text": label_text,
            "showarrow": False,
            "xanchor": "left",
            "font": {"size": 8, "color": color, "family": "monospace"},
            "opacity": max(opacity, 0.6),
        })

    # ── Epoch boundary vertical lines ─────────────────────────────────────────
    for boundary, label in [(stim1_end, "stim2"), (stim2_end, "instr")]:
        shapes.append({
            "type": "line",
            "x0": boundary, "x1": boundary,
            "y0": 0, "y1": 1, "yref": "paper",
            "line": {"color": "#fbbf24", "width": 1, "dash": "dash"},
        })
        annotations.append({
            "x": boundary + 0.05,
            "y": 1.0,
            "xref": "x",
            "yref": "paper",
            "text": label,
            "showarrow": False,
            "font": {"color": "#fbbf24", "size": 9},
            "yanchor": "top",
        })

    # ── Region label annotations (left margin) ────────────────────────────────
    region_y: dict[str, list] = {}
    for plot_idx, ch in enumerate(plot_order):
        if ch in signals:
            r = channel_regions[ch]
            region_y.setdefault(r, []).append(plot_idx * spacing)

    for region_name, ys in region_y.items():
        mid_y = float(np.mean(ys))
        # Find region color
        color = "#888"
        for g in REGION_GROUPS:
            if g["name"] == region_name:
                color = g["color"]
                break
        annotations.append({
            "x": -0.01,
            "y": mid_y,
            "xref": "paper",
            "yref": "y",
            "text": region_name,
            "showarrow": False,
            "xanchor": "right",
            "font": {"size": 8, "color": color, "family": "monospace"},
            "textangle": -90,
        })

    # ── Status counts ─────────────────────────────────────────────────────────
    n_rej = len(rejected_chs)
    n_acc = len(accepted_chs)
    n_unl = n_channels - n_rej - n_acc
    title = (
        f"Trial {trial_idx} — All Channels  "
        f"({n_rej} bad / {n_acc} ok / {n_unl} unlabeled)"
    )
    if ground_truth is not None and trial_idx < ground_truth.shape[1]:
        n_gt_bad = int(ground_truth[:, trial_idx].sum())
        title += f"  |  GT: {n_gt_bad} bad"

    # ── Layout ────────────────────────────────────────────────────────────────
    x_max = t[-1] + 1.5 if t else 11.0
    layout = {
        "title": {"text": title, "font": {"color": TEXT_COLOR, "size": 13}},
        "paper_bgcolor": BG_COLOR,
        "plot_bgcolor": PLOT_BG_COLOR,
        "font": {"color": TEXT_COLOR},
        "xaxis": {
            "title": "Time (s)",
            "color": TEXT_COLOR,
            "gridcolor": "#222",
            "range": [-0.3 if ground_truth is not None else 0, x_max],
        },
        "yaxis": {
            "showticklabels": False,
            "showgrid": False,
            "zeroline": False,
        },
        "shapes": shapes,
        "annotations": annotations,
        "margin": {"l": 80, "r": 220, "t": 50, "b": 50},
        "hovermode": "closest",
        "dragmode": "pan",
        # Legend for regions (compact)
        "legend": {
            "orientation": "h",
            "y": -0.05,
            "font": {"size": 8},
        },
    }

    # Add dummy region traces for the legend
    for group in REGION_GROUPS:
        traces.append({
            "type": "scatter",
            "x": [None], "y": [None],
            "mode": "lines",
            "line": {"color": group["color"], "width": 2},
            "name": group["name"],
            "showlegend": True,
        })

    return {"data": traces, "layout": layout}


# ── CLI entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Web-UI-compatible trial view (Plotly JSON)")
    parser.add_argument("--project-dir", required=True, help="Project directory path")
    parser.add_argument("--trial-idx", type=int, default=0, help="Trial index to display")
    parser.add_argument("--fs", type=float, default=1000.0, help="Sampling frequency (Hz)")
    parser.add_argument("--ground-truth", default=None,
                        help="Path to .mat bad_trials file (n_channels × n_trials binary)")
    args = parser.parse_args()

    ground_truth = None
    if args.ground_truth:
        import scipy.io as sio
        gt_data = sio.loadmat(args.ground_truth)
        ground_truth = gt_data["bad_trials"].astype(np.uint8)

    fig = build_trial_figure(
        project_dir=args.project_dir,
        trial_idx=args.trial_idx,
        fs=args.fs,
        ground_truth=ground_truth,
    )
    print(json.dumps(fig))


if __name__ == "__main__":
    main()
