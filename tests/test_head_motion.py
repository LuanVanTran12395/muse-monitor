"""Athena IMU axes should drive the corresponding visible head motion."""

import numpy as np

from extensions.head_motion import PoseTracker, _rotate


def _pose_for_gyro(sensor_channel):
    tracker = PoseTracker(52)
    block = np.zeros((6, 52))
    block[2] = -1.0  # upright Athena gravity in sensor coordinates
    block[sensor_channel] = 45.0
    tracker.add(block, 1.0)
    return tracker


def test_athena_z_turns_face_sideways():
    tracker = _pose_for_gyro(5)
    forward = _rotate(tracker.q, (0, 0, 1))
    assert forward[0] > 0.5
    assert abs(forward[1]) < 0.1
    tracker.recenter()
    assert np.allclose(tracker.q, (1, 0, 0, 0))


def test_athena_y_nods_head():
    tracker = _pose_for_gyro(4)
    forward = _rotate(tracker.q, (0, 0, 1))
    assert forward[1] < -0.5
    assert abs(forward[0]) < 0.1


def test_athena_x_rolls_head():
    tracker = _pose_for_gyro(3)
    up = _rotate(tracker.q, (0, 1, 0))
    assert up[0] < -0.5
