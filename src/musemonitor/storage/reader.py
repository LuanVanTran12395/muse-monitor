"""Read a recorded session back for review. No Qt dependency.

Accepts a session folder (``data/muse_<stamp>/``, with or without ``session.json``), the folder's
``session.json``, or any CSV of a recording — including old flat files in ``data/``.

    files = locate(path)                       # which CSVs belong to the recording
    info = inspect(files, profiles)            # which device recorded it, and how sure we are
    sess = load(info, profile=info.profile)    # arrays (signals float32, timestamps float64) + events

``inspect`` only reads headers and ``session.json``. Its ``certainty`` is:
- ``certain``   session.json names the device, or the CSV headers match exactly ONE known profile;
- ``ambiguous`` the headers match several profiles → the caller must ask which one;
- ``unknown``   no profile matches → the caller asks, or loads a generic spec with sampling rates
                estimated from the timestamps (``load(info, profile=None)``).
Columns are read by name; ``package_num`` is ignored for review, so files from before and after it
was added both open.
"""
import csv
import itertools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .recording import companion_path
from .session import META_FILE

STREAM_KEYS = ("eeg", "optics", "imu")
MAIN_RE = re.compile(r"^muse_eeg_\d{8}_\d{6}$")
COMPANIONS = ("optics", "imu", "events")
CHUNK_ROWS = 100_000
MIN_ESTIMATE_SEC = 10.0          # shortest stream whose sampling rate we are willing to estimate


class ReaderError(Exception):
    """The recording cannot be opened; the message is shown to the user as is."""


class ReadCancelled(Exception):
    pass


@dataclass
class SessionFiles:
    folder: Path
    stamp: str
    eeg: Path
    optics: Path = None
    imu: Path = None
    events: Path = None
    meta: Path = None

    def stream(self, key):
        return getattr(self, key)


@dataclass
class SessionInfo:
    files: SessionFiles
    headers: dict                      # stream key → channel names (package_num removed)
    meta: dict = None                  # parsed session.json, if any
    profile: object = None             # DeviceProfile when known
    candidates: list = field(default_factory=list)
    certainty: str = "unknown"         # certain | ambiguous | unknown
    device_name: str = ""
    warnings: list = field(default_factory=list)


@dataclass
class LoadedSession:
    info: SessionInfo
    spec: object                       # profile's DeviceSpec, or None → build one from names + rates
    names: dict                        # "eeg" | "optics" | "imu" → channel names
    rates: dict                        # same keys → sampling rate (Hz) from session.json or estimated
    streams: dict                      # "eeg" | "opt" | "imu" → (ts float64 (N,), x float32 (n_ch, N))
    events: list                       # [(unix time, label)]
    fs_estimated: bool = False
    warnings: list = field(default_factory=list)


# ---- locating files --------------------------------------------------------------------------
def _main_of(csv_path):
    stem = csv_path.stem
    if MAIN_RE.match(stem): return csv_path
    for suf in COMPANIONS:
        if stem.endswith("_" + suf) and MAIN_RE.match(stem[:-len(suf) - 1]):
            return csv_path.with_name(stem[:-len(suf) - 1] + ".csv")
    return None


