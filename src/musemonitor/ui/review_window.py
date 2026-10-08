"""Review window: one recorded session, scrollable, in its own window (the live window keeps running).

Reuses RecordingPage and the built-in tabs on a core.review.ReviewStore. A time scrollbar moves the
cursor; Time range sets the width of the view; the event list jumps to an event. Extensions are not
loaded here (phase 1 — see debate/claude-session-review-round-2.md).
"""
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import config as C
from ..core.quality import contact_quality
from ..core.review import ReviewStore
from ..device.profiles import discover_profiles
from ..device.spec import generic_spec
from ..storage.reader import ReadCancelled, ReaderError, inspect, load, locate
from ..storage.session import data_root
from .context import ViewContext
from .markers import EventMarkers
from .pages import RecordingPage
from .plotkit import PlotRegistry
from .theme import THEMES, DEFAULT_THEME, apply_app_theme

SCROLL_UNIT = 0.1                 # seconds per scrollbar step
GENERIC = "Other device — estimate sampling rates from timestamps"
FILE_FILTER = "Muse Monitor recordings (session.json muse_eeg_*.csv);;All files (*)"


def _fmt_time(sec):
    m, s = divmod(max(0.0, sec), 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m}:{s:04.1f}"


def ask_open_path(parent):
    path, _ = QtWidgets.QFileDialog.getOpenFileName(parent, "Open recording", str(data_root()), FILE_FILTER)
    return path or None


def open_review(path, settings, profiles, parent=None, choose_profile=None, show=True):
    """Locate → identify the device (asking when unsure) → load with a progress dialog → ReviewWindow.
    Returns the window, or None if the user cancelled or the recording cannot be opened."""
    try:
        files = locate(path)
        info = inspect(files, profiles)
    except ReaderError as e:
        QtWidgets.QMessageBox.warning(parent, "Cannot open recording", str(e)); return None
    profile = info.profile
    if info.certainty != "certain":
        options = info.candidates or list(profiles)
        choice = (choose_profile or _ask_profile)(parent, info, options)
        if choice is None: return None
        profile = None if choice == GENERIC else choice
    dlg = QtWidgets.QProgressDialog(f"Loading {files.folder.name}…", "Cancel", 0, 1000, parent)
    dlg.setWindowModality(QtCore.Qt.WindowModal); dlg.setMinimumDuration(400); dlg.setAutoClose(True)

    def progress(frac):
        dlg.setValue(int(frac * 1000)); QtWidgets.QApplication.processEvents()
        return not dlg.wasCanceled()
    try:
        sess = load(info, profile=profile, progress=progress)
        w = ReviewWindow(sess, settings, profile=profile)
    except ReadCancelled:
        return None
    except (ReaderError, ValueError) as e:
        QtWidgets.QMessageBox.warning(parent, "Cannot open recording", str(e)); return None
    finally:
        dlg.reset(); dlg.deleteLater()
    if show: w.show()
    return w


def _ask_profile(parent, info, options):
    why = ("its channels match several device types" if info.certainty == "ambiguous"
           else "its channels match no installed device type")
    items = [p.name for p in options] + [GENERIC]
    item, ok = QtWidgets.QInputDialog.getItem(
        parent, "Which device recorded this?",
        f"{info.files.folder.name}/{info.files.eeg.name} has no session.json and {why}.\n"
        "Choose the device it was recorded with:", items, 0, False)
    if not ok: return None
    return next((p for p in options if p.name == item), GENERIC)


