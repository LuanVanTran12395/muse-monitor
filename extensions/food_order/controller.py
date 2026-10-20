"""Glue for the kiosk: quick calibration → sign-in → ordering, with gestures from the reused estimators and a
keyboard / mouse fallback for every action.

Calibration (under a minute, rules of the two extensions — see gestures.py):
    1 look straight, head still, eyes open   5 s   → eye_interaction "open"  + head_motion_plus "neutral" (last 1 s)
    2 turn LEFT and hold                     1.5 s → head_motion_plus "left"
    3 look UP and hold                       1.5 s → head_motion_plus "up"   (→ IMU axes)
    4 blink twice quickly, three times       6 s   → eye_interaction "blink" (+ this user's double-blink spacing)
    5 eyes closed until the end tone         7 s   → closing deflection, quiet level, alpha (quick cart)
    (step 4 with an eye shortcut on, step 5 with the quick cart on; both read the chosen eye source, TP by default)
    then: look straight and hold still → recenter
A failed step is repeated once, then skipped (head: default axes; eyes: that shortcut stays off).
"""
import time

import numpy as np
from PySide6 import QtCore

from musemonitor.storage.session import data_root

from . import menu
from .demo import CameraLink, DemoRecorder, facing_caption
from .kiosk import KioskWindow
from .order import Order
from .text import t

CALIB = [  # key, seconds (titles and instructions: text.py "c.<key>", "c.<key>_t")
    ("open", 5.0), ("left", 1.5), ("up", 1.5), ("blink", 6.0),
    ("closed", 7.0),   # long enough to see the closing deflection, then several seconds of a quiet, closed-eye signal
]
PREP_S, RESULT_S = 2.0, 1.0
CHIP_ICON = dict(point="↔", nod="↕", dwell="●", blink="◉◉", page="⟲", up="↑", up_lang="↑", shake="✕", cart="◡", key="⌨")
CALIB_MSG_EN = {  # gestures.py reports in Vietnamese
    "Dữ liệu IMU không hợp lệ.": "Invalid IMU data.", "Đầu bị động — giữ yên rồi làm lại.": "The head moved — hold still and repeat.",
    "Cần bước giữ yên trước.": "Do the hold-still step first.",
    "Cử động quá nhỏ hoặc đã quay về giữa sớm — làm lại.": "Too small, or back to the centre too early — repeat.",
    "Chưa thấy rõ các cái nháy — làm lại.": "The blinks were not clear — repeat.", "Cần bước nháy trước.": "Do the blink step first.",
    "Thiếu dữ liệu.": "Not enough data.", "Chưa thấy lúc nhắm mắt — nhắm hẳn khi nghe bíp.": "No eye closure seen — close your eyes fully at the beep.",
}
# BCI rule: the reliable channel (head, IMU) carries every consequential command; the eye channels are shortcuts
# whose mistakes are harmless (they only show something, which closes by itself). Replaying the 2026-10-19
# captures through gestures.EyeCommands: from TP9 / TP10 (default) double blink 5 / 9 at 0.33 false / min, eye
# closure 4 / 4 at 0.07 false / min; from AF7 / AF8 3 / 9 at 0.60 and 1 / 4 at 2.40. Dwell (off) selects whenever
# someone lingers to read.
OPTION_DEFAULTS = dict(dwell_select=False, eye_details=True, eye_cart=True)


