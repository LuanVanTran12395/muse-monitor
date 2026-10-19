from PySide6 import QtCore, QtWidgets


class ExtensionStatus(QtWidgets.QLabel):
    """Status-bar slot for extension messages (app.show_status), apart from the app's own messages.

    One message at a time: a newer message (from any extension) replaces the current one. Every message clears
    itself: ``ms`` is capped at MAX_MS, and 0 / negative (Qt's "until replaced") means MAX_MS, so an extension
    cannot pin a line in the status bar. Unusable ``ms`` (None, text, NaN) falls back to DEFAULT_MS."""
    DEFAULT_MS = 5000
    MAX_MS = 15000
    MAX_CHARS = 90

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(QtCore.Qt.PlainText)          # an extension's "<b>" is shown as text, never as markup
        self.owner = None                                # id of the extension whose message is shown
        self._timer = QtCore.QTimer(self); self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear_message)

    @classmethod
    def duration(cls, ms):
        try:
            ms = float(ms)
        except (TypeError, ValueError):
            return cls.DEFAULT_MS
        if ms != ms: return cls.DEFAULT_MS               # NaN
        return cls.MAX_MS if ms <= 0 else int(min(ms, cls.MAX_MS))

    def show_message(self, ext_id, message, ms=DEFAULT_MS):
        message = " · ".join(part.strip() for part in str("" if message is None else message).splitlines()
                             if part.strip())
        if not message:                                  # show_status("") clears that extension's message
            self.clear_owner(ext_id); return
        text = f"🧩 {ext_id}: {message}"
        self.owner = ext_id
        self.setToolTip(text if len(text) > self.MAX_CHARS else "")
        self.setText(text if len(text) <= self.MAX_CHARS else text[:self.MAX_CHARS - 1] + "…")
        self._timer.start(self.duration(ms))

    def clear_owner(self, ext_id):
        """Remove the message if it belongs to ``ext_id`` (extension unloaded, reloaded or failed)."""
        if self.owner == ext_id: self.clear_message()

    def clear_message(self):
        self._timer.stop()
        self.owner = None
        self.setText(""); self.setToolTip("")
