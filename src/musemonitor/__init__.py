"""Muse Monitor — realtime EEG / PPG / fNIRS / IMU monitor for Muse S Athena."""
# numpy/scipy/brainflow MUST be imported BEFORE PySide6: once PySide6 is imported,
# shiboken hooks every import and reads each module's source → importing scipy becomes very slow / hangs.
# Done in the package __init__ so every entry point (app, tests, scripts) follows it.
import numpy  # noqa: F401
import scipy.signal  # noqa: F401
import brainflow.board_shim  # noqa: F401

__version__ = "0.1.0"
