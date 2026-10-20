"""Reuse the functions and rules of the two existing extensions — read only, nothing in them is changed.

    head_motion_plus  PoseTracker (gyro → head pose, stillness, recenter), axes_from_motions, pose_angles,
                      HeadCanvas (3D head), its calibration constants
    eye_interaction   EyeEstimator (blinks from AF7/AF8), relative_alpha (eye closure from TP9/TP10 alpha), EyeCanvas

Each is loaded from its folder next to this one under a private module name (``food_order._reuse_head`` …), so it is
independent of whether that extension is ticked in the app. If a folder is missing, ``load()`` raises ImportError
with a clear message and the kiosk still works with the keyboard.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_cache = {}


def _load(folder_name):
    folder = (HERE.parent / folder_name).resolve()
    if str(folder) in _cache: return _cache[str(folder)]
    init = folder / "__init__.py"
    if not init.exists():
        raise ImportError(f"extension folder '{folder_name}' not found next to food_order ({folder})")
    name = f"{__name__}_{folder_name}_{abs(hash(str(folder))) % 10**8}"
    spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(folder)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module                       # relative imports inside it (e.g. "from . import camera")
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    _cache[str(folder)] = module
    return module


def head():
    """The head_motion_plus module (PoseTracker, axes_from_motions, pose_angles, HeadCanvas, CAPTURE_SEC)."""
    m = _load("head_motion_plus")
    for sym in ("PoseTracker", "axes_from_motions", "pose_angles", "HeadCanvas", "CAPTURE_SEC"):
        if not hasattr(m, sym): raise ImportError(f"head_motion_plus has no {sym}")
    return m


def eyes():
    """The eye_interaction module (EyeEstimator, relative_alpha, EyeCanvas, CAPTURE_SEC)."""
    m = _load("eye_interaction")
    for sym in ("EyeEstimator", "relative_alpha", "EyeCanvas", "CAPTURE_SEC"):
        if not hasattr(m, sym): raise ImportError(f"eye_interaction has no {sym}")
    return m
