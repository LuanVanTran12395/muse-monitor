"""fNIRS: optical intensity at 2 wavelengths → ΔHbO / ΔHbR (modified Beer–Lambert)."""
import numpy as np
from scipy.signal import sosfiltfilt

from .. import config as C
from .filters import lowpass_sos

EXT = np.array(C.FNIRS_EXT)


def mbll(i1, i2, fs, dpf=C.FNIRS_DPF, dist_cm=C.FNIRS_DIST_CM, ext=None):
    """ΔHbO, ΔHbR (µM) from intensities at 2 wavelengths; baseline = mean of the window.
    ext: 2×2 extinction matrix (rows = [λ1, λ2], columns = [HbO, HbR]); default 730/850 nm."""
    I = np.maximum(np.vstack([i1, i2]), 1.0)
    od = -np.log10(I / I.mean(axis=1, keepdims=True))
    od = sosfiltfilt(lowpass_sos(fs, C.FNIRS_LOWPASS_HZ), od, axis=1)
    conc = np.linalg.solve((EXT if ext is None else np.asarray(ext, dtype=float)) * dist_cm * dpf, od)
    return conc * 1e6