def locate(path):
    p = Path(path).expanduser()
    if not p.exists(): raise ReaderError(f"{p} does not exist.")
    if p.is_file() and p.name == META_FILE: p = p.parent
    meta = None
    if p.is_dir():
        meta = p / META_FILE if (p / META_FILE).is_file() else None
        mains = sorted(f for f in p.glob("muse_eeg_*.csv") if MAIN_RE.match(f.stem))
        if meta is not None:
            try: eeg_name = json.loads(meta.read_text())["streams"]["eeg"]["file"]
            except (OSError, ValueError, KeyError, TypeError): eeg_name = None
            if eeg_name and (p / eeg_name).is_file(): mains = [p / eeg_name]
        if not mains: raise ReaderError(f"No recording (muse_eeg_<date>_<time>.csv) in {p}.")
        if len(mains) > 1:
            raise ReaderError(f"{p} holds {len(mains)} recordings — open one of the muse_eeg_*.csv files instead.")
        main = mains[0]
    elif p.suffix.lower() == ".csv":
        main = _main_of(p)
        if main is None: raise ReaderError(f"{p.name} is not a Muse Monitor recording (muse_eeg_<date>_<time>.csv).")
        if not main.is_file(): raise ReaderError(f"The EEG file {main.name} for {p.name} is missing.")
        if (main.parent / META_FILE).is_file(): meta = main.parent / META_FILE
    else:
        raise ReaderError(f"Open a recording folder, its session.json or one of its CSV files — not {p.name}.")
    files = SessionFiles(folder=main.parent, stamp=main.stem[len("muse_eeg_"):], eeg=main, meta=meta)
    for key in COMPANIONS:
        c = companion_path(main, key)
        if c.is_file(): setattr(files, key, c)
    return files


# ---- headers / device ------------------------------------------------------------------------
def _header(path):
    if path.stat().st_size == 0:
        raise ReaderError(f"{path.name} is empty (0 bytes) — if it is in iCloud, download it first.")
    with open(path, newline="") as f:
        row = next(csv.reader(f), None)
    if not row or row[0].strip() != "timestamp":
        raise ReaderError(f"{path.name} has no 'timestamp' header — not a Muse Monitor CSV.")
    return [c.strip() for c in row]


def _channels(cols):
    return [c for c in cols[1:] if c != "package_num"]


def _spec_names(spec):
    return {"eeg": list(spec.eeg.names), "optics": list(spec.optics.names), "imu": list(spec.imu.names)}


def _matches(spec, headers):
    names = _spec_names(spec)
    for key, cols in headers.items():
        if cols != names[key]: return False
    return True


def inspect(files, profiles=()):
    headers = {}
    for key in STREAM_KEYS:
        f = files.stream(key)
        if f is None: continue
        try: headers[key] = _channels(_header(f))
        except ReaderError:
            if key == "eeg": raise
            setattr(files, key, None)                      # unreadable companion → shown without it
    info = SessionInfo(files=files, headers=headers)
    if files.optics is None and files.imu is None:
        info.warnings.append("No optics or IMU file — only EEG is shown.")
    if files.meta is not None:
        try: info.meta = json.loads(files.meta.read_text())
        except (OSError, ValueError): info.warnings.append("session.json could not be read — device guessed from headers.")
    if info.meta:
        info.device_name = info.meta.get("device_name") or ""
        pid = info.meta.get("profile_id")
        prof = next((p for p in profiles if p.id == pid), None)
        if prof is not None and _matches(prof.make_spec(), headers):
            info.profile, info.candidates, info.certainty = prof, [prof], "certain"
            return info
        if _meta_complete(info.meta, headers):
            info.certainty = "certain"                          # rates and channels come from session.json
            if pid: info.warnings.append(f"Device library '{pid}' is not installed — shown with the recorded settings.")
            return info
    info.candidates = [p for p in profiles if _matches(p.make_spec(), headers)]
    if len(info.candidates) == 1:
        info.profile, info.certainty = info.candidates[0], "certain"
    else:
        info.certainty = "ambiguous" if info.candidates else "unknown"
    return info


def _meta_complete(meta, headers):
    try:
        streams = meta["streams"]
        return all(key in streams and float(streams[key]["fs"]) > 0 and list(streams[key]["channels"]) == cols
                   for key, cols in headers.items())
    except (KeyError, TypeError, ValueError):
        return False


# ---- data ------------------------------------------------------------------------------------
def _count_rows(path):
    n, last = 0, b"\n"
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b: break
            n += b.count(b"\n"); last = b[-1:]
    return n + (last != b"\n")


