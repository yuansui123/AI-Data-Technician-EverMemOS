import numpy as np
import pandas as pd
import scipy.io
import scipy.signal
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt, hilbert
import os

# ── Config ──────────────────────────────────────────────────────────────────
DATA_DIR  = r'C:\Users\yuans\Desktop\ClaudeCode\v3mayo\user\MayoData1000\signals'
META_CSV  = r'C:\Users\yuans\Desktop\ClaudeCode\v3mayo\user\MayoData1000\meta_data.csv'
OUT_DIR   = r'C:\Users\yuans\Desktop\AI_Data_Technician\projects\mayotest1\tmp'
FS        = 2000          # Hz
INDICES   = [46, 350, 983, 22]   # 0-based row indices

os.makedirs(OUT_DIR, exist_ok=True)

meta = pd.read_csv(META_CSV)
print(f'Metadata rows: {len(meta)}')

# ── Helper: load signal ──────────────────────────────────────────────────────
def load_signal(row_idx):
    seg_id = meta.iloc[row_idx]['segment_id']
    fname  = f'{seg_id}.mat'
    path   = os.path.join(DATA_DIR, fname)
    mat    = scipy.io.loadmat(path)
    # find data key
    if 'data' in mat:
        sig = mat['data'].ravel().astype(float)
    else:
        keys = [k for k in mat.keys() if not k.startswith('_')]
        sig  = mat[keys[0]].ravel().astype(float)
    return sig, seg_id

# ── Helper: bandpass filter ──────────────────────────────────────────────────
def bandpass(sig, lo, hi, fs, order=4):
    nyq = fs / 2
    b, a = butter(order, [lo/nyq, hi/nyq], btype='band')
    return filtfilt(b, a, sig)

BANDS = {
    'delta':      (1,   4),
    'theta':      (4,   8),
    'alpha':      (8,  13),
    'beta':       (13, 30),
    'gamma':      (30, 80),
    'high_gamma': (80, 150),
}

# ── Plot functions ────────────────────────────────────────────────────────────
def plot_waveform(sig, seg_id, n, fs=FS):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 4))
    t = np.arange(len(sig)) / fs
    ax.plot(t, sig, lw=0.6, color='cyan')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Amplitude')
    ax.set_title(f'Waveform — sig#{n}  [{seg_id}]')
    plt.tight_layout()
    out = os.path.join(OUT_DIR, f'sig{n}_waveform.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f'  Saved {out}')

def plot_psd(sig, seg_id, n, fs=FS):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 4))
    freqs, psd = scipy.signal.welch(sig, fs=fs, nperseg=1024)
    mask = freqs <= 200
    psd_db = 10 * np.log10(psd[mask] + 1e-30)
    ax.plot(freqs[mask], psd_db, lw=1.2, color='magenta')
    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel('Power (dB)')
    ax.set_xlim(0, 200)
    ax.set_title(f'PSD (Welch) — sig#{n}  [{seg_id}]')
    plt.tight_layout()
    out = os.path.join(OUT_DIR, f'sig{n}_psd.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f'  Saved {out}')

def plot_spectrogram(sig, seg_id, n, fs=FS):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 4))
    f, t, Sxx = scipy.signal.spectrogram(sig, fs=fs, nperseg=256)
    mask = f <= 200
    Sxx_db = 10 * np.log10(Sxx[mask, :] + 1e-30)
    ax.pcolormesh(t, f[mask], Sxx_db, cmap='inferno', shading='gouraud')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Frequency (Hz)')
    ax.set_ylim(0, 200)
    ax.set_title(f'Spectrogram — sig#{n}  [{seg_id}]')
    plt.tight_layout()
    out = os.path.join(OUT_DIR, f'sig{n}_spectrogram.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f'  Saved {out}')

def plot_hilbert(sig, seg_id, n, fs=FS):
    plt.style.use('dark_background')
    band_names = list(BANDS.keys())
    n_bands    = len(band_names)
    n_samp     = len(sig)

    envelope_mat = np.zeros((n_bands, n_samp))
    for i, (bname, (lo, hi)) in enumerate(BANDS.items()):
        filtered          = bandpass(sig, lo, hi, fs)
        envelope_mat[i]   = np.abs(hilbert(filtered))

    # Normalise each band independently for visual clarity
    for i in range(n_bands):
        rng = envelope_mat[i].max() - envelope_mat[i].min()
        if rng > 0:
            envelope_mat[i] = (envelope_mat[i] - envelope_mat[i].min()) / rng

    t = np.arange(n_samp) / fs

    fig, ax = plt.subplots(figsize=(10, 4))
    im = ax.imshow(
        envelope_mat,
        aspect='auto',
        extent=[t[0], t[-1], -0.5, n_bands - 0.5],
        origin='lower',
        cmap='inferno',
        vmin=0, vmax=1,
    )
    ax.set_yticks(range(n_bands))
    ax.set_yticklabels(band_names, fontsize=8)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Frequency Band')
    ax.set_title(f'Hilbert Envelope PDM — sig#{n}  [{seg_id}]')
    fig.colorbar(im, ax=ax, label='Norm. Envelope')
    plt.tight_layout()
    out = os.path.join(OUT_DIR, f'sig{n}_hilbert.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f'  Saved {out}')

# ── Main loop ─────────────────────────────────────────────────────────────────
for idx in INDICES:
    print(f'\n=== Processing row #{idx} ===')
    sig, seg_id = load_signal(idx)
    print(f'  segment_id={seg_id}  shape={sig.shape}  fs={FS}')
    plot_waveform   (sig, seg_id, idx)
    plot_psd        (sig, seg_id, idx)
    plot_spectrogram(sig, seg_id, idx)
    plot_hilbert    (sig, seg_id, idx)

print('\nAll 16 plots saved.')
