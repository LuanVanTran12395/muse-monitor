# Food order (demo)

Order food with head and eye gestures on Muse S Athena, in a window of its own. Design:
`debate/claude-food-order-extension-proposal.md` (reviewed by Codex).

## Muse Bistro — order with head and eyes

**🍕 Open Muse Bistro** in the tab opens the ordering window (F11 for full screen). It applies the two existing
extensions to a concrete task. Their estimators and rules are **reused read-only** (`_reuse.py` loads their folders;
nothing in them is changed):

- `head_motion_plus`: `PoseTracker`, `axes_from_motions`, `pose_angles`, plus the 3D head shown in the corner.
- `eye_interaction`: `EyeEstimator`, `relative_alpha`, plus the eyes shown in the corner.

1. **Quick calibration** (about 15 s for the head, head_motion_plus rules), with a tone at GO and at each end:
   1. look straight, hold still — 5 s;
   2. turn left and hold — 1.5 s;
   3. look up and hold — 1.5 s;
   4. then hold still to set the centre.

   With the eye shortcuts on, two eye steps follow (about 13 s): blink twice quickly, three times (6 s); close the
   eyes and keep them closed about 6 s, until the end tone (7 s — long enough to see the closing deflection and
   several seconds of a quiet, closed-eye signal).

   A failed step is repeated once, then skipped. **Esc** skips the whole calibration (keyboard / mouse / dwell still
   work). **Calibrate again** in the tab, or **K** in the window, repeats it.
2. **Sign in**: type a customer code + Enter, or pick a recent account / "Khách mới" with the head.
3. **Order**: every screen shows three cards.

**BCI design rules applied**
- **No Midas touch.** Pointing and reading never trigger anything: look at a card as long as you like. Every
  consequential command is a deliberate act — a **nod**.
- **Reliable channels for commands that change things; unreliable channels for nothing that matters.** Head
  movement (IMU) carries pointing, nod and shake. The eye channels are on by default but only open overlays that a shake closes (see below).
- **The cost of an error decides the confirmation.** Adding to the cart needs no popup: a 3 s **shake to undo**
  is enough. Placing the order or deleting a line asks nod / shake, and a 10 s timeout cancels.
- **One meaning per gesture, everywhere.** Nod = choose / yes. Shake = back / undo / no. Action cards (**✓ Xong**,
  **Đặt hàng**) sit in the first card, so every step is the same "point + nod".
- **Visible system state.** The mode, the gestures usable now, the last command understood, and a signal state
  per channel (head, and the eye channels when enabled). The head-direction bar shows where the pointer is.
- **Fallback for everything**: keyboard and mouse.

