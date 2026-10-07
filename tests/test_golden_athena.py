"""Compare the current code with results locked on raw Athena data (see tests/golden.py).
Skipped until a fixture exists — record one with tools/capture_athena.py, then bless it from the baseline commit."""
import json
from pathlib import Path

import pytest

import golden

FIXTURES = sorted(p for p in (Path(__file__).parent / "fixtures").glob("athena_raw_*.npz")
                  if golden.expected_path(p).exists())


@pytest.mark.skipif(not FIXTURES, reason="no blessed Athena raw fixture yet")
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.stem)
def test_matches_blessed_output(qapp, fixture):
    expected = json.loads(golden.expected_path(fixture).read_text())
    got = golden.compute(fixture)
    assert got["csv"] == expected["csv"], "legacy CSV columns changed"
    assert got["analysis"] == expected["analysis"]


@pytest.mark.skipif(not FIXTURES, reason="no blessed Athena raw fixture yet")
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.stem)
def test_package_num_is_exported(fixture, spec, tmp_path):
    """The new package_num column must hold exactly BrainFlow's package_num row."""
    import csv
    from musemonitor.storage.recording import Recorder
    fx = golden.load_fixture(fixture)
    path = tmp_path / "rec.csv"
    rec = Recorder(path, spec)
    expected = []
    for _, key, d in golden.chunks_in_order(fx):
        x, ts, seq = golden.extract(spec, key, d)
        rec.write(key, ts, x, seq)
        if key == "eeg": expected.extend(seq.tolist())
    rec.close()
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0][-1] == "package_num"
    assert [float(r[-1]) for r in rows[1:]] == expected
