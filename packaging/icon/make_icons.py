"""Regenerate every app-icon file from icon.svg (the editable source).

    ~/.venvs/musemonitor/bin/python packaging/icon/make_icons.py

Writes, next to this file:
    MuseMonitor.icns      macOS app (the art inset with the standard margin of macOS icons: 824 of 1024 px)
    MuseMonitor.ico       Windows app (full bleed; 16 … 256 px, PNG-compressed entries)
    preview.png           a 512 px preview
and src/musemonitor/ui/app_icon.png (256 px, full bleed): the window / dock icon when running from source.

The .icns needs macOS (iconutil); elsewhere it is skipped. The generated files are committed, so building the app
does not need this script — run it only after changing icon.svg.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SVG = HERE / "icon.svg"
MAC_ART = 824 / 1024                       # macOS icon grid: the rounded square fills 824 of 1024 px


def render(size, inset=1.0):
    """The SVG drawn into a transparent size × size image, scaled by ``inset`` and centred."""
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing); p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    art = size * inset
    QtSvg.QSvgRenderer(str(SVG)).render(p, QtCore.QRectF((size - art) / 2, (size - art) / 2, art, art))
    p.end()
    return img


def png_bytes(img):
    buf = QtCore.QBuffer(); buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    """ICO with PNG entries (supported since Windows Vista)."""
    blobs = [png_bytes(render(s)) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, blob in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(head + entries + b"".join(blobs))


def write_icns(path):
    if sys.platform != "darwin" or not shutil.which("iconutil"):
        print("skip .icns (needs macOS iconutil)"); return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "MuseMonitor.iconset"; iconset.mkdir()
        for s in (16, 32, 128, 256, 512):
            render(s, MAC_ART).save(str(iconset / f"icon_{s}x{s}.png"))
            render(2 * s, MAC_ART).save(str(iconset / f"icon_{s}x{s}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841 (Qt needs it)
    write_icns(HERE / "MuseMonitor.icns")
    write_ico(HERE / "MuseMonitor.ico")
    render(512).save(str(HERE / "preview.png"))
    render(256).save(str(REPO / "src" / "musemonitor" / "ui" / "app_icon.png"))
    print("written:", *(p.name for p in sorted(HERE.glob("MuseMonitor.*"))), "preview.png", "app_icon.png")


if __name__ == "__main__":
    main()
