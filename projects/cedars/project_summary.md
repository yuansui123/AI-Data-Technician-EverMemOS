

## Dataset Overview
## Dataset Exploration Summary

- **Files & Format:** 6 data files across 2 subjects (P81, P86), stored as MATLAB v7.3 HDF5 `.mat` files. **Exact absolute path pattern:** `C:\Users\yuans\Desktop\ClaudeCode\v4cedars\user\CedarsData\data\{subj}\epoched_data_{epoch}.mat` where `{subj}` ∈ {P81, P86} and `{epoch}` ∈ {stim1, stim2, instr}. Example: `C:\Users\yuans\Desktop\ClaudeCode\v4cedars\user\CedarsData\data\P81\epoched_data_stim1.mat`. HDF5 keys: `epoched_data` (main tensor), `fs`, `time`, `new_elect_vals`. A companion PDF (Kim et al., 2025, 7.4 MB) and a MATLAB bad-trial marking script (`sfc_mark_bad_trials_v3_viewing_only.m`, 8.2 KB) are also present at `C:\Users\yuans\Desktop\ClaudeCode\v4cedars\user\CedarsData\`.

- **Signal Dimensions:** Data tensors are shaped **[timepoints × channels × trials]** — 192 trials per epoch per subject, sampled at **1000 Hz**. Stim epochs span −1.0 to +2.0 s (3,001 samples); instruction epochs span −1.0 to +3.5 s (4,501 samples). Channel counts: P81 = **88**, P86 = **84**, covering MTL (L/R), MFC (L/R), and IT (L/R) regions.

- **Scientific Context:** Human intracranial LFP from epilepsy patients at Cedars-Sinai. Task: flexible visual decision-making with early vs. late instruction timing, designed to probe **dACC → VTC top-down modulation**. This sample is 2 of 11 total patients.

- **Data Quality — P86 Flag:** P86 shows amplitude swings of ±33,000 µV vs. ±16,000 µV for P81 — roughly **2× wider**, strongly suggesting artifactual channels, electrode pop/clipping events, or a different reference scheme. P86 channels warrant priority inspection.

- **Artifact Labeling is Incomplete:** The expected `bad_trials_combined.mat` file is **absent** for both subjects. The interactive bad-trial marking workflow exists in the `.m` script but has not yet been run — no clean trial index is currently available.

- **Suggested Next Steps:**
  1. Run artifact detection on P86 channels (amplitude threshold screening, visual inspection of outlier channels).
  2. Execute or adapt `sfc_mark_bad_trials_v3_viewing_only.m` to generate `bad_trials_combined.mat` for both subjects.
  3. Validate trial condition labels (early vs. late instruction) and confirm trial counts balance across conditions within the 192-trial sets.
  4. Compute baseline-corrected ERPs at stimulus onset (t = 0) as a sanity check before any spectral or connectivity analysis.

## Labeling History
```markdown
## Labelling Session — Pattern Discovery
- **9 labels added** (9 total) in first labelling session; all labels share the pattern `low_variability`.
- Pattern uniformity suggests the initial sample is drawn from a homogeneous region of the data distribution — no high-variability or mixed examples captured yet.
- **Implication:** Next step should actively seek out high-variability or edge-case examples to diversify the label set and avoid a biased training signal.
```
