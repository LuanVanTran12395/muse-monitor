import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")    # run UI tests without a display

import musemonitor  # noqa: E402,F401  — loads numpy/scipy/brainflow BEFORE PySide6
import pytest  # noqa: E402


@pytest.fixture(scope="session")
def spec():
    from musemonitor.device.spec import athena_spec
    return athena_spec()


@pytest.fixture(scope="session")
def qapp():
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from musemonitor.ui.style import apply_app_style
    apply_app_style(app)                   # same style as the real app
    return app


@pytest.fixture
def settings(tmp_path):
    """Temporary QSettings (.ini file) — tests must never touch the user's real settings."""
    from PySide6 import QtCore
    return QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)


# PySide6 6.11 can segfault while the interpreter shuts down (Py_FinalizeEx → gc → PySide slot
# destructor), turning a fully green run into exit code 139. Once pytest has reported everything,
# exit with pytest's own status and skip interpreter finalization. Results are not affected.
_EXIT_STATUS = 0


def pytest_sessionfinish(session, exitstatus):
    global _EXIT_STATUS
    _EXIT_STATUS = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    import sys
    if "PySide6" in sys.modules:
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(_EXIT_STATUS)
