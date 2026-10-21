# PyInstaller spec — one-folder build of Muse Monitor (debate/claude-packaging-proposal.md).
#   pyinstaller packaging/musemonitor.spec --noconfirm --distpath dist --workpath build
# macOS: dist/Muse Monitor.app · Windows: dist/Muse Monitor/Muse Monitor.exe
import ast
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import musemonitor  # noqa: E402  (version)

# extensions and studies are data: the app loads them from files at run time (plugins/loader.py, bundled_dirs())
datas, binaries, hidden = [], [], []
for folder in ("extensions", "study"):
    for p in (ROOT / folder).rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            datas.append((str(p), str(p.parent.relative_to(ROOT))))


def imports_of(folder):
    """Top-level modules imported by the extensions — PyInstaller cannot see them (loaded dynamically)."""
    names = set()
    for p in folder.rglob("*.py"):
        try: tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError: continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level: names.add(node.module)
    return names


local = {p.stem for f in ("extensions", "study") for p in (ROOT / f).rglob("*.py")}   # sibling modules, not libraries
for folder in ("extensions", "study"):
    hidden += sorted(n for n in imports_of(ROOT / folder)
                     if not n.startswith(("extensions", "study")) and n.split(".")[0] not in local)
hidden += collect_submodules("musemonitor") + collect_submodules("scipy.signal")
hidden += collect_submodules("pyqtgraph", filter=lambda name: not name.startswith("pyqtgraph.opengl"))   # no PyOpenGL
hidden += ["PySide6.QtMultimedia", "PySide6.QtSvg", "PySide6.QtOpenGLWidgets", "PySide6.QtNetwork"]
hidden += {"darwin": ["bleak.backends.corebluetooth"], "win32": ["bleak.backends.winrt"]}.get(sys.platform, [])
ICON = ROOT / "packaging" / "icon"                                  # generated from icon/icon.svg (make_icons.py)
datas.append((str(ROOT / "src" / "musemonitor" / "ui" / "app_icon.png"), "musemonitor/ui"))   # the window icon
for pkg in ("brainflow", "pylsl", "cv2", "bleak"):                    # native libraries and data files
    d, b, h = collect_all(pkg); datas += d; binaries += b; hidden += h

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(ROOT / "src")], binaries=binaries, datas=datas,
             hiddenimports=sorted(set(hidden)), excludes=["tkinter", "pytest", "PyQt5", "PyQt6"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Muse Monitor", console=False,
          argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None,
          icon=str(ICON / "MuseMonitor.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="Muse Monitor")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="Muse Monitor.app", bundle_identifier="io.github.luanvantran12395.musemonitor",
                 icon=str(ICON / "MuseMonitor.icns"),
                 version=musemonitor.__version__,
                 info_plist={
                     "CFBundleShortVersionString": musemonitor.__version__,
                     "NSHighResolutionCapable": True,
                     "LSMinimumSystemVersion": "12.0",
                     "NSBluetoothAlwaysUsageDescription":
                         "Muse Monitor connects to your Muse headset over Bluetooth to record EEG, optics and motion.",
                     "NSCameraUsageDescription":
                         "Optional: the camera only recenters the head pointer when you face the screen. Frames are "
                         "analysed in memory and never shown or saved.",
                 })
