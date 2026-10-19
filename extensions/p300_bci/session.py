"""P300 session folder: files, a bounded writer thread, clean close, integrity check, loader (no Qt).

    <app data folder>/p300_bci/<YYYYmmdd_HHMMSS>[_2…]/      (default <repo>/data/p300_bci, git-ignored)
        config.json   parameters, versions, device, contact, mode; completed / stop_reason / rows_written at close
        stimuli.csv   one row per flash: planned / fired / painted (on) and painted (off) monotonic times
        trials.csv    one row per trial: target, cue, start, end, aborted
        keys.csv      response_assisted mode only: key presses, kept apart from flash times
        eeg.csv       one row per sample: index, raw receive time (unix), the same in the monotonic clock,
                      online timeline estimate, segment, flag reason, channels (µV, unfiltered)
        clock.csv     every ClockBridge measurement: mono, unix, offset, stepped
        contact.csv   electrode contact every ~2 s: level, signal RMS and mains RMS per channel
        report.html   P300 / ERP / epochs / electrodes / timing report (report.py), written after the session
        timing.json   timing report (timing.summarize)
        log.txt       start / stop / reasons / errors

Writes happen in one thread fed by a BOUNDED queue. A full queue is an error (the caller stops the session):
EEG is never dropped silently. Folders are never overwritten.
"""
import csv
import json
import queue
import threading
import re
import time
from pathlib import Path

import numpy as np

STIM_FIELDS = ["seq", "block", "trial", "rep", "cell", "is_target", "planned_mono", "fired_mono", "painted_mono",
               "off_planned_mono", "off_fired_mono", "off_painted_mono", "late_ms", "missed"]
TRIAL_FIELDS = ["trial", "block", "target", "cue_on_mono", "start_mono", "end_mono", "aborted"]
KEY_FIELDS = ["key", "qt_timestamp_ms", "handled_mono", "handled_unix"]
CLOCK_FIELDS = ["mono", "unix", "offset", "stepped"]
EEG_FIXED = ["index", "ts_raw_unix", "r_mono", "t_mono_online", "segment", "flag"]
QUEUE_MAX = 3000            # items (EEG chunks ≈ 20/s, stimuli ≈ 5/s): roughly half a minute of backlog
FLUSH_S = 1.0


SUBJECT_RE = r"[A-Za-z0-9_-]{1,32}"          # subject IDs: safe in a folder name on every OS, no personal names needed


def new_folder(root, stamp=None, subject=None):
    """A fresh session folder under ``root`` — never an existing one: ``<YYYYMMDD_HHMMSS>[_<subject>]`` so folders
    sort by time and can be found by subject."""
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    stamp = stamp or time.strftime("%Y%m%d_%H%M%S")
    if subject:
        if not re.fullmatch(SUBJECT_RE, subject): raise ValueError(f"invalid subject ID {subject!r}")
        stamp = f"{stamp}_{subject}"
    folder, k = root / stamp, 2
    while folder.exists():
        folder = root / f"{stamp}_{k}"; k += 1
    folder.mkdir()
    return folder


def _fmt(v):
    if v is None: return ""
    if isinstance(v, bool): return "1" if v else "0"
    if isinstance(v, float): return f"{v:.6f}"
    return str(v)


