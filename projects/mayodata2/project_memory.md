

## Spectrogram
## iEEG Spectrogram Parameters (MayoData1000 / mayodata2 projects)

Optimized for revealing transient power bursts and vertical banding in iEEG signals.

### scipy.signal.spectrogram settings:
- `nperseg = 250` (50ms window at 5kHz — sharp time resolution)
- `noverlap = 240` (96% overlap — smooth time axis without smearing)
- `fs = 5000` (5 kHz sampling rate)

### Display settings:
- `colormap = 'inferno'` (high perceived contrast)
- `vmin = np.percentile(Sxx_db, 30)` (clips noise floor)
- `vmax = np.percentile(Sxx_db, 99.5)` (makes transient bursts pop)
- `shading = 'gouraud'` (smooth interpolation between time bins)
- Frequency range displayed: 0–600 Hz
- Power in dB: `10 * np.log10(Sxx + 1e-12)`

### HFO marker lines on spectrogram:
- Cyan dashed line at **80 Hz** (ripple threshold)
- Magenta dashed line at **200 Hz** (fast ripple threshold)

### Rationale:
- Small nperseg (250) gives temporal resolution sharp enough to show transient epileptiform spikes as bright vertical bands
- High overlap (240/250 = 96%) ensures smooth time axis
- Percentile-based vmin/vmax clips the noise floor and highlights bursts of power
- inferno colormap has higher perceptual contrast than viridis for bright/dark discrimination

### Example code:
```python
from scipy.signal import spectrogram
import numpy as np

fs = 5000
f, t, Sxx = spectrogram(signal, fs=fs, nperseg=250, noverlap=240)
Sxx_db = 10 * np.log10(Sxx + 1e-12)
vmin = np.percentile(Sxx_db, 30)
vmax = np.percentile(Sxx_db, 99.5)

ax.pcolormesh(t, f, Sxx_db, shading='gouraud', cmap='inferno', vmin=vmin, vmax=vmax)
ax.set_ylim(0, 600)
ax.axhline(80, color='cyan', linestyle='--', linewidth=1)
ax.axhline(200, color='magenta', linestyle='--', linewidth=1)
```

## Project Overview
- **Started:** 2026-03-16. Researcher + AI Data Technician analyzing the MayoData1000 multicenter iEEG dataset.
- **Goal:** Artifact detection, pathological signal identification, and feature engineering for SOZ (Seizure Onset Zone) classification.
- **Status:** Exploratory phase — visual inspection, spectrogram analysis, and feature proposal underway.

---

## Dataset: MayoData1000
- **Path:** `<dataset_root>/MayoData1000`
- **Source:** Multicenter intracranial EEG (iEEG) — Mayo Clinic (Nejedly et al., *Scientific Data*, 2020)
- **Signals folder:** `/signals/` — **1,000 `.mat` files**, each named by signal ID (e.g., `x046608.mat`)
- **Loading:** Use `scipy.io.loadmat(filepath)` — key fields include raw time-series data, channel label, patient ID, and SOZ label
- **Sampling rate:** **5,000 Hz (5 kHz)**
- **Duration per signal:** **3 seconds → 15,000 samples**
- **Data shape per file:** `(15000,)` time-series array (single channel)
- **Metadata fields per file:** channel name (e.g., `RD1_1`), patient ID (e.g., Patient 7), brain region (e.g., Right Hippocampus), SOZ label (`0` = non-SOZ, `1` = SOZ)
- **Electrode types:** depth electrodes and strip/grid electrodes across multiple brain regions
- **Labels:** Binary SOZ classification label per signal

## Key Concepts
- **SOZ (Seizure Onset Zone):** The brain region where epileptic seizures originate. Clinically identified via iEEG in patients with drug-resistant epilepsy (DRE) as a surgical resection target. Labels in this dataset mark each signal channel as SOZ (`1`) or non-SOZ (`0`) based on clinical consensus.

## Analysis Log
- **Signal `x046608`** (Right Hippocampus, RD1_1, Patient 7, SOZ=0) used as first example for visualization.
  - Raw time series, spectrogram, and PSD plotted successfully.
  - Spectrogram parameters optimized for vertical power-band clarity:
    - `nperseg=250` (50 ms window) — sharper time resolution
    - `noverlap=240` (96%) — smooth time axis
    - These settings preferred over defaults (`nperseg~1024`, `noverlap~512`) for visual band clarity.

## Artifact
Batch 2 Muscle Artifact Examples (MayoData1000):

Signal #6 — Muscle Artifact:
- Index: 35712
- File: x035712.mat
- Channel: RAD_3
- Anatomy: ctx-rh-temporalpole
- Patient: 6
- SOZ: 0
- Visual feature: sudden fuzziness in time series, broadband power elevation in PSD

Signal #8 — Muscle Artifact:
- Index: 35140
- File: x035140.mat
- Channel: RAD_2
- Anatomy: Right Amygdala
- Patient: 6
- SOZ: 0
- Visual feature: sudden fuzziness in time series, broadband power elevation in PSD

## Artifact Example Signals - MayoData1000

### Muscle Artifact (EMG Contamination)
- Signal #8: index=40391, channel=RPD_2, anatomy=Right-Hippocampus, patient_id=6, soz=1, file=x040391.mat
- Signal #10: index=77226, channel=LTD_8, anatomy=Left-Cerebral-White-Matter, patient_id=10, soz=0, file=x077226.mat

Visual Features:
- Time series: sudden fuzziness - trace thickens and becomes erratic; irregular spiky bursts with no consistent rhythm
- PSD: broadband power elevation across wide frequency range; no sharp peaks; significant energy extending past 200 Hz

