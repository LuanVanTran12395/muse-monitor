from functools import lru_cache

import numpy as np
from scipy.signal import butter, iirnotch, tf2sos, sosfilt, sosfilt_zi

from .. import config as C


@lru_cache(maxsize=None)
def eeg_sos(fs):
    """Design the filters ONCE per sampling rate (the old code redesigned them 4 channels × 20 times/s)."""
    notch = tf2sos(*iirnotch(C.NOTCH_HZ, C.NOTCH_Q, fs))
    band = butter(C.BAND_ORDER, list(C.BAND_HZ), btype="bandpass", fs=fs, output="sos")
    return {"notch": notch, "band": band, "both": np.vstack([notch, band])}


@lru_cache(maxsize=None)
def bandpass_sos(fs, lo, hi, order=3):
    return butter(order, [lo, hi], btype="bandpass", fs=fs, output="sos")


@lru_cache(maxsize=None)
def lowpass_sos(fs, hz, order=2):
    return butter(order, hz, btype="lowpass", fs=fs, output="sos")


def remove_dc(x):
    """Remove the DC offset of each channel (raw / notch-only mode)."""
    return x - x.mean(axis=1, keepdims=True)


class CausalFilter:
    """Stateful causal filter for data arriving in chunks.

    Each new chunk continues from the filter state (zi) of the previous one, so the filtered
    signal is one continuous series: no distortion at the right edge (no backward pass) or at the
    left edge (no cut-and-refilter of a window). The trade-off is a small phase delay (~tens of ms).
    """
    def __init__(self, fs, notch=True, band=True):
        self.fs = fs; self.notch = notch; self.band = band
        self.sos = None; self.zi = None

    def configure(self, notch, band):
        self.notch, self.band = notch, band; self.reset()

    def reset(self):
        self.zi = None

    def _current_sos(self):
        s = eeg_sos(self.fs)
        if self.notch and self.band: return s["both"]
        if self.notch: return s["notch"]
        if self.band: return s["band"]
        return None

    def process(self, x):
        sos = self._current_sos()
        if sos is None: return x
        if self.zi is None or self.sos is not sos:
            # start in steady state for the first sample → no step caused by the DC offset
            self.sos = sos
            self.zi = sosfilt_zi(sos)[:, None, :] * x[None, :, :1]
        y, self.zi = sosfilt(sos, x, axis=1, zi=self.zi)
        return y