class SessionWriter:
    def __init__(self, folder, config, channels, response_keys=False):
        self.folder = Path(folder)
        self.config = dict(config, completed=False, stop_reason=None)
        self.channels = list(channels)
        self.q = queue.Queue(maxsize=QUEUE_MAX)
        self.rows = dict(stimuli=0, trials=0, keys=0, eeg=0, clock=0, contact=0)
        self.backlog_max = 0
        self.error = None                     # set by the thread when writing fails
        self.close_timed_out = False
        self.finished = threading.Event()
        self._eeg = dict(index=[], ts_raw=[], r=[], t_online=[], segment=[], uncertain=[])
        self._stims = []
        self._write_json("config.json", self.config)
        self._files = {}
        self._open("stimuli.csv", STIM_FIELDS); self._open("trials.csv", TRIAL_FIELDS)
        self._open("clock.csv", CLOCK_FIELDS); self._open("eeg.csv", EEG_FIXED + self.channels)
        self._open("contact.csv", ["mono"] + [f"{c}_{k}" for c in self.channels for k in ("level", "signal_uv", "mains_uv")])
        if response_keys: self._open("keys.csv", KEY_FIELDS)
        self._log = open(self.folder / "log.txt", "a", encoding="utf-8")
        self.thread = threading.Thread(target=self._run, name="p300-writer", daemon=True)
        self.thread.start()

    # ---- producer side (GUI thread) -------------------------------------------------------------------
    def put(self, kind, payload):
        """Queue a record; False when the queue is full or the writer failed (the caller must stop the session)."""
        if self.error or self.finished.is_set(): return False
        try:
            self.q.put_nowait((kind, payload))
        except queue.Full:
            return False
        self.backlog_max = max(self.backlog_max, self.q.qsize())
        return True

    def close(self, stop_reason, timing=None, timeout_s=2.0):
        """Ask the thread to drain, write timing.json and the final config, close the files. Waits at most
        ``timeout_s`` (never blocks the GUI indefinitely); returns True when it finished in time."""
        try:
            self.q.put((("close", (stop_reason, timing))), timeout=timeout_s)
        except queue.Full:
            self.close_timed_out = True
            return False
        if not self.finished.wait(timeout_s):
            self.close_timed_out = True                   # the thread finishes on its own and records it
            return False
        return True

    # ---- writer thread ------------------------------------------------------------------------------------
    def _open(self, name, fields):
        f = open(self.folder / name, "w", newline="", encoding="utf-8")
        w = csv.writer(f); w.writerow(fields)
        self._files[name] = (f, w)

    def _write_json(self, name, data):
        tmp = self.folder / (name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=_json_default), encoding="utf-8")
        tmp.replace(self.folder / name)

    def _run(self):
        last_flush = time.monotonic()
        while True:
            try:
                kind, payload = self.q.get(timeout=0.5)
            except queue.Empty:
                kind = None
            try:
                if kind == "close":
                    self._finish(*payload); return
                if kind is not None: self._handle(kind, payload)
                if time.monotonic() - last_flush > FLUSH_S:
                    for f, _ in self._files.values(): f.flush()
                    self._log.flush(); last_flush = time.monotonic()
            except Exception as e:                        # disk full, permission, bug: stop accepting, keep the error
                self.error = f"{type(e).__name__}: {e}"
                try: self._finish("writer_error", None)
                except Exception: pass
                return

    def _handle(self, kind, p):
        if kind == "eeg":
            index0, ts_raw, r, t_online, segment, flag, x = p
            n = x.shape[1]
            idx = np.arange(index0, index0 + n)
            f, w = self._files["eeg.csv"]
            for i in range(n):
                w.writerow([idx[i], f"{ts_raw[i]:.6f}", f"{r[i]:.6f}", f"{t_online[i]:.6f}", segment, flag or ""]
                           + [f"{v:.3f}" for v in x[:, i]])
            self.rows["eeg"] += n
            e = self._eeg
            e["index"].append(idx); e["ts_raw"].append(np.asarray(ts_raw, float)); e["r"].append(np.asarray(r, float))
            e["t_online"].append(np.asarray(t_online, float)); e["segment"].append(np.full(n, segment))
            e["uncertain"].append(np.full(n, bool(flag)))
        elif kind == "stim":
            self._files["stimuli.csv"][1].writerow([_fmt(p.get(k)) for k in STIM_FIELDS]); self.rows["stimuli"] += 1
            self._stims.append(p)
        elif kind == "trial":
            self._files["trials.csv"][1].writerow([_fmt(p.get(k)) for k in TRIAL_FIELDS]); self.rows["trials"] += 1
        elif kind == "key" and "keys.csv" in self._files:
            self._files["keys.csv"][1].writerow([_fmt(p.get(k)) for k in KEY_FIELDS]); self.rows["keys"] += 1
        elif kind == "contact":
            mono, q = p                                   # q: [(level, signal RMS, mains RMS)] per channel
            row = [f"{mono:.6f}"]
            for level, sig, mains in q: row += [level, f"{sig:.3f}", f"{mains:.3f}"]
            self._files["contact.csv"][1].writerow(row); self.rows["contact"] += 1
        elif kind == "clock":
            self._files["clock.csv"][1].writerow([_fmt(v) for v in p]); self.rows["clock"] += 1
        elif kind == "log":
            self._log.write(f"{time.strftime('%H:%M:%S')} {p}\n")

    def eeg_arrays(self):
        cat = lambda k: np.concatenate(self._eeg[k]) if self._eeg[k] else np.empty(0)
        return {k: cat(k) for k in self._eeg}

    def stims(self):
        return list(self._stims)

    def _finish(self, stop_reason, timing):
        try:
            while True:                                   # anything queued before "close"
                kind, payload = self.q.get_nowait()
                if kind != "close": self._handle(kind, payload)
        except queue.Empty:
            pass
        if callable(timing):                              # computed here, off the GUI thread
            try: timing = timing(self)
            except Exception as e: timing = dict(error=f"timing report failed: {type(e).__name__}: {e}")
        if timing is not None: self._write_json("timing.json", timing)
        for f, _ in self._files.values(): f.close()
        reason = "writer_error" if self.error else stop_reason
        self._log.write(f"{time.strftime('%H:%M:%S')} stop: {reason}" + (f" ({self.error})" if self.error else "") + "\n")
        self._log.close()
        self.config.update(completed=reason == "completed", stop_reason=reason, rows_written=dict(self.rows),
                           writer=dict(backlog_max=self.backlog_max, queue_max=QUEUE_MAX, error=self.error,
                                       close_timed_out=self.close_timed_out),
                           stopped_unix=time.time())
        self._write_json("config.json", self.config)
        self.finished.set()


