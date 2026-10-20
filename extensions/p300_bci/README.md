# P300 BCI (experimental) — stage A

A research prototype inspired by Li, Liu, Cao, *Robotic Motion Control via P300-based Brain-Computer Interface
System* (DOI `10.24297/ijct.v23i.9538`). **Stage A only:** a 3 × 3 stimulus with 5 command cells, session recording
with a timing report, epochs cut at the **stimulus onset**, and target / non-target ERPs.

There is **no classifier and no online control** in this version (stages B and C), and nothing here reproduces or
claims the paper's 84.1 % / 81.2 %. Panel: **Analysis ▸ Other ▸ P300 (experimental)** (it moves to HCI/BCI ▸ BCI if
the `BCI` category is approved).

## Run a session

1. Connect the Muse S Athena and do the fit-test (TP9 / TP10 must not be *Bad*).
2. Tick the panel, open **P300 (experimental)**. Wait until **EEG timing** reads *ready* (about 20 s of data is
   needed to measure the stream; until then **Start** is greyed out and its tooltip says why).
3. **Open stimulus window**, put it on the screen the participant looks at (`F` / `F11` toggles full screen, `Esc`
   leaves full screen). Keep it visible: a covered or minimised window is not painted, and those flashes have no
   onset (the status shows "⚠ … flashes not painted").
4. Enter the **Subject ID** (required — a code such as `S01`, not a name: letters, digits, `-`, `_`, up to 32; the
   last one is pre-filled). Set the session (defaults = the paper): interval 400 ms, flash 100 ms, repetitions, trials per block, blocks,
   rest, cue, mode. Press **▶ Start**.
   - **Random seed**: by default a new seed is drawn at every Start (new target order, saved in `config.json` so the
     plan can be rebuilt). Tick **Fixed** to reuse the number shown (repeat a session exactly).
   - **Repetition variation** (± R): each trial's repetitions drawn in `R ± this` from the seed — every cell still
     flashes once per repetition, so classes stay balanced within a trial. Needed for the count question.
   - **Count question** (off / 2–20 s): after each trial's tail (no epoch contains the key presses) the stimulus
     window asks how many times the target flashed; the participant types digits, ⌫ deletes, Enter confirms. The
     schedule never waits: the window closes after the set time. Keys during the flashes are still ignored in
     *EEG only* mode.

   **C1 protocol** (`debate/claude-p300-stage-a-round-4.md`): interval 800 ms, repetitions 10, variation ± 2, count
   question 5 s, 5 trials × 4 blocks, rest 60 s, seed not fixed. **Do not touch the headset during the session,
   breaks included** (on 2026-10-19 adjusting it during a break silenced the EEG stream); if contact turns poor, note
   it instead. Before each attempt: power-cycle and reconnect the headset, fit-test, and check the tab's **Stream**
   line reads *streaming*.
5. **Instructions** (option *Show step-by-step instructions first*, on by default; Vietnamese or English): six pages
   on the stimulus window, all with the same layout so the participant knows where to look — progress dots, title,
   an illustration (line pictograms; the example page shows the real grid with the target outlined and flashing
   slowly), the text in large type that scales with the window and is shrunk only as much as needed to fit, and big
   key icons at the bottom: **←** back on its own (dimmed on the first page), **Space / → / click** grouped under one
   word (*next*, *start* on the last page). **Esc** (or **■ Stop**, closing the window, a disconnect) cancels —
   nothing has been recorded. The pages follow the configuration (duration, trials, breaks; response-assisted mode
   asks for Space presses).
6. **Countdown** (0–10 s, default 5): a large number inside a shrinking ring. When it ends, readiness is checked
   again (stream, EEG timing, contact) and only then the session folder is created and recording starts — reading time
   is not part of the data or the timing report (`config.json → preparation` records whether instructions were shown,
   the language, the countdown and the seconds spent before the session).
   **Between blocks** the window shows a break screen (seconds left, a hint to blink and relax) and, for the last
   *countdown* seconds, the same large countdown before the next block (visual only: the schedule is unchanged; a
   break shorter than the countdown simply counts down from its own length).
   **Sounds** (option *Beep at session start, block start and end*, on by default): a short high beep when the session
   starts and when each block starts, two rising tones when it ends (one low tone if it was interrupted). They are
   played only when no cell is flashing (block-start beep at the cue, ≥ cue + blank before the first flash) and each
   one is written to `log.txt` with its time, because a tone can itself evoke an auditory response.
