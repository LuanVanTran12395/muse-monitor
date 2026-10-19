import time

from PySide6 import QtWidgets


class EventDialog(QtWidgets.QDialog):
    """Event label prompt: Return/Done = save, Esc/close = cancel."""
    def __init__(self, parent, t_wall, last=""):
        """last: previous label, pre-filled and selected → Return repeats it, typing replaces it."""
        super().__init__(parent)
        stamp = time.strftime("%H:%M:%S", time.localtime(t_wall)) + f".{int((t_wall % 1) * 1000):03d}"
        self.setWindowTitle("Mark event")
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(QtWidgets.QLabel(f"Event at <b>{stamp}</b> — enter a label:"))
        self.edit = QtWidgets.QLineEdit(); self.edit.setPlaceholderText("e.g. eyes closed, blink, stimulus A")
        self.edit.setMinimumWidth(320)
        v.addWidget(self.edit)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        self.done_btn = bb.addButton("Done", QtWidgets.QDialogButtonBox.AcceptRole)
        self.done_btn.setEnabled(False)
        # QDialogButtonBox makes Cancel the default when shown → turn them all off; Return is handled by the line edit
        for b in bb.buttons(): b.setAutoDefault(False); b.setDefault(False)
        self.edit.textChanged.connect(lambda t: self.done_btn.setEnabled(bool(t.strip())))
        self.edit.returnPressed.connect(lambda: self.label() and self.accept())
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if last:
            self.edit.setText(last); self.edit.selectAll()
        v.addWidget(QtWidgets.QLabel("<small>Return = save · Esc = cancel · in the main window, keys 1–9 mark an "
                                     "event at once without this prompt</small>"))

    def label(self):
        return self.edit.text().strip()


def ask_event_label(parent, t_wall, last=""):
    """Open the dialog; return the label or None if cancelled. exec() returns an int (1 = Accepted)."""
    dlg = EventDialog(parent, t_wall, last)
    return dlg.label() if dlg.exec() and dlg.label() else None