def _json_default(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    return str(o)


# ---- reading back --------------------------------------------------------------------------------------
def _rows(path):
    if not path.exists(): return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v):
    if v in ("", None): return None
    try: return int(v)
    except ValueError: return float(v)


def load(folder):
    """dict(config, stimuli, trials, keys, eeg) — eeg: arrays index, ts_raw, r, t_online, segment, flag, data (ch × n)."""
    folder = Path(folder)
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    stimuli = [{k: _num(v) for k, v in r.items()} for r in _rows(folder / "stimuli.csv")]
    trials = [{k: _num(v) for k, v in r.items()} for r in _rows(folder / "trials.csv")]
    keys = [{k: (_num(v) if k != "key" else v) for k, v in r.items()} for r in _rows(folder / "keys.csv")]
    channels = config.get("channels", [])
    with open(folder / "eeg.csv", newline="", encoding="utf-8") as f:
        reader = csv.reader(f); header = next(reader)
        rows = list(reader)
    col = {h: i for i, h in enumerate(header)}
    n = len(rows)
    get = lambda name, typ=float: np.array([typ(r[col[name]]) if r[col[name]] != "" else np.nan for r in rows],
                                           dtype=float) if n else np.empty(0)
    eeg = dict(index=get("index"), ts_raw=get("ts_raw_unix"), r=get("r_mono"), t_online=get("t_mono_online"),
               segment=get("segment"), flag=np.array([r[col["flag"]] for r in rows], dtype=object),
               data=np.array([[float(r[col[c]]) for r in rows] for c in channels]) if n else np.empty((len(channels), 0)))
    contact = []
    for r in _rows(folder / "contact.csv"):                # older sessions have no contact.csv
        contact.append(dict(mono=float(r["mono"]), channels={
            c: (r[f"{c}_level"], float(r[f"{c}_signal_uv"]), float(r[f"{c}_mains_uv"])) for c in channels
            if f"{c}_level" in r}))
    return dict(config=config, stimuli=stimuli, trials=trials, keys=keys, eeg=eeg, contact=contact, folder=folder)


def check(folder):
    """Integrity of a session folder → (ok, list of findings). Incomplete sessions can still be analysed (labelled)."""
    folder = Path(folder)
    findings = []
    try:
        s = load(folder)
    except Exception as e:
        return False, [f"cannot read: {type(e).__name__}: {e}"]
    cfg = s["config"]
    if not cfg.get("completed"): findings.append(f"incomplete: stop_reason = {cfg.get('stop_reason')!r}")
    written = cfg.get("rows_written")
    if written is None:
        findings.append("rows_written missing (the writer did not finish)")
    else:
        for name, got in (("stimuli", len(s["stimuli"])), ("trials", len(s["trials"])), ("eeg", len(s["eeg"]["index"]))):
            if written.get(name) != got: findings.append(f"{name}: {got} rows on disk, {written.get(name)} written")
    seqs = [r["seq"] for r in s["stimuli"]]
    if seqs and seqs != list(range(seqs[0], seqs[0] + len(seqs))): findings.append("stimuli: seq not continuous")
    idx = s["eeg"]["index"]
    if len(idx) and np.any(np.diff(idx) != 1): findings.append("eeg: sample index not continuous")
    w = cfg.get("writer") or {}
    if w.get("error"): findings.append(f"writer error: {w['error']}")
    if w.get("close_timed_out"): findings.append("close timed out on the GUI side (the writer finished later)")
    return not findings, findings
