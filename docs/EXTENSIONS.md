# Writing extensions for Muse Monitor

An extension is a Python file or folder that Muse Monitor loads at startup. It can read live
signals, add tabs and menu actions, react to events and recordings, and write its own files,
without changing the app's code.

## 1. Create one

```bash
PYTHONPATH=src python -m musemonitor.plugins new "My Extension"                 # category suggested from the name
PYTHONPATH=src python -m musemonitor.plugins new "Jaw Alert" --category "Data quality"
```

You can also use **Extensions ▸ Manage extensions… ▸ New extension…** in the app.
Both create `extensions/my_extension/__init__.py` from a working template (a panel plus a menu action)
and tell you where it will appear, e.g. `Analysis ▸ EEG ▸ Alpha Peak`. Edit it, then press **⟳ Update**
in the Manage dialog (or **Extensions ▸ Check for new extensions**), without restarting the app.

### Where your extension appears

| What | Where | Decided by |
|---|---|---|
| Panel (each `app.add_tab`) | **Analysis** or **HCI/BCI** menu, in a group; the tab shows only while ticked there | `category` |
| Actions (`app.add_action`) | **Extensions ▸ ‹extension name› ▸ …** | the extension's `name` |
| Status, errors, Enable, Unload/Load | **Extensions ▸ Manage extensions…** (column *Menu* shows the placement) | — |

| `category` | Menu |
|---|---|
| `"EEG"`, `"Heart & optics"`, `"Data quality"`, `"Other"` (default, also for unknown values) | **Analysis** |
| `"Eyes"`, `"Motion"` — interaction / brain-computer interface panels | **HCI/BCI** |

Panels start **hidden**; the first time a new panel is loaded, the status bar says where to find it.
The user's ticks are remembered (separately for the live window and review windows). The three built-in
tabs (Signals, EEG PSD, PPG · HRV · fNIRS) always show. Pass `app.add_tab(MyTab, shown=True)` to show a
panel the first time only; after that, the user's choice wins.

**Update** loads extensions that were added since the app started, and retries ones that failed to
import (fix the file, press Update again). An extension loaded this way first receives
`on_theme_changed`, then `on_connected` if a device is streaming, then `on_recording_started` if a
recording is running, so it starts in the same state as the app. Enabling/disabling still needs a
restart. Events marked before the extension was loaded are not drawn on its plots.

### Reload after editing (no restart)

Edit your extension's file, then press **⌘⇧R** (**Extensions ▸ Reload changed extensions**), or select
it in **Manage** and press **Reload**. The app:

1. stops the running instance: its hooks stop, `deactivate()` is called, its tabs, menu items and status
   message are removed (an extension that crashed earlier is cleaned up the same way);
2. imports the file again from disk — for a folder extension, every module of the folder, with its
   cached bytecode discarded so an edit saved within the same second is not missed;
3. starts the new code (unless it is disabled in Manage) with the same catch-up hooks as Update; its
   panels come back ticked or not as they were, in the same place in the menus.

*Reload changed extensions* reloads only extensions whose `.py` files changed since they were loaded,
including ones that failed to import (fix the file, press ⌘⇧R again). If the new code fails, the
extension shows **✕ Error** with the traceback in Manage; the app and the device stream keep running.

Limits: reload is refused **while recording** (stop first — it would cut the extension's files in the
middle of the recording), in **review windows** (reload in the live window, then open the recording
again), and for extensions **installed as pip packages** (restart the app). Release everything your
extension holds — files, sockets, LSL outlets, cameras, threads — in `deactivate()`, otherwise the old
instance keeps them after a reload. Modules your extension imports from *outside* its own folder are not
re-imported.

To check what the app will load:

```bash
PYTHONPATH=src python -m musemonitor.plugins list
```

## 2. Where extensions are loaded from

| Location | Use it for |
|---|---|
| `extensions/` in this project | extensions developed alongside the app |
| `~/.musemonitor/extensions/` | personal extensions, kept outside the repo |
| folders in `$MUSEMONITOR_EXTENSIONS` (`:`-separated) | anything else, e.g. a separate git repo |
| pip packages with an entry point in group `musemonitor.extensions` | distributable extensions |

Each extension is either a single `name.py` file or a folder `name/` with `__init__.py`.
Inside a folder, relative imports work (`from .model import Classifier`).
Names starting with `_` or `.` are ignored.

