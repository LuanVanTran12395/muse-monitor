"""The ONLY place Muse Cube loads code from other extensions — read only, nothing in them is changed.

    head_motion_plus      PoseTracker, axes_from_motions, pose_angles (yaw, pitch, roll)
    eye_interaction       EyeEstimator, relative_alpha (used by EyeCommands)
    food_order/gestures   HeadGestures (pointing zones, full turn, look-up hold, nod, shake, gyro-drift pull) and
                          EyeCommands (double blink, TP9 / TP10 by default) — the file alone, not the food_order
                          package (no kiosk, no capture)

Every capability is checked separately (the symbols and methods it needs). One that fails is switched off with its
reason; the others, and the keyboard game, keep working:

    head   pointing a face, turning the whole cube, shake to undo, nod
    tilt   head tilt (roll) to turn a face — needs head, and pose_angles returning roll
    eyes   double blink to turn the selected layer clockwise
    camera head_motion_plus's camera reference (CameraController, FacingGate) for auto-recenter, and its HeadCanvas
           (the 3D head shown instead of the camera image)
(The jaw clench, counter-clockwise, is Muse Cube's own: jaw.py, on the core band-pass filter.)
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEEDS = {
    "head_motion_plus": ("PoseTracker", "axes_from_motions", "pose_angles"),
    "HeadGestures": ("feed", "calibrate", "recenter", "reset_runtime", "update"),
    "eye_interaction": ("EyeEstimator", "relative_alpha"),
    "EyeCommands": ("feed", "calibrate_open", "calibrate_blink", "note_motion"),
}
_cache = {}


def _module_name(tag, path):
    return f"muse_cube_reuse_{tag}_{abs(hash(str(path))) % 10**8}"


def _exec(name, path, package_dir=None):
    if name in _cache: return _cache[name]
    kw = dict(submodule_search_locations=[str(package_dir)]) if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kw)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    _cache[name] = module
    return module


def load_head(root=None):
    folder = ((root or HERE.parent) / "head_motion_plus").resolve()
    init = folder / "__init__.py"
    if not init.exists(): raise ImportError(f"head_motion_plus not found next to muse_cube ({folder})")
    m = _exec(_module_name("head", folder), init, folder)
    missing = [s for s in NEEDS["head_motion_plus"] if not hasattr(m, s)]
    if missing: raise ImportError("head_motion_plus has no " + ", ".join(missing))
    return m


def load_eyes(root=None):
    folder = ((root or HERE.parent) / "eye_interaction").resolve()
    init = folder / "__init__.py"
    if not init.exists(): raise ImportError(f"eye_interaction not found next to muse_cube ({folder})")
    m = _exec(_module_name("eyes", folder), init, folder)
    missing = [s for s in NEEDS["eye_interaction"] if not hasattr(m, s)]
    if missing: raise ImportError("eye_interaction has no " + ", ".join(missing))
    return m


def load_gestures(root=None):
    path = ((root or HERE.parent) / "food_order" / "gestures.py").resolve()
    if not path.exists(): raise ImportError(f"food_order/gestures.py not found ({path})")
    m = _exec(_module_name("gestures", path), path)
    cls = getattr(m, "HeadGestures", None)
    if cls is None: raise ImportError("food_order/gestures.py has no HeadGestures")
    missing = [s for s in NEEDS["HeadGestures"] if not callable(getattr(cls, s, None))]
    if missing: raise ImportError("HeadGestures has no " + ", ".join(missing))
    return m


class Adapter:
    """caps: {name: (ok, reason)}; ``head_gestures(fs)`` builds the estimator when "head" is ok."""

    def __init__(self, root=None):
        self.head_mod = self.gestures_mod = self.eyes_mod = None
        self.caps = {}
        try:
            self.head_mod = load_head(root)
            self.gestures_mod = load_gestures(root)
            self.caps["head"] = (True, "")
        except Exception as e:                                   # missing / changed extension
            self.caps["head"] = (False, f"{type(e).__name__}: {e}")
        if self.caps["head"][0]:
            try:
                import numpy as np
                angles = self.head_mod.pose_angles(np.array((1.0, 0.0, 0.0, 0.0)))
                if len(angles) < 3: raise ValueError("pose_angles gives no roll")
                self.caps["tilt"] = (True, "")
            except Exception as e:
                self.caps["tilt"] = (False, f"{type(e).__name__}: {e}")
        else:
            self.caps["tilt"] = (False, "needs head")
        try:
            if not self.caps["head"][0]: raise ImportError("needs head")
            cam = getattr(self.head_mod, "camera", None)
            if cam is None: raise ImportError("head_motion_plus has no camera module")
            missing = [s for s in ("CameraController", "FacingGate", "availability") if not hasattr(cam, s)]
            if missing or not hasattr(self.head_mod, "HeadCanvas"):
                raise ImportError("head_motion_plus camera has no " + ", ".join(missing or ["HeadCanvas"]))
            ok, why = cam.availability()
            self.caps["camera"] = (bool(ok), why)
        except Exception as e:
            self.caps["camera"] = (False, f"{type(e).__name__}: {e}")
        try:                                                     # independent of the head capabilities
            self.gestures_mod = self.gestures_mod or load_gestures(root)
            cls = getattr(self.gestures_mod, "EyeCommands", None)
            if cls is None: raise ImportError("food_order/gestures.py has no EyeCommands")
            missing = [s for s in NEEDS["EyeCommands"] if not callable(getattr(cls, s, None))]
            if missing: raise ImportError("EyeCommands has no " + ", ".join(missing))
            self.eyes_mod = load_eyes(root)
            self.caps["eyes"] = (True, "")
        except Exception as e:
            self.caps["eyes"] = (False, f"{type(e).__name__}: {e}")

    def ok(self, cap):
        return self.caps.get(cap, (False, ""))[0]

    def reason(self, cap):
        return self.caps.get(cap, (False, "unknown"))[1]

    def head_gestures(self, fs, cfg=None):
        return self.gestures_mod.HeadGestures(self.head_mod, fs, cfg)

    def eye_commands(self, fs, names, source="tp"):
        return self.gestures_mod.EyeCommands(self.eyes_mod, fs, names, source=source)

    def roll(self, tracker):
        return float(self.head_mod.pose_angles(tracker.q)[2])