7. Each trial: the target cell is outlined ("Look at: Forward — count its flashes"), then every command cell flashes
   once per repetition in random order. Ask the participant to count the target's flashes silently.
8. At the end (or **■ Stop**) the files are closed and the ERP is computed in the background and drawn in the tab.
   **Analyse session…** opens any earlier session folder.

**Modes**
- **EEG only (no keys)** — the default. Key presses are ignored and never reveal the target.
- **Response-assisted** — Space presses are recorded in `keys.csv`, apart from flash times. Results from this mode
  are labelled and must not be reported as EEG-only control.

For a session, show only the P300 tab and close heavy tabs: the app's plots redraw on the same thread that
schedules the flashes.

## Files of a session

`data/p300_bci/<YYYYmmdd_HHMMSS>_<subject ID>/` (sessions recorded before the ID existed have no suffix) — next to the app's own recordings, in the same data folder
(`$MUSEMONITOR_DATA_DIR` → `<repo>/data` → `~/MuseMonitor/data`). A new folder every time, never overwritten. `data/`
is git-ignored, so participant EEG is never committed or published; it is never stored inside the extension's code
folder.

| File | Content |
|---|---|
| `config.json` | `subject_id`, every parameter, seed, mode, preset, device, channels, sampling rate, contact at start, versions, path of the app recording if one was running; at the end: `completed`, `stop_reason`, `rows_written`, writer statistics |
| `stimuli.csv` | one row per flash: cell, target or not, `planned_mono`, `fired_mono` (timer), `painted_mono` (first Qt paint = **software onset**), the same for the offset, `late_ms`, `missed` |
| `trials.csv` | target, cue, start, end, `aborted`, `repetitions` of the trial, count question: `ask_on_mono`, `count_answer`, `answer_mono`, `count_correct` (empty when not asked; older sessions without these columns load with them as `None`, repetitions from the config) |
| `keys.csv` | response-assisted only: key, Qt timestamp, time handled (monotonic and Unix) |
| `eeg.csv` | one row per sample: index, raw receive time (Unix), the same in the monotonic clock (`r_mono`), the online timeline estimate (`t_mono_online`), segment, flag, channels in µV (unfiltered) |
| `clock.csv` | each Unix ↔ monotonic measurement (`ClockBridge`) |
| `contact.csv` | electrode contact every 2 s during the session: level (Good / Fair / Bad / No signal), signal RMS and 50 Hz noise RMS per channel — the same estimate as the fit-test |
| `report.html` | the session report (below), written after the session; `erp_<signal>.csv` next to it hold the ERP curves |
| `timing.json` | the timing report (below) |
| `log.txt` | start, stop and reason, errors |

Stop reasons: `completed`, `stopped`, `disconnected`, `unloaded`, `window_closed`, `writer_backlog` (the writer fell
more than about half a minute behind — the session stops instead of dropping EEG), `writer_error`, `eeg_stalled`
(no EEG chunk for over 2 s while the app still shows the headset as connected — seen on Muse S Athena after the
headset was touched during a break: Bluetooth stays up, samples stop; without this check a session ran 15 minutes
with no EEG). While EEG is silent, contact is reported as *No signal* (the app's buffer still holds old samples that
would look *Good*), **Start** is blocked and the tab says to reconnect the headset; the report warns when the EEG
ends before the stimulation. Only `completed` sessions have `completed: true`; others can still be analysed and are
labelled.

## Session report (`report.html`)

