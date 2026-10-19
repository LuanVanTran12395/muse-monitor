# LSL Outlet

Streams live **Muse S Athena** data to [Lab Streaming Layer](https://labstreaminglayer.org) so that
LabRecorder (XDF files) or any LSL inlet can record it alongside other devices and stimulus software.

| Stream | `type` | Content |
|---|---|---|
| `MuseMonitor-Athena-EEG` | `EEG` | 4 channels TP9, AF7, AF8, TP10, µV, float32, nominal 256 Hz, one timestamp per sample |
| `MuseMonitor-Athena-Markers` | `Markers` | the label of each event (Space key, or `app.mark_event` from an extension) |
| `MuseMonitor-Athena-Quality` | `Quality` | one JSON line per timing-state change (`schema` `musemonitor.quality/1`) |

Optics and IMU are not streamed yet.

## Install and use

```bash
pip install -e .[lsl]          # = pip install "pylsl>=1.16.2"
```

Checked on macOS arm64 with pylsl 1.18.5 (liblsl 1.18, bundled in the wheel; no separate install).
Other platforms: if `import pylsl` cannot find liblsl, see the pylsl README.

1. Connect the headset as usual.
2. **Extensions ▸ LSL Outlet ▸ Start LSL streams**. The streams are **off by default** and are not
   remembered between app starts. *Start* before connecting opens them when the device connects.
3. Record with LabRecorder (or any inlet). **Extensions ▸ LSL Outlet ▸ LSL status…** shows whether
   the outlets run, the current timing flag, counters and the hook cost.

An inlet only receives what is sent after it connects, so a recorder that joins after *Start*
never sees the `open` event. The extension therefore re-sends the current state as a `status` event
when the Quality stream gets its first consumer and every 5 s. Closed outlets are kept alive for 1 s,
because liblsl drops a record pushed right before an outlet is destroyed (both found with LabRecorder).

"Active" in *Manage extensions* only means the extension is loaded; the status dialog says whether
the outlets are running. Without pylsl the extension still loads, and *Start* explains what is missing.

**LabRecorder** runs on the same Mac with no extra hardware or network (LSL uses the local network
stack; allow incoming connections if the macOS firewall asks). Download it from the
[App-LabRecorder releases](https://github.com/labstreaminglayer/App-LabRecorder/releases). Read XDF
files with `pip install pyxdf`; `tools/xdf_check.py` checks a recording against the app's CSV.

## Timestamps — what they are and are not

- BrainFlow stamps every EEG sample with the time the **host received** it (samples of one BLE packet
  often share a value). The extension maps that to LSL's clock and smooths it with
  `musemonitor.core.online_timeline.OnlineTimeline`: strictly increasing, spaced by the tracked
  sampling period. Metadata: `timing/clock_policy = host_receive_smoothed`.
- They are an **estimate from host receive times, not calibrated against an external stimulus**.
  The BLE/BrainFlow latency is not removed. For ERP work, measure your setup with a photodiode or
  similar; the Quality stream only says where the algorithm itself is unsure.
- Markers: the time Space was pressed (the value in `_events.csv`), mapped to LSL's clock with the
  clock offset measured at that time. If the system clock stepped around it, a `marker_uncertain`
  Quality event is sent.

## Quality stream

Every record: `v`, `event`, `seq`, `segment`. LSL timestamp = when it was emitted (never decreasing).
Where it applies on the EEG is in the JSON: `input_sample_index` counts every EEG sample received in
this connection (dropped ones included), `published_sample_index` counts samples of the current EEG
outlet. Events: `open`, `status`, `state`, `rebase`, `resume`, `eeg_closed`, `marker_uncertain`, `guard_drop`,
`close` (details in the module docstring).

`reason` values (`null` = not flagged): `pause_pending`, `pause_unrecovered_after_wait`, `clock_step`,
`invalid_timestamp`, `outlier`, `rebase`, and `timing_uncertain:<cause>` for everything after an
unrecovered pause or a rebase.

**Flags are kept for the whole device connection.** After an unrecovered pause or a rebase, the
remaining samples stay flagged — data may still be arriving with an unknown delay, and the arrival rate
cannot tell. Stop/Start of the streams does **not** clear it (the BLE/BrainFlow buffer is not emptied);
only disconnecting and reconnecting the device does. An `open` event says `inherited: true` when the
state comes from earlier in the same connection, and `monitoring_since` says whether the extension
saw the connection from its start (`connect`) or was loaded later (`extension_enabled_mid_connection`).

## Rebase: dropped samples

The EEG outlet's timestamps never go back. When the timeline re-anchors backwards (a *rebase*, e.g.
after a backlog was drained slowly), the samples that would go back are **dropped and counted**
(`rebase` event when detected, `resume` with the count when publishing again). The CSV keeps every
sample. One drop episode may drop at most `ceil(2.0 s × 256)` = 513 samples (`MAX_REBASE_DROP_S`, a
trial value); beyond that the EEG outlet is closed (`eeg_closed`), Markers and Quality keep running.
*Stop* and *Start* again once the timestamps have caught up, or reconnect the device. The last
published timestamp is kept for the whole connection, so a new EEG outlet never starts below it.

Counters (in `close` and the status dialog): per EEG outlet
`received = published + rebase_dropped + guard_dropped`; per connection
`timeline_samples = published + rebase_dropped + guard_dropped + monitored_while_eeg_off`.

## Limits

- `source_id` = hash of board id + BLE name: stable for one headset on one machine. Two headsets with
  the same BLE name get the same id.
- Pushes run in the EEG hook on the GUI thread (liblsl copies and sends on its own thread). The hook
  cost is measured (status dialog); if p99 exceeds about 2 ms or the UI stutters, a separate thread
  will be considered.
- The rebase and pause branches are tested on a simulator (`tests/timeline_sim.py`); how LabRecorder
  joins a restarted outlet in one XDF stream is to be checked on real files.

## Verification status

CI (`tests/test_lsl_outlet.py`, fake pylsl): push format, the quality contract on 6 simulated
scenarios × 10 seeds, drops and the drop limit, the watermark across restarts, lifecycle through the
extension manager, missing pylsl / liblsl, metadata, review windows.

On a real Muse S Athena (2026-10-09, macOS arm64, LabRecorder 1.17.0): a 5.7-min XDF recording next to
the app's CSV — EEG strictly increasing, all 85 232 overlapping samples bit-equal and in order, markers
match `_events.csv` (spacing within 0.6 ms). Details and open points: `debate/claude-lsl-athena-stage3-report.md`.
