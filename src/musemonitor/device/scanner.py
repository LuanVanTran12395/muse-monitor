from PySide6 import QtCore

from .. import config as C


class BleScanner(QtCore.QObject):
    """BLE scan with bleak (CoreBluetooth on macOS). Keeps devices matching a profile's name pattern
    (default: name contains 'Muse')."""
    found = QtCore.Signal(list)        # [(name, address, rssi, profile_id)]
    error = QtCore.Signal(str)
    finished = QtCore.Signal()

    def __init__(self, profiles=None):
        super().__init__()
        self.profiles = profiles

    @QtCore.Slot()
    def run(self):
        try:
            import asyncio
            from bleak import BleakScanner

            async def scan():
                return await BleakScanner.discover(timeout=C.SCAN_SEC, return_adv=True)
            out = []
            for addr, (dev, adv) in asyncio.run(scan()).items():
                name = adv.local_name or dev.name or ""
                if self.profiles is None:
                    if "muse" in name.lower(): out.append((name, addr, adv.rssi, None))
                    continue
                prof = next((p for p in self.profiles if p.matches(name)), None)
                if prof is not None: out.append((name, addr, adv.rssi, prof.id))
            out.sort(key=lambda d: -d[2])
            self.found.emit(out)
        except ImportError:
            self.error.emit("Missing 'bleak' library — run run.command again to install it.")
        except Exception as e:
            self.error.emit(f"Bluetooth scan error: {type(e).__name__}: {e}")
        finally:
            self.finished.emit()
