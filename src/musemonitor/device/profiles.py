"""Device profiles: everything the app needs to know to work with one kind of headset.

The built-in profile is Muse S Athena. Other devices are OPTIONAL libraries found by convention:
any importable top-level package named ``musemonitor_*`` that defines ``DEVICE_PROFILE`` (a
``DeviceProfile`` or a function returning one). Nothing in the app names those libraries, so
deleting one simply removes that device from the connect list.
"""
import importlib
import pkgutil
import sys
import traceback
from dataclasses import dataclass, field
from typing import Callable

from .spec import athena_spec


@dataclass
class DeviceProfile:
    id: str
    name: str
    make_spec: Callable                         # () -> DeviceSpec
    make_worker: Callable                       # (device_name, spec) -> QObject with MuseWorker's signals
    matches: Callable                           # (BLE advertised name) -> bool
    electrode_positions: dict = None            # name -> (x, y) for the head map; None = app default
    fnirs: dict = None                          # defaults for the fNIRS panel (pair, labels, ext, dpf, dist)
    note: str = ""                              # one-line description under the recording screen
    extras: dict = field(default_factory=dict)


def _muse_worker(name, spec):
    from .worker import MuseWorker
    return MuseWorker(name, spec)


def athena_profile():
    return DeviceProfile(
        id="muse_athena", name="Muse S Athena", make_spec=athena_spec, make_worker=_muse_worker,
        matches=lambda n: "muse" in (n or "").lower())


def discover_profiles(prefix="musemonitor_"):
    """[Athena] + profiles of optional device libraries; a broken library is skipped (logged)."""
    profiles = [athena_profile()]
    for mod in sorted({m.name for m in pkgutil.iter_modules() if m.name.startswith(prefix)}):
        try:
            prof = getattr(importlib.import_module(mod), "DEVICE_PROFILE", None)
            if prof is None: continue
            prof = prof() if callable(prof) else prof
            if isinstance(prof, DeviceProfile) and all(p.id != prof.id for p in profiles):
                profiles.append(prof)
        except Exception:
            print(f"[musemonitor] device library '{mod}' failed to load:\n{traceback.format_exc()}", file=sys.stderr)
    return profiles


def profile_for_name(profiles, device_name, default=None):
    """The profile whose BLE name pattern matches ``device_name`` (first match), else ``default``."""
    return next((p for p in profiles if p.matches(device_name)), default)