As a pip package, declare the entry point in its own `pyproject.toml`:

```toml
[project.entry-points."musemonitor.extensions"]
my_extension = "my_package.extension:MyExtension"
```

## 3. Minimal extension

```python
from musemonitor.plugins.api import Extension

class Hello(Extension):
    name = "Hello"
    version = "1.0.0"
    description = "Says hello."

    def activate(self, app):
        app.add_action("Say hello", lambda: app.show_status("Hello!"))

    def on_event(self, t, label):
        print("event", t, label)

EXTENSION = Hello
```

See `extensions/hello_world.py` (minimal) and `extensions/band_power/` (complete: data hook, tab,
recording to `<rec>_bandpower.csv`, menu action, setting).

## 4. The `Extension` class

Override only what you need. A hook you don't override is never called.

| Attribute / hook | When / what |
|---|---|
| `id`, `name`, `version`, `description`, `author` | metadata shown in the manager (`id` defaults to the file or folder name) |
| `requires_api` | minimum `API_VERSION` needed (the app provides `3`); newer requirements are refused. `1` and `2` still work |
| `category` | API 2. Menu placement of the extension's panels — see [Where your extension appears](#where-your-extension-appears). Default `"Other"` |
| `supports_review` | API 2. `True` = also run in review windows (**File ▸ Open session**); default `False` (shown as *not applicable* there). See [Review windows](#9-review-windows-api-2) |
| `supports(spec)` (classmethod) | return `False` when the connected device lacks what you need (e.g. `{"AF7","TP9"} <= set(spec.eeg.names)` or `spec.imu.n >= 6`); the extension then shows **not applicable** instead of failing. Default `True` |
| `activate(app)` | once at startup. Add tabs and actions, and set up state here |
| `deactivate()` | app closing or extension disabled after an error. Close files, stop threads |
| `on_eeg(x, ts)` | each EEG chunk. `x`: `(4, k)` µV, unfiltered; `ts`: Unix time of the last sample |
| `on_optics(x, ts)` | each optics chunk, `(16, k)` raw intensities |
| `on_imu(x, ts)` | each IMU chunk, `(6, k)`: acc x/y/z (g) + gyro x/y/z (°/s) |
| `on_eeg_samples(x, ts_raw)`, `on_optics_samples(x, ts_raw)`, `on_imu_samples(x, ts_raw)` | API 3, live window only: the same chunk, called right after the hook above, with `ts_raw` = float64 `(k,)` Unix timestamp of **every** sample, exactly as written to the CSV. See [Per-sample timestamps](#10-per-sample-timestamps-api-3) |
| `on_event(t, label)` | an event was marked (Space key or `app.mark_event`) |
| `on_recording_started(path)` / `on_recording_stopped()` | recording toggled; `path` is the EEG `.csv` |
| `on_connected(name)` / `on_disconnected()` | stream started / stopped |
| `on_theme_changed(theme)` | the light/dark colour dict (see `ui/theme.py`) |
| `on_view_changed(t_end)` | API 2, review windows only: the view now ends at Unix time `t_end` (scroll, event jump, Time range) |

## 5. The `app` object (`ExtensionContext`)

| Member | Description |
|---|---|
| `app.spec` | channels and rates: `spec.eeg.fs`, `spec.eeg.names`, `spec.optics.n`… |
| `app.store` | signal history: `store.eeg`, `store.eeg_f` (filtered), `store.opt`, `store.imu` are ring buffers; `.get(n)` returns the last `n` samples as `(channels, n)`. `store.eeg_display(n)` matches what the Signals tab shows. `store.last_ts[...]` |
| `app.add_tab(TabClass, title=None, shown=None)` | add a panel (a `BaseTab` subclass, or an instance); listed under `category` in Analysis or HCI/BCI, hidden until ticked |
| `app.add_action(text, fn, shortcut=None)` | add an item to **Extensions ▸ ‹name›** (no need to prefix the text with the extension name) |
| `app.mark_event(label, t=None)` | create an event, the same as pressing Space |
| `app.show_status(msg, ms=5000)` | short message in the status bar, in its own slot next to the app's messages (see below) |
| `app.setting(key, default, type=None)` / `app.set_setting(key, value)` | persistent per-extension settings |
| `app.data_dir` | private folder `~/.musemonitor/data/<id>/` |
| `app.is_streaming`, `app.is_recording`, `app.recording_path`, `app.window_sec`, `app.theme` | current state |
| `app.is_review`, `app.view_end` | API 2: `True` in a review window; Unix time of the right edge of the view there (`None` live) |
| `app.view` | `ViewContext`, if you construct a `BaseTab` yourself |
| `app.main_window` | direct access to the main window. **Not stable** between versions; avoid it |

**`show_status` details.** The message is shown as plain text (no HTML), on one line (line breaks become
` · `), prefixed with 🧩 and your extension id; text longer than 90 characters is cut, with the full text
in the tooltip. It clears itself after `ms` milliseconds, **at most 15 s**; `ms <= 0` means 15 s (not
"until replaced" as in Qt), an unusable value (`None`, text) means 5 s. There is one slot: a newer message
from any extension replaces it. `app.show_status("")` clears your own message; it is also cleared when
your extension is unloaded, reloaded or fails. Call it from the GUI thread (all hooks run there).

To write a file next to a recording, use
`musemonitor.storage.recording.companion_path(path, "suffix")`, which gives `<rec>_suffix.csv`.

## 6. Tabs

```python
import numpy as np, pyqtgraph as pg
from PySide6 import QtWidgets
from musemonitor.plugins.api import BaseTab

class MyTab(BaseTab):
    title = "My tab"

    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QtWidgets.QVBoxLayout(self)
        pw = ctx.plots.widget(pg.PlotWidget())               # registered → follows the theme
        self.plot = ctx.plots.plot(pw.getPlotItem(), marker="eeg")  # time range + event markers
        self.curve = self.plot.plot()
        layout.addWidget(pw)

    def on_analysis(self):          # ~4×/s while the tab is visible
        st, fs = self.ctx.store, self.ctx.spec.eeg.fs
        n = min(st.eeg_f.n, int(self.ctx.window_sec * fs))
        if n > 1:
            self.curve.setData((np.arange(n) - n) / fs, st.eeg_display(n)[0])

    def apply_theme(self, th):
        self.curve.setPen(pg.mkPen(th["eeg"][0]))

    def clear(self):
        self.curve.clear()
```

**Keys.** On the Recording screen the app reserves **Space** (mark an event with a label) and **1–9**
(quick event), except while typing in a text field or spin box. A tab that needs these keys — a BCI
speller, a game, a keypad — claims them while the keyboard focus is inside it:

```python
class Speller(BaseTab):
    wants_keys = {QtCore.Qt.Key_1, QtCore.Qt.Key_2, QtCore.Qt.Key_3}   # or: wants_all_keys = True
    def __init__(self, ctx):
        super().__init__(ctx)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)                  # so the tab can have the focus
    def keyPressEvent(self, ev): ...
```

Keys it does not claim keep their app meaning, and outside the tab everything works as before.
`app.add_action(text, fn, shortcut=...)` shortcuts must not clash with the app's: ⌘N, ⌘O, ⌘W, ⌘R
(record), ⌘T (fit-test), ⌘⇧R (reload extensions).

Tab hooks: `on_frame` (20×/s while visible), `on_analysis` (4×/s while visible),
`update_texts` (2×/s), `on_view_changed` (time range or filter changed), `apply_theme`, `clear`
(new connection). Create plots through `ctx.plots.plot(...)` with `marker="eeg" | "opt" | "imu"`
to get the shared time axis, theme colours and event lines. Use `ctx.plots.muted_label(text)` for
secondary text.

## 7. Rules of thumb

- **Everything runs on the GUI thread.** `on_eeg` is called about 50× per second, so keep it to a
  few microseconds (count samples, append to a list). Do the heavy work in `on_analysis`, every N
  seconds as `band_power` does, or in your own thread. Only touch Qt widgets from the GUI thread.
- **Errors are contained.** If a hook, action or tab raises, that extension is disabled for the
  session, its tab is greyed out, and the traceback appears in **Extensions ▸ Manage** and on stderr.
  The app and other extensions keep running.
- **Enable/disable** in **Extensions ▸ Manage**; the change applies on the next start.
  New extensions can be added while the app runs with **⟳ Update**; edited ones are reloaded with
  **⌘⇧R** (see *Reload after editing*).
- **Unload / Load** (Manage dialog, select a row): removes a running extension right away for this
  session — its hooks stop, `deactivate()` is called, and its tabs and menu items disappear. **Load**
  starts it again with a fresh instance (it receives the same catch-up hooks as Update). This does
  not change the Enabled setting; untick Enabled to keep it off at the next start.
- Import from `musemonitor.plugins.api`. Using `musemonitor.core.*` (filters, PSD, PPG/HRV, fNIRS)
  is fine too.
  For steps the user cannot watch (eyes closed, head turned), `musemonitor.plugins.cues.Cues` plays
  short GO / done / repeat tones: `cues = Cues(); cues.play("go")` (used by eye_interaction and
  head_motion_plus). Avoid `musemonitor.ui.*` internals other than `BaseTab`; they may change.
- Third-party libraries your extension needs must be installed in the app's venv
  (`~/.venvs/musemonitor/bin/pip install …`).

## 8. Testing an extension

Load it in a test window with synthetic data. `tests/test_plugins.py` shows how:

```python
w = MainWindow(spec, settings=temp_settings, extension_dirs=["path/to/your/extensions"])
w.on_data(eeg_chunk, ts)   # drive hooks without a headset
```

## 9. Review windows (API 2)

**File ▸ Open session** opens a recording in its own window. Extensions run there only if they set
`supports_review = True`; each review window has its own instances, separate from the live window.

What happens:

1. `activate(app)` is called with `app.is_review == True`. Size your state for a whole session
   (e.g. `band_power` keeps its full history instead of the last 900 points).
2. The recording is **replayed** to you in the background: chunks of 0.1 s per stream, all streams and
   events merged in time order (an event comes after the data up to its time). Each chunk goes to
   `on_eeg` / `on_optics` / `on_imu` with the raw Unix timestamp of its last sample, as live. During
   the hook, `app.store` holds exactly what had arrived by then, so code that reads
   `app.store.eeg_display(n)` in `on_eeg` works unchanged. Chunk sizes differ from live (live chunks
   follow BrainFlow polling), so stateful code should not depend on chunk size.
3. When the replay is done, and every time the user scrolls, `on_view_changed(t_end)` is called.
   Tabs read `ctx.store` as usual: its newest sample is at the scroll position. Draw on the shared
   axis with `x = t - ctx.store.time_ref("eeg")` and keep only items with `t <= ctx.store.last_ts["eeg"]`
   — this works in both the live and the review window.

Limits in a review window (nothing is written next to the recording):

- `on_recording_started` / `on_connected` are never called; `app.is_recording` is `False`.
- `app.mark_event` draws a temporary marker and adds it to the event list; no file is written.
- `app.set_setting` is kept in memory for that window; QSettings is not changed.
- `app.add_action` adds to that window's **Extensions** menu; panels are ticked in that window's
  Analysis / HCI/BCI menus, remembered separately from the live window.
- **Unload / Load** works, but a re-loaded extension does not get the replay again — reopen the
  recording for that.

Bundled extensions with review support: `hello_world`, `band_power`, `artifact_log`. The others
(`eye_interaction`, `head_motion`, `head_motion_plus`) show real-time state (avatar, head pose,
camera) and stay live-only.

## 10. Per-sample timestamps (API 3)

`on_eeg(x, ts)` gives only the timestamp of the chunk's last sample. When you need the time of every
sample (streaming to another program, precise alignment), override the API 3 hook instead or as well:

```python
class MyExt(Extension):
    requires_api = 3

    def on_eeg_samples(self, x, ts_raw):
        # x: (n_ch, k) µV, unfiltered; ts_raw: np.float64 array of length k
        ...
```

- `ts_raw` is the vector the worker delivered and the CSV records, unmodified. It is the **host
  receive time**, not a device clock: with Muse S Athena (BrainFlow over BLE) samples of one packet
  often share a value, values can jump by tens of milliseconds between packets, and IMU values can
  step back slightly. Smooth it yourself if your use needs a regular time axis.
- A worker that sends only the last timestamp gets it expanded at the nominal sampling rate.
- Called after the API 1 hook of the same chunk; if no extension overrides it, the app does no extra
  work. An error in it disables only that extension, like any hook.
- Live window only: review windows replay recordings through the API 1 hooks and never call these.
- `extensions/lsl_outlet` is a complete example: it smooths `ts_raw` with
  `musemonitor.core.online_timeline.OnlineTimeline` and streams it to Lab Streaming Layer.
