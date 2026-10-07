from PySide6 import QtCore, QtGui, QtWidgets

from ...plugins.loader import default_dir, search_dirs
from ...plugins.scaffold import create_extension

STATUS_TEXT = {"active": "● Active", "disabled": "○ Disabled", "unloaded": "○ Unloaded", "error": "✕ Error",
               "incompatible": "✕ Incompatible", "loaded": "○ Stopped", "not applicable": "– Not applicable"}


class ExtensionsDialog(QtWidgets.QDialog):
    """Extension list: enable/disable (applies on restart), view errors, open the folder, create a new one."""
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Extensions"); self.resize(760, 460)
        v = QtWidgets.QVBoxLayout(self)
        dirs = ", ".join(str(d) for d in search_dirs()) or "(no extension folder yet)"
        hint = QtWidgets.QLabel(f"Loaded from: {dirs}<br>Update loads extensions added while the app is running. "
                                "Enabling / disabling and code changes to loaded extensions take effect after restarting.")
        hint.setWordWrap(True); hint.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        v.addWidget(hint)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Enabled", "Extension", "Version", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._show_details)
        self.table.itemChanged.connect(self._toggled)
        v.addWidget(self.table, 2)
        self.details = QtWidgets.QPlainTextEdit(); self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select an extension to see its description, source and errors.")
        v.addWidget(self.details, 1)

        self.result = QtWidgets.QLabel(""); self.result.setWordWrap(True)
        v.addWidget(self.result)
        row = QtWidgets.QHBoxLayout()
        update_btn = QtWidgets.QPushButton("⟳ Update"); update_btn.clicked.connect(self.update_extensions)
        update_btn.setToolTip("Look for extensions added since the app started and load them now")
        self.toggle_btn = QtWidgets.QPushButton("Unload"); self.toggle_btn.setEnabled(False)
        self.toggle_btn.setToolTip("Unload: remove the selected extension now (this session only). "
                                   "Load: start an unloaded / disabled extension now.")
        self.toggle_btn.clicked.connect(self._toggle_selected)
        new_btn = QtWidgets.QPushButton("New extension…"); new_btn.clicked.connect(self._new)
        open_btn = QtWidgets.QPushButton("Open extensions folder"); open_btn.clicked.connect(self._open_folder)
        close_btn = QtWidgets.QPushButton("Close"); close_btn.clicked.connect(self.accept)
        row.addWidget(update_btn); row.addWidget(self.toggle_btn); row.addWidget(new_btn); row.addWidget(open_btn); row.addStretch(); row.addWidget(close_btn)
        v.addLayout(row)
        self._fill()

    def _fill(self):
        self.table.blockSignals(True)
        recs = self.manager.records
        self.table.setRowCount(len(recs))
        disabled = self.manager.disabled_ids()
        for i, r in enumerate(recs):
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            chk.setCheckState(QtCore.Qt.Unchecked if r.id in disabled else QtCore.Qt.Checked)
            chk.setData(QtCore.Qt.UserRole, r.id)
            self.table.setItem(i, 0, chk)
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{r.name}  ({r.id})"))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(r.version))
            self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(STATUS_TEXT.get(r.status, r.status)))
        self.table.resizeColumnToContents(0); self.table.resizeColumnToContents(3)
        self.table.blockSignals(False)

    def update_extensions(self):
        changed = self.manager.refresh()
        self._fill()
        self.result.setText(self.manager.summarize(changed))
        if changed:                                          # select the new row to show its details / error
            self.table.selectRow(self.manager.records.index(changed[-1]))
        return changed

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.manager.records[rows[0].row()] if rows else None

    def _toggle_selected(self):
        r = self._selected()
        if r is None: return
        if r.status == "active":
            self.manager.unload(r.id)
            self.result.setText(f"Unloaded {r.name} for this session. Tick/untick Enabled to change startup.")
        else:
            status = self.manager.load(r.id)
            self.result.setText(f"{r.name}: {status}." + (" See error below." if status == "error" else ""))
        row = self.manager.records.index(r)
        self._fill(); self.table.selectRow(row); self._show_details()

    def _show_details(self):
        r = self._selected()
        if r is None:
            self.toggle_btn.setEnabled(False); return
        can_load = r.cls is not None and r.status in ("unloaded", "disabled")
        self.toggle_btn.setText("Unload" if r.status == "active" else "Load")
        self.toggle_btn.setEnabled(r.status == "active" or can_load)
        txt = [r.description or "(no description)", "", f"Source: {r.source}"]
        if r.cls is not None and r.cls.author: txt.append(f"Author: {r.cls.author}")
        if r.error: txt += ["", "Error:", r.error]
        self.details.setPlainText("\n".join(txt))

    def _toggled(self, item):
        if item.column() != 0: return
        self.manager.set_enabled(item.data(QtCore.Qt.UserRole), item.checkState() == QtCore.Qt.Checked)

    def _open_folder(self):
        d = default_dir(); d.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(d)))

    def _new(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New extension", "Extension name:")
        if not ok or not name.strip(): return
        try:
            folder = create_extension(name, default_dir())
        except (ValueError, OSError) as e:
            QtWidgets.QMessageBox.warning(self, "New extension", str(e)); return
        QtWidgets.QMessageBox.information(self, "New extension",
                                          f"Created {folder / '__init__.py'}\n\nEdit it, then press ⟳ Update to load it.")
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))
