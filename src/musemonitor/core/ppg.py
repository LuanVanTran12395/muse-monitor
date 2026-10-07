"""PPG → heart rate → HRV."""
import numpy as np
from scipy.signal import sosfiltfilt, find_peaks, welch

from .. import config as C
from .filters import bandpass_sos


def ppg_score(x, fs):
    """How clear the pulse is: spectral peak in 0.7–3 Hz relative to the median spectrum in 0.5–4 Hz."""
    if len(x) < 4 * fs: return 0.0
    f, p = welch(x - x.mean(), fs=fs, nperseg=min(len(x), 4 * fs))
    b = (f >= 0.5) & (f <= 4); c = (f >= 0.7) & (f <= 3)
    med = np.median(p[b])
    return float(p[c].max() / med) if med > 0 else 0.0


def best_channel(x, fs):
    """The channel (row of x) with the clearest pulse."""
    return int(np.argmax([ppg_score(s, fs) for s in x]))


def ppg_beats(x, fs):
    """Band-pass 0.5–4 Hz, invert (optical intensity drops when blood arrives) and find peaks.
    Returns (filtered signal, peak positions in samples — refined with sub-sample parabolic interpolation)."""
    y = -sosfiltfilt(bandpass_sos(fs, *C.PPG_BAND_HZ), x - x.mean())
    pk, _ = find_peaks(y, distance=max(1, int(0.33 * fs)), prominence=0.5 * y.std())
    pk = pk[(pk > 0) & (pk < len(y) - 1)]
    a, b, c = y[pk - 1], y[pk], y[pk + 1]
    den = a - 2 * b + c
    off = np.where(np.abs(den) > 1e-12, 0.5 * (a - c) / np.where(den == 0, 1, den), 0.0)
    return y, pk + np.clip(off, -0.5, 0.5)


def clean_ibi(tb):
    """Inter-beat intervals (s) + validity mask (30–200 bpm, within 30% of the median).
    Returns (time of each IBI = the later beat, IBI, validity mask)."""
    ibi = np.diff(tb)
    lo, hi = C.IBI_RANGE_S
    ok = (ibi > lo) & (ibi < hi)
    if ok.sum() >= 3:
        med = np.median(ibi[ok]); ok &= np.abs(ibi - med) < C.IBI_MAX_DEV * med
    return tb[1:], ibi, ok


def hrv_metrics(ibi, ok):
    """HR, SDNN, SDHR, RMSSD, pRR50, pRR20 from IBIs (s); None if fewer than 3 valid IBIs."""
    v = ibi[ok]
    if len(v) < 3: return None
    d = np.diff(ibi)[ok[1:] & ok[:-1]]       # only differences of two adjacent valid IBIs
    hr = 60.0 / v
    nan = float("nan")
    return dict(hr=hr.mean(), sdnn=v.std(ddof=1) * 1000, sdhr=hr.std(ddof=1), n=len(v) + 1,
                rmssd=np.sqrt(np.mean(d ** 2)) * 1000 if len(d) else nan,
                prr50=np.mean(np.abs(d) > 0.050) * 100 if len(d) else nan,
                prr20=np.mean(np.abs(d) > 0.020) * 100 if len(d) else nan)