Written automatically when a session ends (and whenever **Analyse session…** runs); **Open report** in the tab opens
it. Self-contained HTML (prints to PDF), in the instruction language chosen in the tab (Vietnamese / English):

1. **Summary** — completed or not, mode, duration, trials, flashes, good epochs, the target − non-target difference in
   the P300 window (250–500 ms) — the mean of per-trial differences over **valid trials** (≥ 50 % of the trial's
   target and of its non-target epochs kept), with its exploratory p — per-trial spread, mean per block, the pooled
   epoch difference (descriptive), a verdict and a warning when the preset's electrodes were not *Good* for more
   than 20 % of the time. Verdict order, fixed before C1: measurement quality first (a failed check → no conclusion
   about a P300), then one primary test (main signal, p < 0.05 and a positive difference).
   - **Measurement quality** — value, threshold and pass / FAIL / not assessed: counts right within ±1 (≥ 80 % of
     trials), contact *Good* per preset channel from `contact.csv` between the first and last flash (≥ 70 %),
     epochs kept per class (≥ 80 %, classes within 10 points), valid trials (≥ 80 %). Operational thresholds, not
     physiological limits.
   - **Attention** (when the count question was asked) — asked, answered, exact, within ±1, and every trial's
     flashes and answer.
2. **Electrodes** — contact at start; share of time Good / Fair / Bad / No signal during the session, median signal
   and 50 Hz noise per channel; a colour strip of the contact over time (sessions recorded before this feature say
   so).
3. **Good epochs** — total, kept and rejected by reason, target / non-target, for the preset signal and each channel.
4. **ERP and P300** — per signal: target and non-target ± standard error and the difference wave, the P300 window
   shaded; table with the target peak in the window (amplitude, latency), mean amplitudes, the difference and the
   exploratory p of a sign-flip test across trials (one target − non-target difference per trial: the trial, not the
   overlapping epoch, is the unit).
5. **Timing deviations** — planned → timer → painted distributions and a histogram, missed / unpainted flashes,
   EEG receive-time statistics, and what is not measured.
6. **Limits and method** — every processing choice, and why the statistics are exploratory (few trials, several
   signals looked at without correction, signal and window not fixed in advance, unmeasured constant delays). The p is
   not evidence for or against a P300. Oscillations in the ERP are listed with their candidate causes (a steady-state
   response to the regular stimulation rate, background EEG, stimulus order, filter / baseline) — none verified.

## Offline tools

```bash
~/.venvs/musemonitor/bin/python extensions/p300_bci/offline.py check  <session>   # completeness, row counts, continuity
~/.venvs/musemonitor/bin/python extensions/p300_bci/offline.py timing <session>   # the timing report, by group
~/.venvs/musemonitor/bin/python extensions/p300_bci/offline.py report <session> --lang vi   # (re)write report.html
~/.venvs/musemonitor/bin/python extensions/p300_bci/offline.py erp    <session> --preset default --csv erp.csv
#   --timeline fit|online   (default fit: whole-session regression)   --channels AF7,AF8   (other channels)
```

## Processing (stated order, every value adjustable in `epochs.py`)

1. Channels by **name** from the device (`app.spec`) — nothing hard-coded to 256 Hz. A preset whose channels the
   device lacks is an error, never silently replaced (use `--channels`).
