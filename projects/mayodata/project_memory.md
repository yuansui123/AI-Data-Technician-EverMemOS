

## Dataset
- **Location:** `C:\Users\yuans\Desktop\ClaudeCode\v3mayo\user\MayoData1000`
- **Signals folder:** `MayoData1000/signals/` — **1,000 `.mat` files**
- **File format:** MATLAB `.mat`; each file contains a **1D iEEG signal array**, shape `(15,000,)`, dtype `float32`
- **Sampling rate:** **5,000 Hz (5 kHz)**
- **Duration per signal:** **3 seconds** (15,000 samples ÷ 5,000 Hz)
- **Labels:** Each signal has a **SOZ label** (0 = non-SOZ, 1 = SOZ — Seizure Onset Zone)
- **Metadata fields observed:** Patient ID, brain region (e.g., Right Hippocampus), SOZ status
- **Example file:** `x046343.mat` — Patient 7, Right Hippocampus, SOZ = 0

---

## Project Goal
- Classify iEEG signals as **SOZ vs. non-SOZ** using the MayoData1000 dataset
- Domain: **epilepsy surgery planning** — identifying brain regions where seizures originate

---

## Analysis & Visualisation
- **Raw time series**, **spectrogram**, and **PSD** computed on signal `x046343` (Right Hippocampus, non-SOZ)
- Non-SOZ hippocampal signal showed smooth amplitude fluctuation — typical baseline activity

### Spectrogram Preferred Parameters
| Parameter | Value | Rationale |
|---|---|---|
| `nperseg` | **256** | Finer time slices → sharper vertical bands |
| `noverlap` | **240** (93%) | High overlap → smooth time resolution |
| Colormap/scale | enhanced contrast | Better vertical power-band brightness |

> User preference: high time-resolution spectrogram with clear vertical power-band structure.
