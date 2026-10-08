"""Replay a recorded session to extensions in a review window (API 2).

The recording is cut into chunks of CHUNK_SEC per stream; chunks of all streams and the events are
merged in time order (by the display time of each chunk's last sample; an event comes after the data
up to its time). For each chunk the replay store's cursor is moved to that chunk, so ``app.store``
reads exactly what had arrived by then, and the chunk goes to on_eeg / on_optics / on_imu with the raw
unix timestamp of its last sample — the same contract as live. Chunks are float64 copies, as live.

``step(budget_sec)`` does as much as fits in the time budget, so a QTimer can drive it without
blocking the window; ``progress`` goes 0 → 1.
"""
import time

import numpy as np

CHUNK_SEC = 0.1
STREAM_HOOK = {"eeg": "on_eeg", "opt": "on_optics", "imu": "on_imu"}
EVENT = 3


class Replay:
    def __init__(self, manager, store, events=(), chunk_sec=CHUNK_SEC):
        """manager: the review window's ExtensionManager; store: a ReviewStore cursor of its own (fork())."""
        self.manager, self.store = manager, store
        keys = list(STREAM_HOOK)
        times, codes, ends = [], [], []
        for code, k in enumerate(keys):
            n = len(store.ts[k])
            if n == 0 or not manager._subs[STREAM_HOOK[k]]: continue
            step = max(1, int(round(chunk_sec * store.fs[k])))
            e = np.unique(np.minimum(np.arange(step, n + step, step), n))
            times.append(store.t_rel[k][e - 1]); codes.append(np.full(len(e), code)); ends.append(e)
        self.events = list(events)
        if self.events and manager._subs["on_event"]:
            times.append(np.array([t - store.t0 for t, _ in self.events]))
            codes.append(np.full(len(self.events), EVENT)); ends.append(np.arange(len(self.events)))
        if times:
            t, c, e = np.concatenate(times), np.concatenate(codes), np.concatenate(ends)
            order = np.lexsort((c, t))                       # time, then streams before events
            self.t, self.codes, self.ends = t[order], c[order], e[order]
        else:
            self.t = self.codes = self.ends = np.empty(0, dtype=int)
        self.keys = keys
        self.pos = 0
        self.starts = dict.fromkeys(keys, 0)

    @property
    def total(self):
        return len(self.t)

    @property
    def done(self):
        return self.pos >= self.total

    @property
    def progress(self):
        return 1.0 if not self.total else self.pos / self.total

    def step(self, budget_sec=0.03):
        st, m = self.store, self.manager
        deadline = time.perf_counter() + budget_sec
        while self.pos < self.total:
            code, end, t = int(self.codes[self.pos]), int(self.ends[self.pos]), float(self.t[self.pos])
            self.pos += 1
            if code == EVENT:
                ev_t, label = self.events[end]
                st.set_view_end(t)
                m.dispatch("on_event", ev_t, label)
            else:
                k = self.keys[code]
                start, self.starts[k] = self.starts[k], end
                st.set_view_end(t)
                x = np.array(st.views[k].x[:, start:end], dtype=np.float64)
                m.dispatch(STREAM_HOOK[k], x, float(st.ts[k][end - 1]))
            if time.perf_counter() >= deadline: break
        return self.done

    def run(self):
        """Replay everything at once (tests, small sessions)."""
        while not self.step(1.0): pass