def read_stream(path, progress=None, done=0, total=1):
    """(channel names, ts float64 (N,), x float32 (n_ch, N)), read in blocks of CHUNK_ROWS lines."""
    cols = _header(path)
    names = _channels(cols)
    use = [0] + [i for i, c in enumerate(cols) if i > 0 and c != "package_num"]
    n_rows = _count_rows(path) - 1
    ts = np.empty(max(n_rows, 0)); x = np.empty((len(names), max(n_rows, 0)), dtype=np.float32)
    k = 0
    with open(path, newline="") as f:
        next(f)
        while True:
            lines = [ln for ln in itertools.islice(f, CHUNK_ROWS) if ln.strip()]
            if not lines: break
            try:
                block = np.loadtxt(lines, delimiter=",", usecols=use, ndmin=2, dtype=np.float64)
            except ValueError as e:
                raise ReaderError(f"{path.name}: unreadable row near line {k + 2}: {e}") from None
            m = len(block)
            ts[k:k + m] = block[:, 0]; x[:, k:k + m] = block[:, 1:].T
            k += m
            if progress is not None and progress((done + k) / max(total, 1)) is False:
                raise ReadCancelled()
    if k == 0: raise ReaderError(f"{path.name} has a header but no data.")
    return names, ts[:k], x[:, :k]


def _estimate_fs(ts, name):
    span = float(ts[-1] - ts[0]) if len(ts) > 1 else 0.0
    if not np.isfinite(span) or span <= 0:
        raise ReaderError(f"{name}: timestamps do not increase — cannot estimate the sampling rate.")
    if span < MIN_ESTIMATE_SEC:
        raise ReaderError(f"{name}: only {span:.1f} s of data — too short to estimate the sampling rate safely.")
    return (len(ts) - 1) / span


def read_events(path):
    out = []
    if path is None or path.stat().st_size == 0: return out
    with open(path, newline="") as f:
        for row in itertools.islice(csv.reader(f), 1, None):
            try: out.append((float(row[0]), row[1] if len(row) > 1 else ""))
            except (ValueError, IndexError): continue
    return sorted(out)


def load(info, profile=None, progress=None):
    """Read every stream. ``profile``: DeviceProfile to display with; None = info.profile, or — if that is None
    too — the rates in session.json, else rates estimated from the timestamps (``fs_estimated``)."""
    files = info.files
    profile = profile or info.profile
    present = [k for k in STREAM_KEYS if files.stream(k) is not None]
    sizes = {k: files.stream(k).stat().st_size for k in present}
    total = sum(sizes.values()) or 1
    raw, done, names = {}, 0, {}
    for key in present:
        share = sizes[key] / total
        def cb(frac, base=done / total, share=share):
            return None if progress is None else progress(base + frac * share)
        names[key], ts, x = read_stream(files.stream(key), cb if progress else None, 0, 1)
        raw[key] = (ts, x); done += sizes[key]
    warnings = list(info.warnings)
    fs_estimated, spec = False, None
    if profile is not None:
        spec = profile.make_spec()
        if not _matches(spec, names): raise ReaderError(f"The CSV channels do not match {profile.name}.")
        rates = {k: getattr(spec, k).fs for k in names}
    elif info.meta and _meta_complete(info.meta, names):
        rates = {k: float(info.meta["streams"][k]["fs"]) for k in names}
    else:
        rates = {k: _estimate_fs(raw[k][0], files.stream(k).name) for k in names}
        fs_estimated = True
    for key in names:                                           # sanity: recorded rate vs. the expected one
        ts = raw[key][0]
        if len(ts) > 1 and ts[-1] > ts[0]:
            measured, nominal = (len(ts) - 1) / (ts[-1] - ts[0]), rates[key]
            if abs(measured - nominal) > 0.2 * nominal:
                warnings.append(f"{key}: measured {measured:.1f} Hz vs. {nominal:g} Hz expected.")
    streams = {("opt" if k == "optics" else k): v for k, v in raw.items()}
    if progress is not None: progress(1.0)
    return LoadedSession(info=info, spec=spec, names=names, rates=rates, streams=streams, events=read_events(files.events),
                         fs_estimated=fs_estimated, warnings=warnings)
