"""F0 capture files — pure Python (no Qt). One folder per capture under ``<data>/food_order/capture/``:

    config.json   subject, posture, notes, protocol (seed, steps), device, channels, rates, contact at start,
                  versions; at the end: completed, stop_reason, rows
    eeg.csv       index, ts_raw_unix (the device timestamp the app received), recv_mono, then one column per channel
    imu.csv       the same for the IMU (acc_x … gyro_z)
    labels.csv    one row per protocol step: kind, name, set, rep, prompt / GO / end times (monotonic and unix),
                  bad (marked by the experimenter), bad_mono, note
    contact.csv   electrode contact every ~2 s: level, signal RMS and mains RMS per channel
    log.txt       tones, pauses, bad marks, stop

Label times are when the app showed the GO cue and played its tone — NOT when the movement began: allow a reaction
time (debate/codex-food-order-extension-review.md §F0.4). recv_mono and the label times use the same monotonic
clock; ts_raw_unix and the *_unix label times use the wall clock.
"""
import csv
import json
import re
import time
import unicodedata
from pathlib import Path

SUBJECT_RE = r"[A-Za-z0-9_-]{1,32}"
LABEL_FIELDS = ["step", "kind", "name", "set", "rep", "prompt_mono", "go_mono", "go_unix", "end_mono", "end_unix",
                "bad", "bad_mono", "note"]


def to_subject(text):
    """What the sign-in field keeps from what was typed: accents removed (Trần → Tran, đ → d), spaces → "_", other
    characters dropped, at most 32 — so a name or "M 01" still gives a valid folder-safe code."""
    t = (text or "").replace("đ", "d").replace("Đ", "D")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"\s", "_", t)
    return re.sub(r"[^A-Za-z0-9_-]", "", t)[:32]


def valid_subject(subject):
    return bool(re.fullmatch(SUBJECT_RE, subject or ""))


def new_folder(root, subject, stamp=None):
    """``<YYYYMMDD_HHMMSS>_<subject>`` under ``root`` — never an existing folder."""
    if not re.fullmatch(SUBJECT_RE, subject or ""): raise ValueError(f"invalid subject ID {subject!r}")
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    base = f"{stamp or time.strftime('%Y%m%d_%H%M%S')}_{subject}"
    folder, k = root / base, 2
    while folder.exists(): folder = root / f"{base}_{k}"; k += 1
    folder.mkdir()
    return folder


def _fmt(v):
    if v is None: return ""
    if isinstance(v, bool): return "1" if v else "0"
    if isinstance(v, float): return f"{v:.6f}"
    return str(v)


class CaptureWriter:
    """Buffered CSV writers (called from the GUI thread; the rates are low: 256 Hz EEG, 52 Hz IMU)."""

    def __init__(self, folder, config, eeg_names, imu_names):
        self.folder = Path(folder)
        self.config = dict(config)
        self.rows = dict(eeg=0, imu=0, labels=0, contact=0)
        self.eeg_names, self.imu_names = list(eeg_names), list(imu_names)
        self.files = {}
        self._open("eeg", ["index", "ts_raw_unix", "recv_mono"] + self.eeg_names)
        self._open("imu", ["index", "ts_raw_unix", "recv_mono"] + self.imu_names)
        self._open("labels", LABEL_FIELDS)
        self._open("contact", ["mono"] + [f"{c}_{k}" for c in self.eeg_names for k in ("level", "signal_uv", "mains_uv")])
        self.log_f = open(self.folder / "log.txt", "w", encoding="utf-8")
        self._write_config()
        self.closed = False

    def _open(self, name, header):
        f = open(self.folder / f"{name}.csv", "w", newline="", encoding="utf-8", buffering=1 << 16)
        w = csv.writer(f); w.writerow(header)
        self.files[name] = (f, w)

    def _write_config(self):
        (self.folder / "config.json").write_text(json.dumps(self.config, indent=2, ensure_ascii=False, default=str),
                                                 encoding="utf-8")

    def samples(self, stream, x, ts_raw, recv_mono):
        """stream: "eeg" | "imu"; x: channels × n; ts_raw: per-sample device timestamps."""
        if self.closed: return
        w = self.files[stream][1]
        start = self.rows[stream]
        for i in range(x.shape[1]):
            w.writerow([start + i, f"{ts_raw[i]:.6f}", f"{recv_mono:.6f}"] + [f"{v:.3f}" for v in x[:, i]])
        self.rows[stream] += x.shape[1]

    def label(self, row):
        if self.closed: return
        self.files["labels"][1].writerow([_fmt(row.get(k)) for k in LABEL_FIELDS]); self.rows["labels"] += 1

    def contact(self, mono, q):
        if self.closed: return
        row = [f"{mono:.6f}"]
        for lvl, sig, mains in q: row += [lvl, f"{sig:.3f}", f"{mains:.3f}"]
        self.files["contact"][1].writerow(row); self.rows["contact"] += 1

    def log(self, text):
        if self.closed: return
        self.log_f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    def close(self, stop_reason, extra=None):
        if self.closed: return
        self.log(f"stop: {stop_reason}")
        for f, _ in self.files.values(): f.close()
        self.log_f.close()
        self.config.update(completed=stop_reason == "completed", stop_reason=stop_reason, rows=dict(self.rows),
                           stopped_unix=time.time(), **(extra or {}))
        self._write_config()
        self.closed = True


def load(folder):
    """dict(config, labels, eeg_header, imu_header) — the signal CSVs are left on disk for the replay tool."""
    folder = Path(folder)
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    with open(folder / "labels.csv", newline="", encoding="utf-8") as f:
        labels = list(csv.DictReader(f))
    heads = {}
    for name in ("eeg", "imu"):
        with open(folder / f"{name}.csv", newline="", encoding="utf-8") as f:
            heads[name] = next(csv.reader(f))
    return dict(config=config, labels=labels, eeg_header=heads["eeg"], imu_header=heads["imu"], folder=folder)
