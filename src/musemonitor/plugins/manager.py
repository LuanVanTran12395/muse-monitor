"""Extension lifecycle: load, activate, dispatch hooks, isolate errors."""
import sys
import traceback
from dataclasses import dataclass

from .api import API_VERSION, Extension, ExtensionContext
from .loader import discover

HOOKS = ("on_eeg", "on_optics", "on_imu", "on_event", "on_recording_started", "on_recording_stopped",
         "on_connected", "on_disconnected", "on_theme_changed")
DISABLED_KEY = "extensions/disabled"


@dataclass
class ExtensionRecord:
    id: str
    source: str
    cls: type = None
    instance: Extension = None
    status: str = "loaded"      # active | disabled | unloaded | error | incompatible | not applicable
    error: str = None

    @property
    def name(self):
        return (self.cls and self.cls.name) or self.id

    @property
    def version(self):
        return self.cls.version if self.cls else ""

    @property
    def description(self):
        return self.cls.description if self.cls else ""


class ExtensionManager:
    def __init__(self, host, settings, dirs=None, use_entry_points=True):
        self.host = host
        self.settings = settings
        self.dirs = dirs; self.use_entry_points = use_entry_points
        self.records = []
        self._subs = {h: [] for h in HOOKS}       # hook → records that override it

    # ---- enable/disable (takes effect on next start-up) ------------------------------
    def disabled_ids(self):
        v = self.settings.value(DISABLED_KEY, [])
        return set([v] if isinstance(v, str) else (v or []))

    def set_enabled(self, ext_id, enabled):
        ids = self.disabled_ids()
        ids.discard(ext_id) if enabled else ids.add(ext_id)
        self.settings.setValue(DISABLED_KEY, sorted(ids))

    # ---- loading ------------------------------------------------------------------
    def load_all(self):
        disabled = self.disabled_ids()
        for d in discover(self.dirs, self.use_entry_points):
            self._register(d, disabled)
        for rec in self.records:
            if rec.status == "error": self._log(rec)
        return self.records

    def refresh(self):
        """Find extensions ADDED while the app is running and activate them at once (no restart needed).

        - Already-loaded extensions are kept and not re-imported (editing their code still needs a restart).
        - Extensions that previously failed to import are retried (fix the file, then press Update).
        - New extensions "catch up" with the app state: current theme, streaming, recording.
        Returns the list of new/retried records."""
        loaded = {r.source for r in self.records if r.cls is not None}
        disabled, changed = self.disabled_ids(), []
        for d in discover(self.dirs, self.use_entry_points, skip=loaded):
            old = next((r for r in self.records if r.source == d.source), None)
            if old is not None: self.records.remove(old)            # previous import error → retry
            rec = self._register(d, disabled)
            if rec.status == "active": self._catch_up(rec)
            elif rec.status == "error": self._log(rec)
            changed.append(rec)
        return changed

    def _supports(self, rec):
        """Ask whether the extension fits the current device; if not → status "not applicable"."""
        spec = getattr(self.host, "spec", None)
        try:
            ok = spec is None or bool(rec.cls.supports(spec))
        except Exception:
            ok = True                                    # supports() raised → try running anyway (errors are isolated)
        if not ok:
            rec.status = "not applicable"
            rec.error = "Not applicable to the connected device (channels / sensors it needs are missing)."
        return ok

    @staticmethod
    def summarize(changed):
        """One-line summary of refresh() results for the UI."""
        if not changed: return "No new extensions found."
        parts = []
        for status, word in (("active", "loaded"), ("error", "failed"), ("disabled", "disabled"),
                             ("incompatible", "incompatible"), ("not applicable", "not applicable")):
            names = [r.name for r in changed if r.status == status]
            if names: parts.append(f"{word}: {', '.join(names)}")
        return f"{len(changed)} new extension(s) — " + "; ".join(parts)

    def _register(self, d, disabled):
        rec = ExtensionRecord(d.id, d.source, d.cls, error=d.error)
        self.records.append(rec)
        if d.error:
            rec.status = "error"; return rec
        if any(r is not rec and r.id == d.id and r.cls is not None for r in self.records):
            rec.status, rec.error = "error", f"duplicate extension id '{d.id}' — skipped"; return rec
        if d.cls.requires_api > API_VERSION:
            rec.status = "incompatible"
            rec.error = f"requires API {d.cls.requires_api}, app provides {API_VERSION}"; return rec
        if not self._supports(rec):
            return rec
        if d.id in disabled:
            rec.status = "disabled"; return rec
        self._activate(rec)
        return rec

    def _catch_up(self, rec):
        """Extension loaded at runtime: replay to it alone the state hooks that already happened."""
        host, inst = self.host, rec.instance
        steps = []
        ctx = getattr(host, "ctx", None)
        if ctx is not None: steps.append(("on_theme_changed", (ctx.th,)))
        if getattr(host, "streaming", False): steps.append(("on_connected", (getattr(host, "device_name", ""),)))
        if getattr(host, "recording", False) and getattr(host, "rec_path", None):
            steps.append(("on_recording_started", (host.rec_path,)))
        for hook, args in steps:
            if rec.status != "active": break
            if getattr(type(inst), hook) is getattr(Extension, hook): continue
            try: getattr(inst, hook)(*args)
            except BaseException as e: self.fail(rec.id, e, where=hook)

    def _activate(self, rec):
        try:
            inst = rec.cls()
            inst.app = ExtensionContext(rec.id, self.host, self)
            rec.instance = inst
            inst.activate(inst.app)
        except BaseException:
            rec.status, rec.error = "error", traceback.format_exc()
            self._teardown(rec); return
        rec.status = "active"
        for h in HOOKS:                      # only register overridden hooks → no wasted CPU
            if getattr(type(rec.instance), h) is not getattr(Extension, h): self._subs[h].append(rec)

    def active(self):
        return [r for r in self.records if r.status == "active"]

    # ---- hook dispatch --------------------------------------------------------------
    def dispatch(self, hook, *args):
        for rec in list(self._subs[hook]):
            try:
                getattr(rec.instance, hook)(*args)
            except BaseException as e:
                self.fail(rec.id, e, where=hook)

    def guard(self, ext_id, where, fn, *args):
        """Call an extension's fn; on error → disable only that extension."""
        try:
            return fn(*args)
        except BaseException as e:
            self.fail(ext_id, e, where=where)

    def fail(self, ext_id, exc, where=""):
        rec = next((r for r in self.records if r.id == ext_id), None)
        if rec is None or rec.status != "active": return
        rec.status = "error"
        rec.error = f"in {where}:\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._teardown(rec)
        self._log(rec)
        if hasattr(self.host, "on_extension_failed"): self.host.on_extension_failed(rec)

    def _teardown(self, rec):
        for subs in self._subs.values():
            if rec in subs: subs.remove(rec)
        if rec.instance is not None:
            try: rec.instance.deactivate()
            except BaseException: pass

    def unload(self, ext_id):
        """Unload a running extension mid-session: stop hooks, call deactivate, remove tabs + menu items.
        Current session only — the next start-up loads it again (untick Enabled to turn it off for good)."""
        rec = next((r for r in self.records if r.id == ext_id and r.status == "active"), None)
        if rec is None: return False
        self._teardown(rec)
        try: rec.instance.app._dispose()
        except BaseException: pass
        rec.instance, rec.status = None, "unloaded"
        return True

    def load(self, ext_id):
        """Re-activate an unloaded/disabled extension mid-session (does not change the Enabled setting)."""
        rec = next((r for r in self.records if r.id == ext_id and r.cls is not None
                    and r.status in ("unloaded", "disabled")), None)
        if rec is None: return None
        rec.error = None
        if not self._supports(rec): return rec.status
        self._activate(rec)
        if rec.status == "active": self._catch_up(rec)
        return rec.status

    def shutdown(self):
        for rec in self.active():
            self._teardown(rec); rec.status = "loaded"

    @staticmethod
    def _log(rec):
        print(f"[musemonitor] extension '{rec.id}' ({rec.source}) failed:\n{rec.error}", file=sys.stderr)
