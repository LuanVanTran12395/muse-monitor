"""Record RAW data from a Muse S Athena through BrainFlow as a test fixture.

Unlike the app's CSV (timestamps + signal channels only), this file keeps EVERY BrainFlow row
of all three presets (including package_num, marker, battery…) and the boundaries of each read (chunk), so it can be
replayed exactly as the worker received it.

Usage (close Muse Monitor first — BLE allows only one connection). ``--out`` is required, so where a
personal recording lands is always a deliberate choice:

    # private, git-ignored (e.g. for measuring timing):
    PYTHONPATH=src ~/.venvs/musemonitor/bin/python tools/capture_athena.py MuseS-EDAA --seconds 600 --out data/athena_raw_10min.npz
    # a fixture for the golden test — WILL be committed if you add it:
    PYTHONPATH=src ~/.venvs/musemonitor/bin/python tools/capture_athena.py MuseS-EDAA --seconds 30 --out tests/fixtures/athena_raw_<time>.npz

While recording: sit still and follow the on-screen cues (tap / blink) — these landmarks help
check cross-stream latency later. Ctrl+C stops early (what was recorded is still saved).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from brainflow.board_shim import BoardShim, BrainFlowInputParams

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from musemonitor import config as C  # noqa: E402
from musemonitor.device.spec import athena_spec  # noqa: E402

CUES = ((10, "Tap the headset lightly 3 times (tap, tap, tap)"), (20, "Blink hard 3 times"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="BLE device name, e.g. MuseS-EDAA")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--out", required=True,
                    help="output .npz — data/… stays private (git-ignored); tests/fixtures/… is meant to be committed")
    a = ap.parse_args(argv)

    spec = athena_spec()
    presets = {"eeg": spec.eeg.preset, "optics": spec.optics.preset, "imu": spec.imu.preset}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    chunks = {k: [] for k in presets}          # [(array with all rows, time.time() at read)]
    cues_done = []
    wall0 = time.time()
    params = BrainFlowInputParams(); params.serial_number = a.serial; params.other_info = C.OTHER_INFO
    board = BoardShim(spec.board_id, params)
    print(f"Connecting to {a.serial}…", flush=True)
    board.prepare_session()
    try:
        board.start_stream(C.STREAM_BUFFER)
        t0 = time.monotonic(); wall0 = time.time()      # real start once the stream is running
        print(f"Recording {a.seconds:.0f} s — sit still.", flush=True)
        while (el := time.monotonic() - t0) < a.seconds:
            for key, p in presets.items():
                if board.get_board_data_count(p) > 0:
                    d = board.get_board_data(preset=p)
                    if d.shape[1]: chunks[key].append((d, time.time()))
            for sec, msg in CUES:
                if el >= sec and sec not in [c[0] for c in cues_done]:
                    cues_done.append((sec, msg, time.time())); print(f"  ▶ {msg}", flush=True)
            time.sleep(C.POLL_MS / 1000)
    except KeyboardInterrupt:
        print("Stopped early — saving what was recorded.")
    finally:
        try: board.stop_stream()
        except Exception: pass
        board.release_session()

    arrays, meta = {}, {
        "serial": a.serial, "other_info": C.OTHER_INFO, "board_id": spec.board_id, "start_wall": wall0,
        "brainflow_version": BoardShim.get_version(), "poll_ms": C.POLL_MS,
        "cues": [{"at_sec": s, "message": m, "wall": w} for s, m, w in cues_done],
        "board_descr": {k: BoardShim.get_board_descr(spec.board_id, p) for k, p in presets.items()},
    }
    for key in presets:
        cs = chunks[key]
        if not cs:
            print(f"Warning: no {key} data received"); continue
        arrays[f"{key}_data"] = np.hstack([c[0] for c in cs])
        arrays[f"{key}_chunk_lens"] = np.array([c[0].shape[1] for c in cs])
        arrays[f"{key}_poll_wall"] = np.array([c[1] for c in cs])
    np.savez_compressed(out, meta=json.dumps(meta), **arrays)
    for key in presets:
        if f"{key}_data" in arrays:
            d = arrays[f"{key}_data"]
            print(f"  {key:7s}: {d.shape[1]:6d} samples, {len(arrays[key + '_chunk_lens'])} chunks, {d.shape[0]} rows")
    print(f"Saved {out} ({out.stat().st_size / 1e3:.0f} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
