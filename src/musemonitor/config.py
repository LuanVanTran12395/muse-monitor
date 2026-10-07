"""Every tunable parameter of the app. Pure Python module — imports no third-party library.

Hardware facts (sampling rates, channel counts…) are NOT here; they are read from BrainFlow
in ``musemonitor.device.spec``.
"""

APP_NAME = "Muse Monitor"
ORG_NAME = "MuseMonitor"                 # QSettings key

# ---- Connection / stream --------------------------------------------------------
OTHER_INFO = "preset=p1041;low_latency=true"
STREAM_BUFFER = 450000
SCAN_SEC = 5                     # duration of each BLE scan
NO_PACKET_WARN_SEC = 5.0         # warn if BLE is connected but no EEG packet arrived yet
POLL_MS = 20                     # how often the worker reads data from BrainFlow

# ---- Display / buffers ------------------------------------------------------
WINDOW_SEC = 8                   # default time range
MAX_WINDOW_SEC = 120             # maximum time range (EEG/IMU buffer capacity)
OPT_HIST_SEC = 330               # longer optics buffer for HRV (window up to 300 s)
FIT_SEC = 4                      # signal window on the fit-test screen
REDRAW_MS = 50                   # plot redraw period
TEXT_MS = 500                    # text readouts + contact quality: twice per second
ANALYSIS_MS = 250                # PSD / PPG tabs: four times per second
EEG_FIXED_UV = 200               # fixed ±200 µV scale
FIT_RANGE_UV = 150
TIME_FIT_SEC = 30                # display time axis: linear fit of raw timestamps over the last 30 s

# ---- EEG filters -----------------------------------------------------------------
NOTCH_HZ, NOTCH_Q = 50.0, 30.0
BAND_HZ, BAND_ORDER = (1, 40), 4

# ---- Electrode contact quality (impedance proxy) ---------------------
# Muse/BrainFlow do NOT measure real impedance (kΩ). It is estimated from the EEG itself
# over the last QUALITY_SEC seconds: RMS in 1–40 Hz, RMS of mains noise 45–55 Hz,
# and flat / saturated signal.
QUALITY_SEC = 2
Q_FLAT_UV = 1.0                       # RMS < 1 µV → no signal / disconnected
Q_GOOD = dict(band=30.0, line=5.0)    # Good:  RMS 1–40 Hz ≤ 30 µV and 50 Hz ≤ 5 µV
Q_FAIR = dict(band=80.0, line=15.0)   # Fair:  ≤ 80 µV and ≤ 15 µV; above → Bad

# ---- EEG spectrogram (defaults; the user adjusts them on the tab) ------------------
PSD_WIN_SEC = 1.0
PSD_STEP_SEC = 0.25
PSD_FMAX_HZ = 45
PSD_MAX_CELLS = 1_500_000        # cap on FFT work per update

# ---- PPG / HRV ----------------------------------------------------------------
PPG_BAND_HZ = (0.5, 4.0)         # 30–240 bpm
HRV_WIN_SEC = 60
PPG_AUTO_EVERY_SEC = 5           # Auto mode: re-pick the channel every 5 s
PPG_AUTO_SPAN_SEC = 10           # … based on the last 10 s
IBI_RANGE_S = (0.3, 2.0)         # 30–200 bpm
IBI_MAX_DEV = 0.3                # drop IBIs more than 30% from the median

# ---- fNIRS (modified Beer–Lambert) ------------------------------------------
# Molar extinction coefficients (cm⁻¹/M, Prahl); rows = wavelength [730, 850 nm], columns = [HbO, HbR].
# Athena's optical channel → wavelength mapping is NOT published by BrainFlow; the default follows the
# OpenMuse order (O1 = left-outer 730 nm, O3 = left-outer 850 nm). Re-pick channels on the tab if needed.
FNIRS_EXT = ((390.0, 1102.2), (1058.0, 691.32))
FNIRS_CH = (0, 2)
FNIRS_DPF = 6.0
FNIRS_DIST_CM = 3.0
FNIRS_LOWPASS_HZ = 0.5           # removes the cardiac pulse from Hb

# ---- Recording sessions ------------------------------------------------------------------
# Each Start recording creates data/muse_<time>/ holding the CSVs + report.html (whole-session PSD).
DATA_DIR_ENV = "MUSEMONITOR_DATA_DIR"     # set this environment variable to use another data folder
START_EVENT_LABEL = "0"                   # event added automatically when recording starts
REPORT_PSD_SEG_SEC = {"eeg": 4.0, "opt": 16.0, "imu": 8.0}   # Welch segment length per stream
REPORT_EEG_FMAX = 60.0
REPORT_BANDS = {"delta": (1, 4), "theta": (4, 8), "alpha": (8, 13), "beta": (13, 30), "gamma": (30, 45)}
