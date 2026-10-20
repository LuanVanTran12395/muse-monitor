# Studies

This folder holds Muse Monitor's **research studies**: experiments with a written protocol, recorded data that can be
traced back to it, and analyses that can be run again. It marks the direction of the project: from a monitor with
demos towards a platform for academic research with consumer EEG.

Each study is a Muse Monitor extension, found by the app like those in `extensions/`, plus its own offline tools and
documentation:

```
study/<name>/
  __init__.py     the extension: runs the experiment inside the app (its own window, settings, recording)
  offline.py      re-analysis of recorded sessions, without the app
  README.md       the protocol, the data format, the analysis, the status and the limits
```

## Principles

- **Protocol first.** Design, parameters and analysis are written down, and reviewed, before data is collected.
  Proposals and reviews are kept in `debate/`, which stays local and is not in the repository.
- **Participants.** Informed consent before any recording. Participants are identified by a code, never by name.
  Participant data is never committed: it goes to `data/`, which is git-ignored.
- **Provenance.** Every session folder records the app version, the device, the parameters and the random seed, so a
  result can be traced to how it was obtained.
- **Measured, estimated, not measured.** Timing and quality are reported for what they are. An estimate is never
  presented as a measurement.
- **Reproducible.** `offline.py` recomputes the reports and results from the raw files.
- **Not a medical device.** Results are research findings, not diagnoses (see the main README).

## Studies

| Study | Status | What it is |
|---|---|---|
| [`p300_bci`](p300_bci/README.md) | experimental, stage A | 3×3 P300 stimulus window (5 command cells), session recording with a timing report, epochs at the stimulus onset and target / non-target ERP; offline `check` / `timing` / `report` / `erp`. No classifier or online control yet. |

Tests for the studies are in `tests/` with the rest of the suite (e.g. `tests/test_p300_bci.py`).