class ReviewWindow(QtWidgets.QMainWindow):
    _open = set()                       # keeps review windows alive independently of the live window

    def __init__(self, session, settings, profile=None):
        super().__init__()
        self.session = session
        spec = session.spec or generic_spec(session.names, session.rates)
        self.store = ReviewStore(spec, session.streams, session.events)
        self.ctx = ViewContext(spec=spec, store=self.store, settings=settings,
                               plots=PlotRegistry(float(settings.value("window_sec", C.WINDOW_SEC))), profile=profile)
        self.markers = EventMarkers(self.ctx)
        files = session.info.files
        self.setWindowTitle(f"{C.APP_NAME} — Review: {files.folder.name if files.meta else files.eeg.stem}"
                            + ("  (sampling rates estimated)" if session.fs_estimated else ""))
        self.resize(1240, 860)
        self._build_ui()
        for t, label in self.store.events: self.markers.add(t, label)
        self.apply_theme(settings.value("theme", DEFAULT_THEME))
        self._pending = QtCore.QTimer(self); self._pending.setSingleShot(True); self._pending.setInterval(15)
        self._pending.timeout.connect(self.refresh)
        self._update_scroll_range()
        self.go_to(min(self.ctx.window_sec, self.store.duration))
        ReviewWindow._open.add(self)

    # ---- UI ------------------------------------------------------------------------------------------
    def _build_ui(self):
        st, info = self.store, self.session.info
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.t0))
        device = info.device_name or (self.ctx.profile.name if self.ctx.profile else "unknown device")
        note = (f"Review • recorded {started} • {device} • {_fmt_time(st.duration)} long • "
                + " · ".join(f"{k.upper()} {getattr(self.ctx.spec, a).fs} Hz"
                             for k, a in (("eeg", "eeg"), ("optics", "optics"), ("imu", "imu"))
                             if getattr(self.ctx.spec, a).n)
                + ("  • " + "  ".join(self.session.warnings) if self.session.warnings else ""))
        self.page = RecordingPage(self.ctx)
        self.page.set_review_mode(note)
        self.page.set_status("")
        self.page.ev_label.setText(f"Events: {len(st.events)} in this recording  ·  click one in the list to jump to it")
        self.page.range_spin.valueChanged.connect(lambda _: (self._update_scroll_range(), self.schedule()))
        self.page.filtered.toggled.connect(lambda _: self.schedule())
        self.page.notch.toggled.connect(lambda _: self.schedule())
        self.page.tabs.currentChanged.connect(lambda _: self.schedule())

        self.scroll = QtWidgets.QScrollBar(QtCore.Qt.Horizontal)
        self.scroll.valueChanged.connect(self._scrolled)
        self.pos_label = QtWidgets.QLabel()
        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(self.scroll, 1); bottom.addSpacing(8); bottom.addWidget(self.pos_label)
        central = QtWidgets.QWidget(); lay = QtWidgets.QVBoxLayout(central); lay.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(self.page, 1); lay.addLayout(bottom)
        self.setCentralWidget(central)

        self.ev_list = QtWidgets.QListWidget()
        for t, label in st.events:
            it = QtWidgets.QListWidgetItem(f"{_fmt_time(t - st.t0)}   {label}")
            it.setData(QtCore.Qt.UserRole, t - st.t0); self.ev_list.addItem(it)
        if not st.events: self.ev_list.addItem("(no events)")
        self.ev_list.itemActivated.connect(self._jump_to_item); self.ev_list.itemClicked.connect(self._jump_to_item)
        dock = QtWidgets.QDockWidget("Events", self); dock.setObjectName("events")
        dock.setWidget(self.ev_list); dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

        menu = self.menuBar().addMenu("File")
        for text, key, slot in (("New session", QtGui.QKeySequence.New, self.new_session),
                                ("Open session…", QtGui.QKeySequence.Open, self.open_another),
                                (None, None, None),
                                ("Close window", QtGui.QKeySequence.Close, self.close)):
            if text is None: menu.addSeparator(); continue
            act = menu.addAction(text); act.setShortcut(key); act.triggered.connect(slot)

    # ---- cursor ----------------------------------------------------------------------------------------
    def _update_scroll_range(self):
        T, dur = self.ctx.window_sec, self.store.duration
        self.scroll.blockSignals(True)
        self.scroll.setRange(0, max(0, int(round((dur - T) / SCROLL_UNIT))))
        self.scroll.setPageStep(max(1, int(round(T / SCROLL_UNIT))))
        self.scroll.setSingleStep(max(1, int(round(T / 10 / SCROLL_UNIT))))
        self.scroll.blockSignals(False)

    def view_start(self):
        return self.scroll.value() * SCROLL_UNIT

    def go_to(self, view_end):
        """Show the window ending at ``view_end`` seconds (clamped to the session)."""
        start = min(max(0.0, view_end - self.ctx.window_sec), self.scroll.maximum() * SCROLL_UNIT)
        if self.scroll.value() == int(round(start / SCROLL_UNIT)): self.schedule()
        else: self.scroll.setValue(int(round(start / SCROLL_UNIT)))

    def center_on(self, t):
        self.go_to(t + self.ctx.window_sec / 2)

    def _jump_to_item(self, item):
        t = item.data(QtCore.Qt.UserRole)
        if t is not None: self.center_on(float(t))

    def _scrolled(self, _):
        self.schedule()

    def schedule(self):
        self._pending.start()

    def refresh(self):
        """Redraw everything for the current scroll position (called through a short single-shot timer)."""
        T = self.ctx.window_sec
        x_end = self.view_start() + T                      # right edge of the plots (may pass the session end)
        end = self.store.set_view_end(x_end)
        self.ctx.plots.set_x_end(x_end)
        self.markers.place()
        fs = self.ctx.spec.eeg.fs
        need = C.QUALITY_SEC * fs
        self.page.set_quality(contact_quality(self.store.eeg.get(need), fs) if self.store.eeg.n >= need else None)
        for tab in self.page.tab_list:                       # rate limits meant for live updates: off when scrolling
            if hasattr(tab, "tiles_t"): tab.tiles_t = 0.0
            if hasattr(tab, "auto_t"): tab.auto_t = 0.0
        self.page.on_frame(); self.page.on_analysis(); self.page.update_texts()
        self.pos_label.setText(f"{_fmt_time(max(0.0, end - T))} – {_fmt_time(end)} / {_fmt_time(self.store.duration)}")

    # ---- theme / menu ------------------------------------------------------------------------------------
    def apply_theme(self, name):
        th = self.ctx.th = THEMES.get(name, THEMES[DEFAULT_THEME])
        apply_app_theme(th)                                  # same theme as the live window (from settings)
        self.ctx.plots.apply_theme(th); self.page.apply_theme(th); self.markers.apply_theme()

    @classmethod
    def apply_theme_all(cls, name):
        for w in list(cls._open): w.apply_theme(name); w.schedule()

    def new_session(self):
        """From a review window: close it and bring the live window to the front."""
        live = next((w for w in QtWidgets.QApplication.topLevelWidgets()
                     if w.isVisible() and type(w).__name__ == "MainWindow"), None)
        if live is not None: live.raise_(); live.activateWindow()
        self.close()

    def open_another(self):
        path = ask_open_path(self)
        if path: open_review(path, self.ctx.settings, discover_profiles(), parent=self)

    def closeEvent(self, event):
        ReviewWindow._open.discard(self)
        self.deleteLater()
        event.accept()
