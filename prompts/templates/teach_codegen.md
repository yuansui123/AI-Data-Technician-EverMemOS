Write Python code for a signal labelling plot.

## Dataset context
{summary}

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

Return ONLY raw Python code — no markdown fences, no explanation.