### Powerline Contamination (60 Hz)
- Signal #9: index=95762, channel=PD_1, anatomy=Left-Cerebral-White-Matter, patient_id=12, soz=0, file=x095762.mat

Visual Features:
- Time series: large, constant sinusoidal oscillation - perfectly rhythmic throughout entire 3-second clip
- PSD: sharp dominant peak at 60 Hz + harmonic peaks at 120 Hz, 180 Hz, ~300 Hz, ~540 Hz

## iEEG Artifact Visual Features — MayoData1000

### Artifact Type 1: Muscle Artifact (EMG Contamination)
**Example signals:** #8 (RPD_2, Right-Hippocampus, Patient 6, SOZ=1, seg=40391), #10 (RAD_2, Right-Amygdala, Patient 6, SOZ=0, seg=35140)

**Time Series Visual Features:**
- Sudden onset of "fuzziness" — the trace becomes thick, dense, and irregular
- High-frequency, erratic, spiky bursts with no consistent periodic pattern
- Irregular transient episodes (not sustained throughout the entire clip)
- Large-amplitude rapid fluctuations with variable envelope
- Often appears as a region of the trace suddenly "thickening" or becoming chaotic

**PSD Features:**
- Broadband power elevation across a wide frequency range (from low frequencies extending well past 200 Hz)
- No single sharp dominant peak — power rises broadly
- Power does NOT drop off quickly with frequency (unlike clean neural signal)
- Significant energy above 200 Hz (fast ripple band) due to EMG contamination

**Detection Rule (suggested):**
- Broadband power elevation (spectral flatness high)
- Significant power > 200 Hz
- Non-stationary burst character (transient high-energy episodes in time-frequency)

---

### Artifact Type 2: Powerline Contamination (60 Hz)
**Example signal:** #9 (LTD_8, Left-Cerebral-White-Matter, Patient 10, SOZ=0, seg=77226)

**Time Series Visual Features:**
- Large, CONSTANT sinusoidal oscillation throughout the entire 3-second clip
- Very rhythmic, highly regular — does NOT change amplitude or frequency over time
- Appears as a pure, clean sine wave dominating the signal
- Amplitude is typically large relative to neural signal

**PSD Features:**
- Very sharp, dominant peak precisely at **60 Hz**
- Additional sharp peaks at harmonics: **120 Hz, 180 Hz, ~300 Hz, ~540 Hz**
- Power drops rapidly between the harmonic peaks
- The 60 Hz peak is far above the background 1/f noise floor

**Detection Rule (suggested):**
- Sharp PSD peak at 60 Hz (and harmonics)
- Harmonic ratio: 120 Hz / background power elevated
- High signal periodicity / low spectral entropy

---

### Summary Table
| Artifact | Time Series | PSD | Key Distinguisher |
|---|---|---|---|
| Muscle (EMG) | Sudden fuzziness, erratic spikes | Broadband elevation | Broadband, no peak |
| Powerline (60Hz) | Constant large sinusoidal wave | Sharp 60 Hz + harmonics | 60 Hz peak + harmonics |

These examples were visually confirmed by the researcher and vision model analysis on 2026-03-16.

## Dataset
- **Path:** `<dataset_root>/MayoData1000`
- **Source:** Mayo Clinic multicenter iEEG — Nejedly et al., *Scientific Data*, 2020
- **Files:** 1,000 `.mat` files in `/signals/` subdirectory; filename format `x{6-digit-index}.mat` (e.g., `x046608.mat`)
- **Loading:** MATLAB `.mat` format; load with `scipy.io.loadmat()`
- **Signal shape:** 15,000 samples per file (3 seconds @ 5,000 Hz sampling rate)
- **Key metadata fields per file:** channel name, anatomy label, patient ID, SOZ label (binary: 0 = not in seizure onset zone, 1 = SOZ)
- **SOZ definition:** Seizure Onset Zone — the brain region where epileptic seizures originate; resection target for drug-resistant epilepsy (DRE) surgery

---

## Spectrogram Parameters (Default)
Always use these parameters when plotting spectrograms:

| Parameter | Value |
|---|---|
| `nperseg` | 250 (50 ms window) |
| `noverlap` | 240 (96% overlap) |
| `colormap` | `inferno` |
| `vmin / vmax` | 30th / 99.5th percentile |
| `shading` | `gouraud` |

Rationale: sharpens vertical power bands while maintaining smooth time axis.

---

## Artifact Reference Examples
Always record signal batch number, metadata index, full filename, channel, and anatomy when saving examples.

### 💪 Muscle Artifact (EMG)
- **Visual (time series):** Sudden "fuzziness" — trace thickens and becomes erratic; high-frequency bursting
- **Visual (spectrogram):** Broadband high-frequency energy spike, sudden onset
- **Examples:**
  - `#8` | Index `40391` | `x040391.mat` | Channel: `RPD_2`
  - `#10` | Index `77226` | `x077226.mat`

### ⚡ Powerline Contamination (60 Hz)
- **Visual (time series):** Large, constant sinusoidal oscillation dominating the trace
- **Visual (PSD):** Sharp, prominent peak at exactly 60 Hz
- **Examples:**
  - `#9` | Index `95762` | `x095762.mat` | Channel: `PD_1`

---

## Global Procedures
- **Always save original file ID:** When remembering any signal example, always record: batch number (e.g., #8), metadata index (e.g., `40391`), full filename (e.g., `x040391.mat`), channel name, and anatomy label. Applies across all future projects.