2. Combine (mean of the preset's channels, or keep each).
3. Band-pass the **continuous** signal, **separately per block** (never across a block boundary). Viewing ERPs uses a
   zero-phase filter; the causal option (state reset at each block, 2 s warm-up) is what an online stage would use.
4. Cut epochs at the onset (`painted_mono`) placed on the EEG timeline; baseline; reject by amplitude.
5. Rejection reasons are counted: `missed` (timer more than half a flash late), `no_paint`, `out_of_range`,
   `uncertain` (timeline flag), `segment_boundary` (timeline rebase), `gap`, `amplitude`.

| Preset | Channels | Band | Epoch | Baseline | Reject | Note |
|---|---|---|---|---|---|---|
| `default` | TP9, TP10 (mean) | 0.5–35 Hz | −0.2 … 0.8 s | −0.2 … 0 s | 80 µV | |
| `li2020` | TP9, TP10 (mean) | 0.5–35 Hz | 0 … 1 s | none | 80 µV | as in the paper, which did not state the unit (µV assumed), filtered after concatenating epochs and cut at **key presses** — we filter first and cut at stimulus onsets |

Grouped averages (for stage B) follow fixed rules: groups of `k` within the same cell and trial, in repetition order;
`R ≥ k` is required; the remainder `R mod k` is dropped and counted; a group with a rejected member is not formed.

## Timing — what is measured and what is not

`timing.json` keeps three groups apart and never adds them into one "uncertainty":

- **measured** — timer lateness (`fired − planned`), paint after fire, paint after plan, missed slots, flashes
  without a paint, EEG hook duration;
- **estimated** — from the EEG receive timestamps: duplicates (several samples of a Bluetooth packet sharing one
  timestamp), steps back, *bursty intervals* (> 3 sample periods: packets arriving in bursts — normal, not data loss),
  *receive pauses* (> 100 ms), timeline flags / segments / rebases, online timeline vs whole-session fit, receive
  scatter, clock steps **during the session**, the measured sampling rate (sample count ÷ session length — a coarse
  check that can hide short losses: "no evidence of loss", not proof of none; receive times cannot show loss), and the app's count of `package_num` steps other than 0/1 with
  its histogram (recorded for later verification; **not** a lost-packet count — Athena's numbering rule is
  unverified);
- **not measured** — the **display latency** (compositor, refresh, pixel response) and the **fixed Bluetooth delay**.
  `display_latency_s` stays `null` until it is measured with an external optical reference (a photodiode on the
  bottom-left corner square, which is white exactly while a cell is lit).

Consequences: onsets are **software estimates** and EEG times are **host-receive estimates**, not scalp sampling
times. A constant unmeasured delay shifts the apparent P300 latency (in the synthetic test a 20 ms Bluetooth delay
plus half a packet moves a +300 ms peak to about +345 ms); varying delay smears the average. Do not quote latencies
to the millisecond.

## Tests

`tests/test_p300_bci.py` (offscreen, synthetic data with a **known** ERP): schedule (seed, balance, one flash per cell
per repetition, no repeats at boundaries, labels, validation); epochs locked to the onset (a 100 ms onset error moves
the peak by 100 ms); other sampling rates and channel names; gaps / uncertain / segment changes rejected; grouped
averaging rules; timing report groups; writer (never overwrites, full queue, writer error, close timeout); the
extension in the app with Athena-like timestamps (12-sample packets sharing one timestamp, 20 ms delay); keys ignored
in EEG-only, recorded in response-assisted; every way of stopping closes the files; the offline CLI.

Synthetic results show the pipeline cuts the right window; **they are not evidence that a P300 can be detected with a
Muse on a person.**

## Checklist with a real Muse S Athena and a real screen

Not tried yet — every item below is open.

- [ ] Fit-test TP9 / TP10 Good; contact recorded in `config.json`.
- [ ] 2 blocks × 5 trials; `offline.py timing`: missed slots, p95 paint after plan, duplicates / gaps, rebases.
- [ ] Repeat with the Signals tab open to see the effect of GUI load.
- [ ] `offline.py check` passes; `erp`: is there a target / non-target difference around 250–500 ms on this person?
      (Do not expect the paper's figure; the Muse electrodes are far from Pz.)
- [ ] Stop / disconnect / close the stimulus window mid-session: files closed, reason recorded.
- [ ] (With a photodiode) measure the display latency; enter it with its method and spread.
- [ ] At least two independent sessions of the same person before stage B is evaluated.

## Limits

- Stage A only: no model, no online decisions, no robot. The command names (Forward, Turn left, Stop, Turn right,
  Backward) are labels for a future simulated command sink.
- Electrode positions of the Muse are far from the usual P300 sites; many people may show no usable P300.
- Timing limits above; one stimulus process and the app share the GUI thread.