| To | Gesture | Keyboard / mouse |
|---|---|---|
| Point at card 1 / 2 / 3 | turn the head slightly left / keep centre / slightly right — free, never selects | ← → or 1 2 3 |
| **Choose / yes** | **nod** | Enter / Y, or click the card |
| Next / previous three | **turn fully** right / left and come back | PgDn / PgUp, ] / [ |
| Categories (and Cart, Sign out) | **look up and hold** | ↑ |
| Back · undo the last add (3 s) · cancel | **shake** | N or Backspace |
| Cart | the Cart card (under Categories) | C |
| Recenter the pointer | — | R |

**Eye shortcuts** (on by default; tab check boxes). They read **TP9 / TP10** by default; the tab's *Eyes* list
also offers AF7 / AF8 and AF − TP (a change needs *Calibrate again*). A mistaken detection only shows a panel,
which closes by itself or with a shake:

| Eyes | Effect | Then |
|---|---|---|
| **Blink twice quickly** (your own spacing, set in the calibration), head still | the pointed item opens enlarged with its description, prices per size and extras | **nod** chooses it · **shake** closes it (no time limit) |
| **Close the eyes until the "ting"** (~3 s) | the cart opens over the menu | **nod** orders (popup) · shake or 6 s closes it |

A small eye next to the avatars blinks with every blink seen; while the eyes are closed, a ring and
"nhắm mắt… 1.6 / 3 s" count up to the tone.

**How they are recognised** (`gestures.EyeCommands`): eye_interaction's `EyeEstimator` filter and blink calibration,
plus rules from the 2026-10-19 captures.
- Deliberate blinks are not larger than natural ones, so a command double blink also needs a still head, two blinks
  of similar size at the calibrated spacing, and nothing just before or after.
- Closing the eyes gives one large deflection (its polarity is taken from the calibration), then a quiet signal
  with no blinks, and — when the calibration saw it — more alpha than with the eyes open.

Replayed on the captures (calibration rows to calibrate, test rows to measure; 15 min; closure counted at 2.2 s):

| Source | Double blink found | false / min | Eye closure found | false / min |
|---|---|---|---|---|
| **TP9 / TP10** (default) | **5 / 9** | **0.33** | **4 / 4** | **0.07** |
| AF7 / AF8 | 3 / 9 | 0.60 | 1 / 4 | 2.40 |
| AF − TP | 5 / 9 | 0.40 | 3 / 4 | 0.20 |

Why TP does better: Muse references every channel to Fpz on the forehead, so a blink reaches TP9 / TP10 (inverted)
through the reference; behind the ears, gaze shifts disturb less; and TP carries the eyes-closed alpha, which
gives closure a second check. The fit-test's *Bad* on TP often reflects large amplitudes, not a useless signal.
These are one person's three short sessions — small data. This is why the eyes still only open panels, and never
choose or order anything.

**Language: Tiếng Việt / English.** Every kiosk text (`text.py`) and the menu (`menu.py`: item names,
descriptions, sizes, extras, category names) exist in both languages.
- Each customer's choice is **remembered for their account** and comes back when they sign in.
- Switch with the **VI | EN** switch on the sign-in screen (click), by **looking up** on the sign-in screen (the
  look-up gesture has no other use there), with **L** at any time, or in the tab.
- Cart lines are stored as indices, so the cart, the toasts and the details sheet follow a switch made mid-order.

**Camera: auto-recenter + demo layout** (tab, off by default). This is head_motion_plus's camera reference, reused
read-only:
- YuNet face landmarks on the chosen camera (built-in preferred over an iPhone).
- `FacingGate`: when you **look straight at the screen and hold still for 1 s**, the head pointer is recentered,
  which corrects gyro drift, at most every 5 s. A toast says so.
- It asks for consent each time it is turned on. macOS asks once. Frames are analysed in memory.
- While it runs, the kiosk switches to a **demo layout**: the camera image (mirrored, with the face box and
  "nhìn thẳng màn hình ✓"), the 3D head and the eyes in a right column, the menu on the left.

**Demo video** — a screen video of the kiosk window only (UI, camera image, head, eyes), written to
`data/food_order/demo/muse_bistro_<time>.mp4` (local, git-ignored, 15 frames/s, no sound). It is **not** the app's EEG
recording (● Start recording).
- Start: **🎬 Record demo video** in the tab, or **F9** in the kiosk.
- While it runs, a red label in the kiosk says "● Recording demo video 0:42 · click or F9 to stop", and the label is
  itself the stop button. The tab button reads "■ Stop demo video · 0:42".
- When it stops, the kiosk shows the saved file name. **Open videos folder** opens the folder.

**Item details have no time limit**: read as long as you like. Head turns do not close them; only a **shake** does
(or a nod, which chooses the item).

**Experimental, off by default**: *Hold still selects* (dwell) — it selects whenever someone lingers to read.

Flow:

1. Choose an item.
2. Size S / M / L (pizza, drinks).
3. Toppings or extras: nod toggles one, **✓ Xong** continues.
4. Quantity: nod on − / +, then nod on the middle card to add to the cart.
5. "Đã thêm … · lắc để hoàn tác".
6. Cart: **Đặt hàng** (nod → popup nod / shake, 10 s timeout, **simulated**), or point at a line + nod to change or
   remove it.

After a nod or shake the head has to be quiet for a moment before the next command, so one shake is one "no".
Pointing changes only after the head stays in a zone for 0.2 s. While still near the centre, the yaw is pulled back
slowly to compensate for gyro drift.

Without the two sibling folders, the window says so and works with keyboard and mouse only.

Defaults come from the gesture captures of 2026-10-19 (median peak speeds: point ≈ 65 °/s, full turn ≈ 110,
shake ≈ 150, nod ≈ 93, look-up ≈ 75). They are angles and speeds in `gestures.DEFAULTS`.

## Optional: labelled gesture capture (1–3 minutes)

1. Connect the headset and do the fit-test. All four electrodes are recorded; none may show *No signal*. *Bad*
   is allowed (TP9 / TP10 are often *Bad* and still carry blinks and eye closure well), but better contact gives
   cleaner data.
2. Tick the panel: **Analysis ▸ Other ▸ Food order (demo)**. Set the posture and any notes (glasses, hair, room).
3. Press **▶ Start capture**: the capture window opens on a **sign-in screen**, like signing in to order. Put the
   window in front of the participant (F11 for full screen), type the participant's ID (a code, e.g. `M01`; the
   last one is pre-filled) and press **Enter**. The capture starts at once. If it cannot start yet (no EEG, an
   electrode with *No signal*, invalid code), the screen says why under the field. *Bad* contact does not block.
