import numpy as np

from .. import config as C


def stft_power(x, fs, win, step, fmax, max_cells=C.PSD_MAX_CELLS):
    """One-sided spectrogram (µV²/Hz) per channel, segments aligned to the newest sample.
    x: (n_ch, n). Returns (segment centres in s relative to the last sample, f, P[ch, t, f], step used)
    or None if there is not enough data for one window."""
    n = x.shape[1]
    if n < win: return None
    step = max(step, int(np.ceil((n - win) * win / max_cells)), 1)   # cap the FFT work
    starts = np.arange(n - win, -1, -step)[::-1]
    w = np.hanning(win + 1)[:-1]                                      # periodic Hann
    f = np.fft.rfftfreq(win, 1 / fs); keep = f <= fmax
    idx = starts[:, None] + np.arange(win)
    out = np.empty((x.shape[0], len(starts), keep.sum()), dtype=np.float32)
    scale = 1.0 / (fs * (w ** 2).sum())
    for c in range(x.shape[0]):
        seg = x[c][idx]
        seg = (seg - seg.mean(axis=1, keepdims=True)) * w
        p = np.abs(np.fft.rfft(seg, axis=1)) ** 2 * scale
        p[:, 1:] *= 2
        out[c] = p[:, keep]
    return (starts + win / 2 - n) / fs, f[keep], out, step


class PsdAccumulator:
    """Welch PSD accumulated chunk by chunk over a whole recording — never keeps the full signal in memory.

    Each ``nperseg``-sample segment (overlap ``overlap``) has its DC removed, is Hann-windowed and turned
    into a one-sided periodogram (unit²/Hz); the result is the mean over segments — identical to
    ``scipy.signal.welch(x, fs, nperseg=…, noverlap=…)`` (detrend='constant', average='mean')."""
    def __init__(self, fs, n_ch, seg_sec, overlap=0.5):
        self.fs = fs
        self.nperseg = max(8, int(round(seg_sec * fs)))
        self.step = max(1, self.nperseg - int(self.nperseg * overlap))
        self.n_ch = n_ch
        self.buf = np.zeros((n_ch, 0))
        self.sum = np.zeros((n_ch, self.nperseg // 2 + 1))
        self.count = 0
        self.total = 0

    @staticmethod
    def _periodogram(seg, fs):
        n = seg.shape[1]
        w = np.hanning(n + 1)[:-1]                       # periodic Hann (as in scipy)
        X = np.fft.rfft((seg - seg.mean(axis=1, keepdims=True)) * w, axis=1)
        p = np.abs(X) ** 2 / (fs * (w ** 2).sum())
        if n % 2: p[:, 1:] *= 2
        else: p[:, 1:-1] *= 2
        return p

    def add(self, x):
        self.total += x.shape[1]
        self.buf = np.concatenate([self.buf, np.asarray(x, dtype=float)], axis=1)
        while self.buf.shape[1] >= self.nperseg:
            self.sum += self._periodogram(self.buf[:, :self.nperseg], self.fs)
            self.count += 1
            self.buf = self.buf[:, self.step:]

    def result(self):
        """(f, psd[n_ch, n_f], number of segments). Shorter than one segment: one periodogram of what exists."""
        if self.count:
            return np.fft.rfftfreq(self.nperseg, 1 / self.fs), self.sum / self.count, self.count
        if self.buf.shape[1] >= 8:
            return np.fft.rfftfreq(self.buf.shape[1], 1 / self.fs), self._periodogram(self.buf, self.fs), 1
        return None


def band_powers(f, psd, bands):
    """Absolute power per band (integrated PSD) → dict band name → array [n_ch]."""
    df = f[1] - f[0] if len(f) > 1 else 1.0
    return {name: psd[:, (f >= lo) & (f < hi)].sum(axis=1) * df for name, (lo, hi) in bands.items()}
