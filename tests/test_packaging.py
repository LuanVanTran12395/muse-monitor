"""Packaged-app behaviour (debate/claude-packaging-proposal.md): where extensions are found and created when frozen,
and the --self-check of an installation."""
import sys

import pytest

from musemonitor.plugins import loader


@pytest.fixture
def frozen_app(tmp_path, monkeypatch):
    """Pretend to be a PyInstaller app: sys.frozen + sys._MEIPASS (the read-only resource folder)."""
    bundle = tmp_path / "bundle"
    (bundle / "extensions").mkdir(parents=True); (bundle / "study").mkdir()
    user = tmp_path / "home" / ".musemonitor" / "extensions"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(loader, "USER_DIR", user)
    monkeypatch.delenv(loader.ENV_VAR, raising=False)
    return bundle, user


def test_from_source_the_repo_folders_are_used(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert not loader.frozen()
    assert loader.bundled_dirs() == (loader.PROJECT_DIR, loader.STUDY_DIR)
    assert loader.default_dir() == loader.PROJECT_DIR


def test_frozen_extensions_come_from_the_bundle_and_new_ones_go_to_the_user_folder(frozen_app):
    bundle, user = frozen_app
    assert loader.frozen()
    assert loader.bundled_dirs() == (bundle / "extensions", bundle / "study")
    user.mkdir(parents=True)
    assert loader.search_dirs() == [bundle / "extensions", bundle / "study", user]
    assert loader.default_dir() == user                                          # never inside the app


def test_the_new_extension_button_writes_to_the_user_folder_when_frozen(frozen_app, qapp, spec, settings, monkeypatch):
    """In the packaged app the supported way to create an extension is the UI button (no `plugins new` command)."""
    from PySide6 import QtGui, QtWidgets
    from musemonitor.ui import main_window as mw
    from musemonitor.ui.widgets.extensions_dialog import ExtensionsDialog
    bundle, user = frozen_app
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *a, **k: ("Blink Mouse", True))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: pytest.fail(str(a)))
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda *a, **k: True)
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[])
    try:
        ExtensionsDialog(w.extensions, w)._new()
        made = [p for p in user.iterdir()] if user.exists() else []
        assert made and (made[0] / "__init__.py").exists()
        assert not any((bundle / "extensions").iterdir())                        # nothing written into the app
    finally:
        w.close()


def test_self_check_passes_from_source(qapp, monkeypatch, tmp_path):
    """Every feature is exercised (no headset); from source a library that is not installed is a SKIP, not a FAIL.
    Nothing is written to the user's data folder."""
    from musemonitor import selfcheck
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    lines = []
    assert selfcheck.run(out=lines.append) == 0, "\n".join(lines)
    names = [line.split()[1] for line in lines if line.startswith("  ")]
    assert names == [n for n, _ in selfcheck.CHECKS]
    assert lines[-1] == "PASSED" and not (tmp_path / "data").exists()           # the data folder is only named


def test_self_check_counts_a_failure(qapp, monkeypatch):
    from musemonitor import selfcheck
    def broken(ctx): raise RuntimeError("liblsl missing")
    monkeypatch.setattr(selfcheck, "CHECKS", [("lsl", broken)])
    lines = []
    assert selfcheck.run(out=lines.append) == 1
    assert any("FAIL" in l and "liblsl missing" in l for l in lines) and lines[-1].startswith("FAILED")


def test_main_dispatches_self_check(monkeypatch):
    from musemonitor import app, selfcheck
    monkeypatch.setattr(selfcheck, "run", lambda out=print: (out("  OK    x  y"), 7)[1])
    assert app.main(["musemonitor", "--self-check"]) == 7


def test_self_check_report_file(monkeypatch, tmp_path):
    from musemonitor import app, selfcheck
    monkeypatch.setattr(selfcheck, "run", lambda out=print: (out("  OK    data  fine"), out("PASSED"), 0)[2])
    report = tmp_path / "check.txt"
    assert app.main(["musemonitor", "--self-check", "--report", str(report)]) == 0
    assert report.read_text().splitlines() == ["  OK    data  fine", "PASSED"]


def test_the_icon_files_are_generated_from_the_svg_and_used(qapp):
    from pathlib import Path
    from PySide6 import QtGui
    repo = Path(__file__).resolve().parents[1]
    icon = repo / "packaging" / "icon"
    assert (icon / "icon.svg").read_text().startswith("<svg") and (icon / "design-A-headband-eeg.pdf").exists()
    ico = (icon / "MuseMonitor.ico").read_bytes()
    assert ico[:4] == b"\x00\x00\x01\x00" and int.from_bytes(ico[4:6], "little") == 7          # 7 sizes, 16 … 256
    assert (icon / "MuseMonitor.icns").read_bytes()[:4] == b"icns"
    win = QtGui.QImage(str(repo / "src" / "musemonitor" / "ui" / "app_icon.png"))
    assert win.width() == 256 and win.pixelColor(128, 128).alpha() == 255
    spec = (repo / "packaging" / "musemonitor.spec").read_text()
    assert "MuseMonitor.icns" in spec and "MuseMonitor.ico" in spec and "app_icon.png" in spec
