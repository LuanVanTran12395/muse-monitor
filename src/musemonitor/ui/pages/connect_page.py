from PySide6 import QtCore, QtWidgets

from ... import config as C


class ConnectPage(QtWidgets.QWidget):
    """Screen 1: BLE scan, pick / type a device name, Connect."""
    connect_clicked = QtCore.Signal()      # Connect clicked (or Cancel while connecting)
    rescan_clicked = QtCore.Signal()

    PROFILE_ROLE = QtCore.Qt.UserRole + 1

    def __init__(self, ctx, profiles=None):
        super().__init__()
        self.ctx = ctx; self.busy = False
        self.profile_names = {p.id: p.name for p in (profiles or [])}
        kinds = " / ".join(self.profile_names.values()) or "Muse"
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(60, 40, 60, 40); v.setSpacing(12)
        v.addWidget(QtWidgets.QLabel("<h2>Connect a device</h2>"))
        v.addWidget(ctx.plots.muted_label(f"Supported: {kinds}. Turn on the headset, close any other app connected "
                                          "to it, then pick the device from the list."))
        row = QtWidgets.QHBoxLayout()
        self.scan_btn = QtWidgets.QPushButton("⟳ Rescan"); self.scan_btn.clicked.connect(self.rescan_clicked)
        self.scan_label = QtWidgets.QLabel("")
        row.addWidget(self.scan_btn); row.addWidget(self.scan_label); row.addStretch()
        v.addLayout(row)
        self.dev_list = QtWidgets.QListWidget()
        self.dev_list.setStyleSheet("QListWidget{font-size:14pt} QListWidget::item{padding:10px}")
        self.dev_list.itemSelectionChanged.connect(self._on_selected)
        self.dev_list.itemDoubleClicked.connect(lambda _: self.connect_clicked.emit())
        v.addWidget(self.dev_list, 1)
        manual = QtWidgets.QHBoxLayout()
        manual.addWidget(QtWidgets.QLabel("Or enter name:"))
        self.dev_name = QtWidgets.QLineEdit(ctx.settings.value("last_device", ""))
        self.dev_name.setPlaceholderText("e.g. MuseS-EDAA")
        self.dev_name.textChanged.connect(lambda t: self.conn_btn.setEnabled(bool(t.strip()) and not self.busy))
        manual.addWidget(self.dev_name, 1)
        v.addLayout(manual)
        bottom = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.conn_btn = QtWidgets.QPushButton("Connect  →"); self.conn_btn.setMinimumHeight(40)
        self.conn_btn.setEnabled(bool(self.device_name()))
        self.conn_btn.clicked.connect(self.connect_clicked)
        bottom.addWidget(self.status, 1); bottom.addWidget(self.conn_btn)
        v.addLayout(bottom)

    def device_name(self):
        return self.dev_name.text().strip()

    def selected_profile_id(self):
        """Profile of the selected scan result if it is the name being connected, else None."""
        items = self.dev_list.selectedItems()
        if items and items[0].data(QtCore.Qt.UserRole) == self.device_name():
            return items[0].data(self.PROFILE_ROLE)
        return None

    def _on_selected(self):
        items = self.dev_list.selectedItems()
        if items: self.dev_name.setText(items[0].data(QtCore.Qt.UserRole))

    # ---- state driven by the controller ------------------------------------
    def set_scanning(self, on):
        self.scan_btn.setEnabled(not on and not self.busy)
        if on: self.scan_label.setText(f"Scanning Bluetooth ({C.SCAN_SEC} s)…")

    def set_scan_message(self, text):
        self.scan_label.setText(text)

    def show_devices(self, devs):
        self.dev_list.clear()
        last = self.ctx.settings.value("last_device", "")
        for dev in devs:
            name, addr, rssi = dev[:3]
            pid = dev[3] if len(dev) > 3 else None
            kind = f"    [{self.profile_names[pid]}]" if pid in self.profile_names and len(self.profile_names) > 1 else ""
            bars = "▂▄▆█"[:max(1, min(4, (rssi + 100) // 12))]
            it = QtWidgets.QListWidgetItem(f"{name}    {bars}  {rssi} dBm{kind}" + ("    (last used)" if name == last else ""))
            it.setData(QtCore.Qt.UserRole, name); it.setData(self.PROFILE_ROLE, pid); it.setToolTip(addr)
            self.dev_list.addItem(it)
            if name == last: it.setSelected(True)
        self.scan_label.setText(f"Found {len(devs)} device(s)" if devs else "No device found — make sure the headset is on, then rescan.")

    def set_busy(self, busy):
        """busy = connecting/streaming: the button becomes Cancel and device selection is locked."""
        self.busy = busy
        self.conn_btn.setText("Cancel" if busy else "Connect  →")
        self.conn_btn.setEnabled(busy or bool(self.device_name()))
        for w in (self.scan_btn, self.dev_list, self.dev_name): w.setEnabled(not busy)

    def set_cancel_enabled(self, on):
        self.conn_btn.setEnabled(on)

    def set_status(self, text):
        self.status.setText(text)
