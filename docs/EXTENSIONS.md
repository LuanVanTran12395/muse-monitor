# Writing extensions for Muse Monitor

An extension is a Python file or folder that Muse Monitor loads at startup. It can read live
signals, add tabs and menu actions, react to events and recordings, and write its own files,
without changing the app's code.

## 1. Create one

```bash
PYTHONPATH=src python -m musemonitor.plugins new "My Extension"
```

You can also use **Extensions ▸ Manage extensions… ▸ New extension…** in the app.
Both create `extensions/my_extension/__init__.py` from a working template (a tab plus a menu action).
Edit it, then press **⟳ Update** in the Manage dialog (or **Extensions ▸ Check for new extensions**):
it appears under **Extensions** and as a new tab on the recording screen, without restarting the app.

**Update** loads extensions that were added since the app started, and retries ones that failed to
import (fix the file, press Update again). An extension loaded this way first receives
`on_theme_changed`, then `on_connected` if a device is streaming, then `on_recording_started` if a
recording is running, so it starts in the same state as the app. Changes to the code of an
extension that is already loaded, and enabling/disabling, still need a restart. Events marked
before the extension was loaded are not drawn on its plots.

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
| `requires_api` | minimum `API_VERSION` needed (currently `1`); newer requirements are refused |
| `supports(spec)` (classmethod) | return `False` when the connected device lacks what you need (e.g. `{"AF7","TP9"} <= set(spec.eeg.names)` or `spec.imu.n >= 6`); the extension then shows **not applicable** instead of failing. Default `True` |
| `activate(app)` | once at startup. Add tabs and actions, and set up state here |
| `deactivate()` | app closing or extension disabled after an error. Close files, stop threads |
| `on_eeg(x, ts)` | each EEG chunk. `x`: `(4, k)` µV, unfiltered; `ts`: Unix time of the last sample |
| `on_optics(x, ts)` | each optics chunk, `(16, k)` raw intensities |
| `on_imu(x, ts)` | each IMU chunk, `(6, k)`: acc x/y/z (g) + gyro x/y/z (°/s) |
| `on_event(t, label)` | an event was marked (Space key or `app.mark_event`) |
| `on_recording_started(path)` / `on_recording_stopped()` | recording toggled; `path` is the EEG `.csv` |
| `on_connected(name)` / `on_disconnected()` | stream started / stopped |
| `on_theme_changed(theme)` | the light/dark colour dict (see `ui/theme.py`) |

## 5. The `app` object (`ExtensionContext`)

| Member | Description |
|---|---|
| `app.spec` | channels and rates: `spec.eeg.fs`, `spec.eeg.names`, `spec.optics.n`… |
| `app.store` | signal history: `store.eeg`, `store.eeg_f` (filtered), `store.opt`, `store.imu` are ring buffers; `.get(n)` returns the last `n` samples as `(channels, n)`. `store.eeg_display(n)` matches what the Signals tab shows. `store.last_ts[...]` |
| `app.add_tab(TabClass)` | add a tab (a `BaseTab` subclass, or an instance) |
| `app.add_action(text, fn, shortcut=None)` | add an item to the **Extensions** menu |
| `app.mark_event(label, t=None)` | create an event, the same as pressing Space |
| `app.show_status(msg)` | status-bar message |
| `app.setting(key, default, type=None)` / `app.set_setting(key, value)` | persistent per-extension settings |
| `app.data_dir` | private folder `~/.musemonitor/data/<id>/` |
| `app.is_streaming`, `app.is_recording`, `app.recording_path`, `app.window_sec`, `app.theme` | current state |
| `app.view` | `ViewContext`, if you construct a `BaseTab` yourself |
| `app.main_window` | direct access to the main window. **Not stable** between versions; avoid it |

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
  New extensions can be added while the app runs with **⟳ Update**.
- **Unload / Load** (Manage dialog, select a row): removes a running extension right away for this
  session — its hooks stop, `deactivate()` is called, and its tabs and menu items disappear. **Load**
  starts it again with a fresh instance (it receives the same catch-up hooks as Update). This does
  not change the Enabled setting; untick Enabled to keep it off at the next start.
- Import from `musemonitor.plugins.api`. Using `musemonitor.core.*` (filters, PSD, PPG/HRV, fNIRS)
  is fine too. Avoid `musemonitor.ui.*` internals other than `BaseTab`; they may change.
- Third-party libraries your extension needs must be installed in the app's venv
  (`~/.venvs/musemonitor/bin/pip install …`).

## 8. Testing an extension

Load it in a test window with synthetic data. `tests/test_plugins.py` shows how:

```python
w = MainWindow(spec, settings=temp_settings, extension_dirs=["path/to/your/extensions"])
w.on_data(eeg_chunk, ts)   # drive hooks without a headset
```
