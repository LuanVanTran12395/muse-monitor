# Eye Interaction (experimental)

Adds an **Eyes (experimental)** panel (HCI/BCI ▸ Eyes) to Muse Monitor for Muse S Athena. The avatar animates brief blinks from large, simultaneous AF7/AF8 ocular artifacts and estimates sustained eye closure from relative 8–13 Hz alpha power at TP9/TP10. Athena does not supply a dedicated EOG channel through this extension; the frontal EEG is an **EOG proxy**.

## Calibrate

Connect Athena, open the tab and keep the headset still. Start each step with its button or by pressing
**1–5** while the tab is open (in this tab these keys run the steps instead of marking quick events; Space
still marks an event), or press **▶ Calibrate 1–3** to run the three required steps one after another
(press it again — it reads **■ Cancel** — to stop). Each step counts down "GO in 3… 2… 1…", then a progress
bar shows the seconds left. Wait for **GO** before changing your eyes.

The step buttons show where you are: **✓** done · **⚠** done, but alpha did not change between open and
closed eyes · **✕** the capture must be repeated · **●** capturing · **…** counting down. A step that cannot
run yet is greyed out (its tooltip says which step comes first) and the next required step is in bold.

**Sound cues** (on by default, untick *Sound cues* to silence them; the choice is remembered): a short high
beep at **GO**, two rising tones when a capture **ends successfully**, one low tone when the step **must be
repeated** (the text says why). In step 2 your eyes are closed: close them at the GO beep and open them at the
end tones. Without sound output the system beep is used.


1. **Eyes open:** look forward with eyes open for five seconds.
2. **Eyes closed:** close your eyes for five seconds. The extension enables long eye closure only if posterior alpha rises clearly above the open baseline.
3. **Blink 3×:** open your eyes, blink three distinct times during four seconds, and avoid head movement. If fewer than two clear peaks are detected, repeat this step.

The avatar stays open until calibration succeeds. Motion reported by the IMU temporarily blocks blink animation and alpha decisions. Calibration resets on disconnect. You can repeat steps at any time.

## Left / right glances (experimental)

A horizontal eye movement changes the two forehead electrodes in **opposite** directions, while a
blink moves both the same way, so AF7 − AF8 (band-passed 0.3–6 Hz) separates glances from blinks.
Polarity depends on the person and the fit, so calibrate once after step 1:

4. **Glance left:** on GO, look to the left edge of the screen with your **eyes only**, hold about
   one second, then look back to the centre.
5. **Glance right:** the same to the right.

After calibration the avatar's pupils follow (with **Mirror view** ticked, the default: you look left →
pupils move to the screen's left; unticked: the avatar looks to its own left, like a person facing you), the **Gaze** readout shows centre / left / right with counts, and the Gaze plot marks each glance.
Only left/right is detected — up/down movements cannot be told apart from blinks with this headset.
A quick look-and-back is supported: the return is accepted 0.12 s after the glance (a repeat glance in
the same direction needs 0.35 s), and a return that coincides with a blink is still detected.
A sustained gaze cannot be held by the band-pass, so the avatar returns to centre after 6 s without a
returning eye movement; the return is still expected for 30 s, so when your eyes do come back it is
counted as "back to centre", not as a glance to the other side. The status line shows
`swing X/Y µV`: the largest AF7 − AF8 swing in the last 2 s versus the calibrated threshold — if a
glance is not detected, its swing stayed below the threshold (repeat steps 4–5 with a wider glance).
Head turns, jaw clenching and poor frontal contact can cause false glances; IMU motion blocks
detection briefly.

## Detection plots

Below the avatar (drag the divider to resize) two small time-domain plots share the app's time axis,
**Time range** and event markers:

- **Blink (EOG µV)** — filtered AF7/AF8 mean (sign flipped so blinks point up), the calibrated blink
  threshold (dashed) and a ▼ marker at every counted blink.
- **Gaze µV** (key in the corner: ↑ your left · ↓ your right) — filtered AF7 − AF8 (horizontal EOG proxy; glances to your left drawn upward, to
  your right downward, whatever the Mirror view setting), the ±
  glance threshold, ◀ at a glance to the left, ▶ to the right and a grey dot when the eyes return
  to centre. Markers sit where the signal crosses the threshold — the moment the app
  reacts (about 50 ms after the eye movement), so the avatar changes at the same time. Each glance has
  two transients: going out (◀/▶) and coming back (grey dot, same direction as the opposite glance).
- **Alpha** — TP9/TP10 8–13 Hz / 4–30 Hz power over a 4 s window, updated about twice per
  second; the dashed line is the open/closed threshold from calibration. A **closed** line marks the
  moment the closure was recognised (two consecutive values above the threshold) and the shaded band
  lasts until reopening is recognised. Because of the 4 s window and two votes, recognition lags the
  real eye closure by a few seconds.

The alpha ratio is shown before calibration too, on a fixed 0–1 axis, but open/closed decisions start
only after step 2 enables them. Detection keeps running while another tab is open.

## Readouts

Above the avatar: **Eyes** (open / closing? / closed / opening?, or why closed-eye detection is off),
**Blinks** (count) and **Gaze** (centre / left / right with counts). Hover them for the numbers behind them:
the alpha ratio and its threshold, the largest recent left/right swing against the glance threshold.

Eye closure comes from alpha over a 4 s window and needs two readings in a row, so it lags the real
closure by a few seconds. After the first reading the avatar half-closes (**closing?**) or half-opens
(**opening?**) and a caption under it says that the state is still being checked.

## Limits

- Alpha does not reliably indicate eye state for every person or recording; the closed state is disabled when calibration cannot separate it from eyes open.
- Forehead muscles, electrode movement, gaze shifts and poor contact can mimic a blink; subtle blinks may be missed.
- The avatar shows a short blink event or a likely sustained closure. It does not measure eyelid opening, gaze, left/right winks, or sleep state.
- No raw EEG is sent outside Muse Monitor by this extension.