class Controller:
    def __init__(self, ext):
        self.ext = ext
        self.window = None
        self.order = Order(recent=self._recent(), lang=self._lang_setting())
        self.head = self.eyes = None
        self.reuse_error = ""
        try:
            from . import _reuse
            from .gestures import EyeCommands, HeadGestures
            self.head_mod, self.eye_mod = _reuse.head(), _reuse.eyes()
            self.head = HeadGestures(self.head_mod, ext.imu_fs)
            self.eyes = EyeCommands(self.eye_mod, ext.fs, ext.channels, source=self.eye_source())
        except Exception as e:                          # missing / changed extension: keyboard and mouse still work
            self.reuse_error = f"{type(e).__name__}: {e}"
        # camera (head_motion_plus's module, reused read-only): auto-recenter + the demo layout; demo video recorder
        self.camera, self.gate, self.cam_res, self.camera_why = None, None, None, "gestures unavailable"
        if self.head is not None:
            cam_mod = getattr(self.head_mod, "camera", None)
            ok, why = cam_mod.availability() if cam_mod is not None else (False, "head_motion_plus has no camera module")
            self.camera_why = why
            if ok:
                self.camera = CameraLink(cam_mod)
                self.camera.result.connect(self._cam_result)
                self.camera.frame.connect(self._cam_frame)
                self.camera.error.connect(self._cam_error)
                self.camera.running_changed.connect(self._cam_running)
                self.gate = cam_mod.FacingGate()
        self.recorder = DemoRecorder()
        self.last_video = None
        self.calib = None                               # dict(i, phase, until, attempt, imu, raw, filt, message)
        self.received = None                            # (text, until)
        self.blink_flash = -1e9                         # last blink seen (eye feedback)
        self.last_imu = None                            # monotonic time of the last IMU chunk (head signal state)
        self.timer = QtCore.QTimer(); self.timer.setInterval(40); self.timer.timeout.connect(self._tick)

    # ---- settings -------------------------------------------------------------------------------------------------
    def _recent(self):
        raw = str(self.ext.app.setting("recent_accounts", "") or "")
        return [c for c in raw.split(",") if c][:5]

    # ---- language: per customer (each account remembers its own), switchable at any time -------------------------
    def _lang_setting(self):
        lang = str(self.ext.app.setting("language", "vi") or "vi")
        return lang if lang in ("vi", "en") else "vi"

    def _account_langs(self):
        import json
        try: return json.loads(str(self.ext.app.setting("account_langs", "{}") or "{}"))
        except ValueError: return {}

    def set_lang(self, lang):
        """Change the kiosk language; it is remembered for the signed-in customer (and as the default)."""
        if lang not in ("vi", "en"): return False
        changed = self.order.set_lang(lang)
        self.ext.app.set_setting("language", lang)
        self._remember_lang()
        if not changed: return False
        if self.window is not None: self.window.edit.setPlaceholderText(self.tr("login.placeholder"))
        self._render(); return True

    def _remember_lang(self):
        import json
        if not self.order.user: return
        langs = self._account_langs(); langs[self.order.user] = self.order.lang
        self.ext.app.set_setting("account_langs", json.dumps(langs))

    def toggle_lang(self):
        return self.set_lang("en" if self.order.lang == "vi" else "vi")

    def tr(self, key, **kw):
        return t(key, self.order.lang, **kw)

    def head_live(self, now=None):
        """Head gestures usable: the estimator exists AND IMU data arrived within the last second (EEG alone does
        not count — the IMU can stop while EEG goes on)."""
        now = self.ext.mono() if now is None else now
        return self.head is not None and self.last_imu is not None and now - self.last_imu < 1.0

    def eye_source(self):
        src = str(self.ext.app.setting("eye_source", "tp"))
        return src if src in ("tp", "af", "diff") else "tp"

    def set_eye_source(self, source):
        """A new source needs its own eye calibration: the estimator starts afresh (blink / closure off until then)."""
        self.ext.app.set_setting("eye_source", source)
        if self.eyes is None or self.eyes.source == source: return
        from .gestures import EyeCommands
        self.eyes = EyeCommands(self.eye_mod, self.ext.fs, self.ext.channels, source=self.eye_source())
        self._render()

    def opt(self, key, default=None):
        default = OPTION_DEFAULTS.get(key, False) if default is None else default
        return str(self.ext.app.setting(key, default)).lower() in ("true", "1")

    # ---- window ---------------------------------------------------------------------------------------------------
    def open(self, calibrate=True):
        if self.window is None:
            self.window = KioskWindow(self._key, self._closed, self._login, self._click)
            avatars = []
            if self.head is not None:
                hc = self.head_mod.HeadCanvas(self.head.tracker); avatars.append(hc)
            if self.eyes is not None:
                ec = self.eye_mod.EyeCanvas(self.eyes); avatars.append(ec)
            self.window.set_avatars(avatars)
            self.window.edit.setPlaceholderText(self.tr("login.placeholder"))
            self.avatar_widgets = avatars
        self.window.show(); self.window.raise_(); self.window.activateWindow()
        n = sum(l.qty for l in self.order.cart)
        if n and self.order.user: self.order._toast(self.tr("toast.kept", n=n), self.ext.mono())
        if calibrate and self.head is not None and not self.head.calibrated: self.start_calibration()
        self.timer.start(); self._render()
        return self.window

    def close(self):
        self.record_stop()
        if self.camera is not None: self.camera.stop()
        self.timer.stop()
        if self.window is not None:
            self.window.on_closed = lambda: None; self.window.close(); self.window = None

    def _closed(self):
        """Closing the window never destroys the order: the cart stays for this app session (sign out empties it),
        and the next opening says so. No dialog — a head-only user could not answer a desktop dialog."""
        self.record_stop()
        self.window = None; self.timer.stop(); self.calib = None

    # ---- camera: auto-recenter (head_motion_plus rules) and the demo layout ------------------------------------
    def camera_start(self, device_id=None):
        """After the caller's consent dialog. Returns (ok, message)."""
        if self.camera is None: return False, self.camera_why
        self.gate.reset(); self.cam_res = None
        self.camera.start(device_id)
        return True, "Đang bật camera… macOS có thể hỏi quyền."

    def camera_stop(self):
        if self.camera is not None: self.camera.stop()
        if self.window is not None: self.window.set_camera(None)

    def _cam_running(self, on):
        if not on and self.window is not None: self.window.set_camera(None)

    def _cam_result(self, res):
        """FacingGate: facing the screen AND the head still for 1 s (at most every 5 s) → recenter the pointer."""
        self.cam_res = res
        if self.head is None or self.calib: return
        now = self.ext.mono()
        if self.gate.update(res.get("facing", False), self.head.tracker.is_still(), time.monotonic()) and self.head.recenter():
            self.order._toast(self.tr("toast.recenter"), now)
            for wdg in getattr(self, "avatar_widgets", []):
                if hasattr(wdg, "mark_recentered"): wdg.mark_recentered("camera")
            self._after(self.order, now, self.tr("log.camera"))

    def _cam_frame(self, img):
        if self.window is not None: self.window.set_camera(img, facing_caption(self.cam_res, self.order.lang))

    def _cam_error(self, message):
        if self.window is not None: self.window.set_camera(None)
        self.ext.app.show_status(message, 10000)

    # ---- demo video -------------------------------------------------------------------------------------------
    def record_start(self):
        """Write the kiosk window (camera, head, eyes and the UI) to data/food_order/demo/<time>.mp4."""
        if self.recorder.active: return False, "Đang ghi."
        win = self.open(calibrate=False)
        folder = data_root() / "food_order" / "demo"; folder.mkdir(parents=True, exist_ok=True)
        path = folder / time.strftime("muse_bistro_%Y%m%d_%H%M%S.mp4")
        if not self.recorder.start(win, path):
            return False, "Không ghi được video (OpenCV / codec)."
        self.last_video = path
        return True, f"Đang ghi video demo → {path.name}"

    def record_stop(self):
        if not self.recorder.active: return None
        path = self.recorder.stop()
        if self.window is not None:
            self.window.recording = None
            self.order._toast(self.tr("toast.video_saved", name=path.name), self.ext.mono())
            self._render()
        return path

    def record_toggle(self):
        """F9 or a click on the ● REC label in the kiosk (the kiosk is often full screen: the tab is out of reach)."""
        if self.recorder.active: return self.record_stop()
        ok, msg = self.record_start()
        if ok: self.order._toast(self.tr("toast.video_started"), self.ext.mono()); self._render()
        else: self.ext.app.show_status(msg, 8000)
        return ok

    # ---- calibration ----------------------------------------------------------------------------------------------
    def steps(self):
        eyes = self.opt("eye_details") or self.opt("eye_cart")
        return [(k, self.tr(f"c.{k}"), self.tr(f"c.{k}_t"), secs) for k, secs in CALIB
                if (k not in ("blink", "closed") or eyes) and (k != "closed" or self.opt("eye_cart"))]

    def start_calibration(self):
        if self.head is None: return False
        self.calib = dict(i=0, attempt=1, phase="prep", until=self.ext.mono() + PREP_S, message="")
        self._render(); return True

    def _calib_tick(self, now):
        c = self.calib
        steps = self.steps()
        if c["i"] >= len(steps):                         # final: hold still → recenter
            if self.head.recenter() or now > c.get("give_up", now + 1):
                self.calib = None; self._beep("done"); self._render(); return
            c.setdefault("give_up", now + 4.0); return
        key, _, _, secs = steps[c["i"]]
        if now < c["until"]: return
        if c["phase"] == "prep":
            c.update(phase="go", until=now + secs, imu=[], raw=[], filt=[]); self._beep("go")
        elif c["phase"] == "go":
            ok, msg = self._finish(key, c)
            if self.order.lang == "en": msg = CALIB_MSG_EN.get(msg, msg)
            self._beep("done" if ok else "retry")
            c.update(phase="ok" if ok else "fail", until=now + RESULT_S, message=msg, ok=ok)
        else:
            if c["ok"] or c["attempt"] >= 2:
                c.update(i=c["i"] + 1, attempt=1)
            else:
                c["attempt"] += 1
            c.update(phase="prep", until=now + PREP_S, message="" if c.get("ok") else c["message"])

    def _finish(self, key, c):
        imu = np.concatenate(c["imu"], axis=1).T if c["imu"] else np.empty((0, 6))
        raw = np.concatenate(c["raw"], axis=1) if c["raw"] else np.empty((len(self.ext.channels), 0))
        filt = np.concatenate(c["filt"], axis=1) if c["filt"] else np.empty((2, 0))
        fs = int(self.ext.fs)
        if key == "open":
            ok_e, msg_e = self.eyes.calibrate_open(raw[:, fs:], filt[:, fs:]) if raw.shape[1] > 2 * fs else (False, self.tr("c.no_eeg"))
            n = int(self.head.fs)
            ok_h, msg_h = self.head.calibrate("neutral", imu[-n:]) if len(imu) >= n // 2 else (False, self.tr("c.no_imu"))
            return ok_e and ok_h, msg_h or msg_e
        if key in ("left", "up"): return self.head.calibrate(key, imu)
        if key == "blink": return self.eyes.calibrate_blink(filt)
        return self.eyes.calibrate_closed(raw, filt)

    # ---- streams --------------------------------------------------------------------------------------------------
    def on_imu(self, x, ts_raw):
        if self.head is None: return
        now = self.ext.mono()
        self.last_imu = now
        x = np.asarray(x, dtype=float)
        if self.eyes is not None: self.eyes.note_motion(x)
        if self.calib and self.calib["phase"] == "go": self.calib["imu"].append(x[:6].copy())
        events = self.head.feed(x, float(ts_raw[-1]) if len(ts_raw) else float("nan"), now)
        if self.calib or self.window is None: return
        for e in events: self._event(e, now)

    def on_eeg(self, x, ts_raw):
        if self.eyes is None: return
        now = self.ext.mono()
        capturing = bool(self.calib and self.calib["phase"] == "go")
        filtered, events = self.eyes.feed(np.asarray(x, dtype=float), now, detect=not self.calib)
        if capturing:
            self.calib["raw"].append(np.asarray(x, dtype=float).copy()); self.calib["filt"].append(filtered.copy())
        if self.calib or self.window is None: return
        for e in events: self._event(e, now)

    # ---- commands -------------------------------------------------------------------------------------------------
    def _event(self, e, now):
        o, kind = self.order, e[0]
        if kind == "point": o.point(e[1]); return
        if kind == "look_up" and o.screen == "login":                 # nothing else to do there: switch the language
            if self.toggle_lang(): self._after(o, now); self._beep("go")
            return
        if kind == "blink": self.blink_flash = now; return
        if kind == "select" and not self.opt("dwell_select"): return
        if kind == "double_blink" and not self.opt("eye_details"): return
        if kind == "eyes_closed" and not self.opt("eye_cart"): return
        done = {"select": lambda: o.select(now), "double_blink": lambda: o.details(now), "page": lambda: o.page(e[1]),
                "nod": lambda: o.yes(now), "shake": lambda: o.no(now), "look_up": o.categories,
                "eyes_closed": lambda: o.cart_peek(now)}[kind]()
        if done:
            self._after(o, now, self.tr("log.dwell") if kind == "select" else None)
            self._beep({"nod": "done", "eyes_closed": "done", "shake": "retry"}.get(kind, "go"))

    def _after(self, o, now, label=None):
        if o.user: self.ext.app.set_setting("recent_accounts", ",".join(o.recent[:5]))
        text = label or (o.log[-1][0] if o.log else "")
        self.received = (text, now + 1.6)
        self._render()

    def _login(self, code):
        from .capture import to_subject
        now = self.ext.mono()
        code = to_subject(code)
        saved = self._account_langs().get(code)                   # the customer's own language
        if saved in ("vi", "en"): self.order.set_lang(saved)
        if self.order.login(code, now):
            self._remember_lang(); self._after(self.order, now); self._beep("done")

    def _key(self, ev):
        if ev.isAutoRepeat(): return
        Q, o, now, k = QtCore.Qt, self.order, self.ext.mono(), ev.key()
        if self.calib:
            if k == Q.Key_Escape: self.calib = None; self._render()          # skip calibration
            elif k == Q.Key_L: self.toggle_lang()
            return
        acts = {Q.Key_Left: lambda: o.point(o.focus - 1), Q.Key_Right: lambda: o.point(1 + o.focus),
                Q.Key_1: lambda: o.point(0), Q.Key_2: lambda: o.point(1), Q.Key_3: lambda: o.point(2),
                # Enter = the nod: chooses the pointed card, confirms a popup, acts on a sheet (as the dock says)
                Q.Key_Return: lambda: o.yes(now), Q.Key_Enter: lambda: o.yes(now),
                Q.Key_PageDown: lambda: o.page(1), Q.Key_BracketRight: lambda: o.page(1),
                Q.Key_PageUp: lambda: o.page(-1), Q.Key_BracketLeft: lambda: o.page(-1),
                Q.Key_Up: o.categories, Q.Key_Y: lambda: o.yes(now), Q.Key_N: lambda: o.no(now),
                Q.Key_Backspace: lambda: o.no(now), Q.Key_C: o.cart_open,
                Q.Key_D: lambda: o.details(now), Q.Key_V: lambda: o.cart_peek(now),
                Q.Key_R: self._recenter_key,
                Q.Key_K: self.start_calibration, Q.Key_L: self.toggle_lang}
        if k == Q.Key_F9: self.record_toggle(); return
        if k in acts and acts[k]() is not False:
            self._after(o, now, {Q.Key_Left: self.tr("log.key_point"), Q.Key_Right: self.tr("log.key_point"),
                                 Q.Key_R: self.tr("log.recenter")}.get(k))

    def _recenter_key(self):
        if self.head is None or not self.head.recenter(): return False
        for wdg in getattr(self, "avatar_widgets", []):
            if hasattr(wdg, "mark_recentered"): wdg.mark_recentered("manual")
        return True

    def _click(self, action):
        """Mouse: ``action`` is the control drawn under the pointer (KioskWindow.hit_at) — a card, a popup or sheet
        button, a category tab, the cart tab or the language switch. Areas outside a modal layer do nothing."""
        if self.window is None: return
        o, now = self.order, self.ext.mono()
        kind = action[0]
        if kind == "lang": self.set_lang(action[1]); return
        if kind == "rec_stop": self.record_stop(); return
        if self.calib: return
        done = False
        if kind == "popup_yes" and o.popup: done = o.yes(now)
        elif kind == "popup_no" and o.popup: done = o.no(now)
        elif kind == "overlay_yes" and o.overlay and not o.popup: done = o.yes(now)
        elif kind == "overlay_no" and o.overlay and not o.popup: done = o.no(now)
        elif kind == "card" and not o.popup and not o.overlay:
            o.point(action[1]); done = o.select(now)
        elif kind == "cat": done = o.open_category(action[1])
        elif kind == "cart" and not o.overlay: done = o.cart_open()
        if done: self._after(o, now, self.tr("log.click") if kind == "card" else None)

    def _beep(self, tone):
        if self.ext.cues.enabled: self.ext.cues.play(tone)

    # ---- view -----------------------------------------------------------------------------------------------------
    def _tick(self):
        now = self.ext.mono()
        if self.calib: self._calib_tick(now)
        else: self.order.tick(now)
        if self.received and now > self.received[1]: self.received = None
        if self.window is not None: self.window.recording = self.recorder.seconds() if self.recorder.active else None
        for wdg in getattr(self, "avatar_widgets", []):
            if hasattr(wdg, "advance"): wdg.advance()
            wdg.update()
        self._render()

    def _render(self):
        if self.window is None: return
        self.window.set_view(self.view())

    def view(self):
        now = self.ext.mono()
        if self.calib:
            c, steps = self.calib, self.steps()
            if c["i"] >= len(steps):
                return dict(mode="calib", lang=self.order.lang, k=len(steps), n=len(steps), title=self.tr("calib.final_title"),
                            text=self.tr("calib.final_text"), big="…", phase="prep", fraction=0.0,
                            mode_label=self.tr("mode.calib"), chips=[("Esc", self.tr("chip.skip")), ("L", "VI | EN")])
            key, title, text, secs = steps[c["i"]]
            left = max(0.0, c["until"] - now)
            big = {"prep": f"{left:.0f}" if left >= 0.5 else "1", "go": "GO", "ok": "✓", "fail": "✕"}[c["phase"]]
            frac = 1 - left / secs if c["phase"] == "go" else (1.0 if c["phase"] in ("ok", "fail") else 0.0)
            return dict(mode="calib", lang=self.order.lang, k=c["i"] + 1, n=len(steps), title=title, text=text, big=big,
                        phase=c["phase"], fraction=frac, message=c.get("message") if c["phase"] in ("fail", "prep") else "",
                        mode_label=self.tr("mode.calib"), chips=[("Esc", self.tr("chip.skip")), ("L", "VI | EN")])
        o = self.order
        tr = self.tr
        item = o.draft.name(o.lang) if o.draft else ""
        heading = {"login": tr("login.heading"), "categories": tr("h.categories"),
                   "size": tr("h.size", item=item), "extras": tr("h.extras", item=item), "qty": tr("h.qty", item=item),
                   "cart": tr("h.cart", total=menu.vnd(o.total())) if o.cart else tr("h.cart_empty"),
                   "row": tr("h.row"), "done": tr("h.done"),
                   "browse": menu.category_name(o.category, o.lang)}.get(o.screen)
        hint = {"browse": tr("hint.browse"), "extras": tr("hint.extras"), "cart": tr("hint.cart") if o.cart else "",
                "done": tr("hint.done"), "qty": tr("hint.qty")}.get(o.screen, "")
        chips = self._chips(o)
        toast = None
        if o.toast:
            toast = dict(text=o.toast["text"])
            if o.toast.get("undo") and now <= o.toast["undo_until"]:
                toast["right"] = tr("toast.undo_hint", s=f"{max(0, o.toast['undo_until'] - now):.0f}")
        popup = None
        if o.popup:
            kind = o.popup["kind"]
            n_items = sum(l.qty for l in o.cart)
            title = {"order": tr("pop.order_one", total=menu.vnd(o.total())) if n_items == 1 else
                     tr("pop.order", n=n_items, total=menu.vnd(o.total())),
                     "delete": tr("pop.delete", item=o.cart[o.popup.get("line", 0)].describe(o.lang)) if o.cart else "?",
                     "logout": tr("pop.logout")}[kind]
            popup = dict(title=title, sub=tr("pop.order_sub") if kind == "order" else "",
                         yes={"order": tr("btn.order"), "delete": tr("btn.delete"), "logout": tr("btn.logout")}[kind],
                         no=tr("btn.cancel"), left=max(0.0, o.popup["until"] - now))
        pointer = None
        dwell = 0.0
        if self.head is not None:
            yaw = self.head.last[0]
            pointer = 0.5 - yaw / (2 * self.head.cfg["page_deg"])
            dwell = self.head.dwell_fraction(now)
        prefill = o.recent[0] if o.recent else ""
        overlay = None
        if o.overlay:
            left = None if o.overlay["until"] is None else max(0.0, o.overlay["until"] - now)
            if o.overlay["kind"] == "details":
                card = o.overlay["card"]
                overlay = dict(kind="details", card=card, lines=o.item_details(card), left=left)
            else:
                overlay = dict(kind="peek", lines=[(l.describe(o.lang), l.qty, menu.vnd(l.total)) for l in o.cart],
                               total=menu.vnd(o.total()), left=left)
        eye = None
        if self.eyes is not None and (self.opt("eye_details") or self.opt("eye_cart")):
            eye = dict(blink=now - self.blink_flash < 0.35, closing=self.eyes.closed_now,
                       closed_s=self.eyes.cfg["closed_s"], since=self._closing_since(now))
        return dict(mode="order", lang=o.lang, screen=o.screen, category=o.category, cards=o.cards(), focus=o.focus,
                    page=(min(o.page_no(), o.n_pages() - 1), o.n_pages()), heading=heading, hint=hint,
                    cart_n=sum(l.qty for l in o.cart), cart_total=menu.vnd(o.total()) if o.cart else "",
                    user=o.user, keyboard_only=not self.head_live(now),
                    mode_label=(tr("mode.keys") + " · " if not self.head_live(now) else "") + tr(f"mode.{o.screen}")
                    + (f" · {menu.category_name(o.category, o.lang)}" if o.screen == "browse" else ""),
                    chips=chips, toast=toast, popup=popup, pointer=pointer, prefill=prefill, signals=self.signals(),
                    overlay=overlay, eye=eye,
                    dwell=dwell if self.opt("dwell_select") else 0.0,
                    received=self.received[0] if self.received else "")

    def _closing_since(self, now):
        e = self.eyes
        if e is None or e.closing is None: return 0.0
        return max(0.0, (e.n - e.closing) / e.fs - e.cfg["settle_s"])

    def _key_chips(self, o):
        """Without head signal (no headset, IMU silent): the keys, on screen — no need to read the README."""
        k = lambda key, text: (key, self.tr(text))
        if o.popup: return [k("Enter", "key.yes"), k("⌫", "key.no")]
        if o.overlay: return [k("Enter", "key.choose"), k("⌫", "key.no")]
        base = [k("← →", "key.point"), k("Enter", "key.choose")]
        if o.screen == "login": return [("⌨", self.tr("chip.key"))] + base + [k("L", "key.lang")]
        if o.screen == "done": return base + [k("⌫", "key.signout")]
        page = [k("PgDn", "key.page")] if o.n_pages() > 1 else []
        extra = [k("D", "key.details")] if o.screen == "browse" else []
        return base + page + [k("↑", "key.cat"), k("⌫", "key.back"), k("C", "key.cart")] + extra + [k("L", "key.lang")]

    def _chips(self, o):
        if not self.head_live(): return self._key_chips(o)
        chip = lambda k: (CHIP_ICON[k], self.tr(f"chip.{k}"))
        if o.popup: return [("↕", self.tr("chip.yes")), ("✕", self.tr("chip.cancel"))]
        if o.overlay:
            return [("↕", self.tr("chip.choose_this") if o.overlay["kind"] == "details" else self.tr("chip.order")),
                    ("✕", self.tr("chip.close"))]
        sel = [chip("point"), chip("nod")] + ([chip("dwell")] if self.opt("dwell_select") else [])
        page = [chip("page")] if o.n_pages() > 1 else []
        eyes = self.eyes is not None
        blink = [chip("blink")] if self.opt("eye_details") and eyes and self.eyes.blink_ready and o.screen == "browse" else []
        cart = [chip("cart")] if self.opt("eye_cart") and eyes and self.eyes.closure_ready else []
        s = o.screen
        if s == "login": return [chip("key")] + sel + [chip("up_lang")]
        if s == "done": return sel + [("✕", self.tr("chip.signout"))]
        return sel + page + ([chip("up")] if s not in ("extras", "qty", "size") else []) + [chip("shake")] + blink + cart

    def signals(self):
        """Signal state per channel, shown in the kiosk (BCI: the user sees what the system can hear)."""
        tr = self.tr
        if self.head is None: return [(tr("sig.head"), "off"), (tr("sig.blink"), "off")]
        q = self.ext.contact() or {}
        used = {"tp": ("TP9", "TP10"), "af": ("AF7", "AF8")}.get(self.eyes.source, ("TP9", "AF7", "AF8", "TP10"))
        front = "ok" if all(q.get(c) == "Good" for c in used) else "weak" if q else "off"
        out = [(tr("sig.head"), "ok" if self.head_live() else "off")]
        if self.opt("eye_details"): out.append((tr("sig.blink"), front if self.eyes.blink_ready else "off"))
        if self.opt("eye_cart"): out.append((tr("sig.closed"), front if self.eyes.closure_ready else "off"))
        return out