4. For every step the window shows the gesture (pictogram and large instruction) with **CHUẨN BỊ**, then a high
   **GO** tone with **LÀM NGAY** and a filling ring. Do the gesture **once**, then **VỀ GIỮA · NGHỈ**. For *Nhắm
   mắt*: close your eyes at GO and open them at the second tone (3 s).
5. Keys in the window:
   - **⌫ Backspace**: this repetition was done wrong. Works during it, or until the next GO for the one that just
     finished.
   - **P**: pause after this step. **Space / Enter / click**: continue.
   - At the end: **Space / Enter / click** starts another capture for the same ID; **Esc** closes the window.
   - **Esc twice**: stop.
   - **F**: full screen.
6. **Do not touch the headset** during the capture. If no EEG arrives for 2 s, the capture stops (`eeg_stalled`)
   and keeps the data so far; reconnect the headset and start a new capture.

Sequence (seed drawn at Start, saved), with one participant-paced pause. **Length** in the tab: **~3 min** (default) or **~2 min**.

1. Baseline 15 s (relaxed, natural blinks), then a 10 s slow head sweep left ↔ right (pointing range, gyro drift).
2. **Calibration set**: every gesture once, in a block. Then the screen **"Xong phần hiệu chỉnh"** waits: rest,
   then **Space / Enter / a click** in the window starts the test set (the window takes the keyboard back by itself).
3. **Test set, first half**: every gesture 2× in total (~2 min preset: 1×), random order, never twice in a row.
4. Natural-movement segments, 15 s each, 2 drawn at random (~2 min preset: 1) from: looking around the screen,
   reading aloud (nodding or shaking while talking is fine), glancing while turning, hands near the face.
5. Test set, second half.

Each trial: 1 s get ready → GO → 2–2.5 s to do the gesture (eye closure 4 s) → 1 s back to centre.
**For more data, run several short captures with a break in between.** Each one is its own folder, and they are
pooled for tuning (calibration rows) and measuring (test rows) in F2.

Gestures: point left / right (small turn, hold 2 s), turn fully left / right and back, nod, shake, look up and
hold, double blink, eyes closed 3 s.

## Files

`data/food_order/capture/<YYYYmmdd_HHMMSS>_<subject>/`, git-ignored like the app's recordings:

| File | Content |
|---|---|
| `config.json` | subject, posture, notes, protocol (seed, every step), device, channels, rates, contact at start, versions; at the end `completed`, `stop_reason`, `rows` |
| `eeg.csv`, `imu.csv` | `index, ts_raw_unix, recv_mono`, then the channels (EEG µV; IMU acc_x … gyro_z) |
| `labels.csv` | one row per step: `kind` (baseline / trial / negative), `name`, `set` (calib / test), `rep`, `prompt_mono`, `go_mono`, `go_unix`, `end_mono`, `end_unix`, `bad`, `bad_mono`, `note` |
| `contact.csv` | contact level, signal and 50 Hz RMS per channel every ~2 s (*No signal* while the EEG is silent) |
| `log.txt` | tones, pauses, bad marks, stop |

**Label times are cue times** (GO shown and its tone played), not movement onset. Allow a reaction time when
matching detections. `recv_mono` and the `*_mono` label times share one clock.

## Limits

- The gesture thresholds and the eye-source comparison come from one person's three short capture sessions
  (2026-10-19); other people, fits and postures are not tested.
- Eye shortcuts are imperfect (double blink found about half the time); they only open overlays for that reason.
- Not tried with real users, a screen reader (only `accessibleDescription` is set), or a long session (gyro drift
  relies on the centre pull and the optional camera recenter).
- Synthetic tests cover the order flow, hit boxes, keyboard path, gesture rules, the capture protocol and files.
  They are not evidence about real gestures.
