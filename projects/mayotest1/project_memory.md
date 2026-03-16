

## Dataset
- **Path:** `C:\Users\yuans\Desktop\ClaudeCode\v3mayo\user\MayoData1000`
- **Source:** Mayo Clinic intracranial EEG (iEEG)
- **Size:** 1,000 `.mat` files, 1D float32 arrays, 15,000 samples each
- **Labels:** SOZ (Seizure Onset Zone) vs. non-SOZ per signal

## Signal Categories (User-Defined)
Four categories to classify signals — user is teaching these via visual inspection:
- **powerline_60hz** — regular sinusoidal oscillation; sharp narrow PSD spike at 60 Hz (± 120 Hz harmonic). Confirmed example: #46.
- **noise** — **sudden burst in amplitude** visible in the time series; determined primarily from the waveform plot. Not continuous fuzziness — must be an abrupt onset. Confirmed example: #350 (though #350 shows persistent broadband irregularity — category still held; clearer examples being sought).
- **pathology** — sudden isolated spikes or abnormal transients; requires time series + context to confirm. Candidate example: #983.
- **physiology** — clean biological signal; smoother morphology, continuous oscillations without sudden bursts or spikes, normal 1/f PSD dropoff. Example: #22. Signal #136 is a candidate (continuous ±2.5 oscillations, no burst, no sharp spike) — not yet confirmed by user.

## Visual Observations So Far
- SOZ signals tend toward higher low-frequency (δ, <4 Hz) power, flatter broadband PSD, more residual high-frequency (>80 Hz, HFO) power, and irregular/high-amplitude bursts.
- Non-SOZ signals tend toward smoother waveforms and steeper 1/f PSD dropoff.
- Diagnosis requires **multi-view inspection**: raw waveform, PSD, and potentially spectrogram + zoomed detail.
- **Noise classification is driven by the time series plot first** — look for sudden amplitude bursts, not just broadband PSD elevation.
- When inspecting with vision, **always split into individual plots** (one view per image); do not send large multi-panel figures — vision model gets overwhelmed.

## Project Goal
- Learn to distinguish the four signal categories (powerline_60hz, noise, pathology, physiology) via user teaching.
- User emphasises: **always visually inspect plots** before confirming understanding — do not rely on metadata alone.

## Open Questions / Next Steps
- Confirm category for signal #136 (candidate: physiology).
- Find clearer noise examples with unambiguous sudden amplitude bursts (ongoing random sampling).
- Build a labelled reference set from user-confirmed examples (currently confirmed: #46 powerline, #350 noise, #22 physiology; #983 pathology pending full confirmation).
- Define downstream task (classification model, data cleaning pipeline, or both).

