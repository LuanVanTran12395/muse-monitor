"""Athena battery: BrainFlow ≤ 5.23 reports raw/512 (full = 50%); the worker corrects it to raw/256."""
import numpy as np
import pytest

from musemonitor import config as C
from musemonitor.device import worker as W


@pytest.mark.parametrize("version, scale", [("5.23.0", 2.0), ("5.22.1", 2.0), ("5.23", 2.0),
                                            ("5.24.0", 1.0), ("6.0.0", 1.0), ("5.24.0rc1", 1.0)])
def test_scale_depends_on_brainflow_version(version, scale):
    assert W.athena_battery_scale(version) == scale


def test_installed_brainflow_is_handled():
    assert W.athena_battery_scale() in (1.0, C.ATHENA_BATTERY_SCALE)


def test_full_battery_reads_100_percent():
    raw = 100 * 256                                      # raw u16 the headset sends at 100 % (raw/256 = 100)
    brainflow_value = raw / 512                          # what BrainFlow ≤ 5.23 puts in the battery row
    assert brainflow_value * W.athena_battery_scale("5.23.0") == pytest.approx(100.0)
    assert np.isclose(brainflow_value, 50.0)
