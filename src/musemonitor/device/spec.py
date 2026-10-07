"""Channel / sampling-rate description of a device, read from BrainFlow instead of hard-coded.

Other devices: see device/profiles.py (optional ``musemonitor_*`` libraries with a ``DEVICE_PROFILE``).
"""
from dataclasses import dataclass, field

from brainflow.board_shim import BoardShim, BoardIds, BrainFlowPresets


@dataclass(frozen=True)
class StreamSpec:
    preset: int
    fs: int
    rows: list            # rows of this stream in the BrainFlow data array
    ts_row: int
    names: list = field(default_factory=list)
    seq_row: int = None   # BrainFlow package_num row (None = the device has none)

    @property
    def n(self):
        return len(self.rows)


@dataclass(frozen=True)
class DeviceSpec:
    board_id: int
    eeg: StreamSpec
    optics: StreamSpec
    imu: StreamSpec
    battery_row: int      # battery lives in the optics (ancillary) preset
    n_acc: int            # imu.rows = accel + gyro


def athena_spec():
    board = BoardIds.MUSE_S_ATHENA_BOARD.value
    dflt = BrainFlowPresets.DEFAULT_PRESET.value
    anc = BrainFlowPresets.ANCILLARY_PRESET.value       # optics + pin
    aux = BrainFlowPresets.AUXILIARY_PRESET.value       # Athena's IMU is in the aux preset
    opt_rows = BoardShim.get_optical_channels(board, anc)
    acc = BoardShim.get_accel_channels(board, aux)
    gyr = BoardShim.get_gyro_channels(board, aux)
    return DeviceSpec(
        board_id=board,
        eeg=StreamSpec(dflt, BoardShim.get_sampling_rate(board), BoardShim.get_eeg_channels(board),
                       BoardShim.get_timestamp_channel(board), BoardShim.get_eeg_names(board),
                       BoardShim.get_package_num_channel(board, dflt)),
        optics=StreamSpec(anc, BoardShim.get_sampling_rate(board, anc), opt_rows,
                          BoardShim.get_timestamp_channel(board, anc), [f"O{i+1}" for i in range(len(opt_rows))],
                          BoardShim.get_package_num_channel(board, anc)),
        imu=StreamSpec(aux, BoardShim.get_sampling_rate(board, aux), acc + gyr,
                       BoardShim.get_timestamp_channel(board, aux),
                       ["acc_x", "acc_y", "acc_z", "gyro_x", "gyro_y", "gyro_z"],
                       BoardShim.get_package_num_channel(board, aux)),
        battery_row=BoardShim.get_battery_channel(board, anc),
        n_acc=len(acc),
    )
