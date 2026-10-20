# Muse Cube

A Rubik's cube game (2×2 by default, 3×3) in a window of its own, played **with the head on Muse S Athena** (R2) or
with keyboard and mouse (R1). Eye shortcuts come in R3. Design: `debate/claude-rubik-game-proposal.md`, kept local.

Open it from **Analysis ▸ Other ▸ Muse Cube** → **🧊 Open Muse Cube**. Without a headset, keyboard and mouse do
everything.

## Tutorial (before the real game)

The first time the window opens, an 8-step tutorial runs before the real game. A card above the cube says what to do,
in head terms when the IMU is live, otherwise in keys / mouse terms. Each step waits until it is done, then shows
"✓ Tốt lắm!":

1. pick the right face (point right · click it);
2. choose the layer behind it (nod · click again / Tab / Next layer);
3. turn it (tilt · ↺ ↻ / U D L R F B; with tilt off, the buttons);
4. undo (shake · ⌫);
5. turn the whole cube (full turn and back · arrows);
6. solve a cube scrambled by 1 move;
7. solve one scrambled by 2 moves;
8. ready → the real game (nod · Enter · *Start the game*).

Steps 1–5 use an unscrambled practice cube that never counts as solved, so any move can be tried and undone. Space
(new game) is ignored during the tutorial. Size and scramble changes in the tab apply to the real game that follows.
**Esc** or *Skip* goes straight to the real game; **F1** or the tab's *Tutorial* button replays it. Once done or
skipped, it is not shown again by itself.

## The window

- A perspective cube, seen from above at an angle: front red, right blue, top white (back orange, left green, bottom
  yellow).
- **Glass** (default): clear cubies with a light rim. The stickers of the hidden faces show through, fainter, so the
  back can be read without turning the cube. **Classic**: grey cubies, hidden faces hidden. Switch them top right
  (or **G**).
- Top left: **● CHƯA GIẢI / ● ĐÃ GIẢI** (UNSOLVED / SOLVED).
- Bottom dock: size and scramble, moves, clock, and the keys.
- **Right: the 2D panel** (**P** shows / hides it; hidden below 1100 px wide). It follows the 3D cube as it is held
  now: the stickers, the selected layer (blue), the hint (amber), and the turn animation. Two views, switched in the
  panel:
  - **Ba cụm vòng / Three rings.** Each axis is a cluster of concentric rings, one per layer: top **U · E · D**,
    right **R · M · L**, left **F · S · B** (outer U, R, F; inner D, L, B). Each sticker is a ball where two rings
    of the other two axes cross. U, R and F stickers sit next to their own cluster, D, L and B across. Turning a
    layer moves the balls on its ring along it. The ring buttons (**X** clockwise, **X′** counter-clockwise) turn
    that layer, and so does a click on the ring itself (Shift = counter-clockwise).
  - **Chữ thập / Cross.** The six faces unfolded: U on top, L · F · R · B, D below. A click on a sticker selects its
    face.

## Controls

| Action | Keys | Mouse |
|---|---|---|
| Turn the face showing at the top / bottom / left / right / front / back | **U D L R F B** (clockwise as you look at it; **Shift** = counter-clockwise) | click a face, then **↺ / ↻** |
| Choose the layer behind the selected face: outer → middle (3×3) → opposite → outer | **Tab** | click the same face again, or **Lớp kế ▸** |
| Turn a 3×3 middle slice | **M E S** (as L, D, F; Shift = counter) | select the face, choose the middle layer, ↺ / ↻ |
| Turn the whole cube (to look at another face) | **← → ↑ ↓** | — (dragging only tilts the look a little) |
| Undo | **⌫** | — |
| Way back (hint) | **H** | — |
| New game (random scramble, the chosen scramble length) | **Space** (mid-game: press twice, as the button) | **⇄ Trộn ngẫu nhiên**, top right of the cube area: one click once solved (it lights up) or before the first move; mid-game a second click within 3 s ("Bấm lại để trộn"), so a stray click never throws a game away |
| Glass / Classic · Language | **G** · **N** | the switch |
| Full screen | **F11** | double-click empty space resets the look |

## Head control (R2)

Connect the headset and open the window, in either order: a **15–25 s calibration** starts by itself once, on the
first IMU data (or **K** / *Calibrate head* in the tab).

1. look straight, head still (4 s; also eyes open and the jaw at rest);
2. turn left and hold (1.5 s);
3. look up and hold (1.5 s) — these set head_motion_plus's axes;
4. tilt right, right ear towards the shoulder, and hold (1.5 s) — the tilt direction and size;
5. look straight at the cube (1.5 s) → recenter;
6. with blink / jaw turns on: blink twice quickly ×3 (6 s);
7. clench the jaw ~1 s ×2 (3 s).

Each step shows, on a card over the cube:
- **an animated pictogram**: a head on shoulders, seen as in a mirror (your left is on the left). While getting ready
  it demonstrates the movement in a loop; during "now" it shows the pose to hold. Blinks and clenches keep looping;
  an arrow or mark shows the movement;
- **what exactly to do**: the direction and rough size (e.g. 30–45° to your left), how long to hold, what to avoid
  ("turn the neck only, shoulders still, no tilt"), and what the step is for;
- the phase ("GET READY — watch", "NOW — hold until the bar is full", "✓ Done") and the time bar;
- when a step must be repeated, the reason in words ("the movement was too small — make it larger").

The tilt test uses the same pictograms for its prompts.

A step that fails is repeated once, then skipped. **Esc** skips. **Home** recenters at any time.

| Head | Command |
|---|---|
| point **left / centre / right** (yaw zones, 0.2 s settle) | select the **front / top / right** face (as they sit on the screen), its outer layer |
| **nod** | the next layer behind it: outer → middle (3×3) → opposite → outer — every layer is reachable without flipping the cube |
| **tilt right / left** from a steady head, held 0.4 s, then back level | turn the selected layer **↻ / ↺**, as seen from its face (a bar shows the hold) |
| **blink twice quickly** (EEG), head still | turn the selected layer **↻** |
| **clench the jaw** (EEG), head still | turn the selected layer **↺** |
| **full turn** right / left and back | turn the whole cube (view only): the right / left face comes to the front |
| **look up and hold** 0.7 s | turn the whole cube (view only): the bottom comes to the front (as ↑) |
| **shake** | undo |
| **nod**, once solved | new game |

**Blink ×2 ↻ / jaw clench ↺** (tab check box *Blink ×2 ↻ · jaw clench ↺*, on by default) turn the selected layer
without tilting:
- They act **only with a layer selected**. Without one, the window says "Select a layer first".
- They need a still head: head movement and neck muscles would fake them.
- The double blink is food_order's `EyeCommands` rule: two blinks at your own spacing, isolated, similar size. It
  reads TP9 / TP10 by default.
- The clench is artifact_log's EMG band (RMS 30–45 Hz, below the 50 Hz mains), made fast: a causal filter and a
  0.2 s window instead of 1 s epochs, held 0.25 s. One clench = one turn. It reads TP9 / TP10, over the temporal
  muscles.
- Both are calibrated in two extra steps after the head steps: blink twice quickly ×3 (6 s); clench ~1 s ×2 (3 s),
  measured against the jaw at rest during the still step. A step that fails leaves that control off.
- A stray blink or clench is a move, which a shake undoes. The cost of the error is low, so there is no
  confirmation.
- They work whether or not tilt passed its test. With tilt off, the ↺ ↻ buttons still show.
- Not tried on a person yet. On the 2026-10-19 captures, a false double blink came about every 3 minutes (0.33 per
  minute).

**Live EOG / EMG, thresholds and filters by hand.** The tab's *EOG / EMG* panel shows what the two detectors hear,
over the last 6 s:
- **EOG**: the blink channel after its band-pass (TP9 / TP10 by default, blink polarity up), the blink threshold as a
  dashed line, single blinks ▲, and recognised double blinks ★ on the pair's second blink;
- **EMG**: the jaw RMS in its band, the threshold, and recognised clenches ★.

Under each plot:
- the **threshold** (type a value, or drag the dashed line). Lower it when a deliberate blink / clench stays under the
  line; raise it when something else crosses it. A threshold set by hand works even without the calibration;
- **Calibrated value** goes back to what the calibration chose;
- the **filter band**: EOG default 0.8–8 Hz (eye_interaction's band-pass, replaced on the game's own estimator only),
  EMG default 30–45 Hz. Change it to make the signal stand out, e.g. EOG 0.5–5 Hz for slow, large blinks, or EMG
  55–100 Hz if the 30–45 Hz band is noisy (avoid 50 Hz). The bands are remembered. Thresholds were measured in the old
  band: re-calibrate or adjust them.

The game window shows the same two traces small (last 3 s, with the threshold), under the 3D head, while EEG
arrives.

**Camera recenter, 3D head only** (tab: *📷 Camera recenter*, off by default, asks every time). This is
head_motion_plus's camera reference (`CameraController`, `FacingGate`). When you look straight at the screen and hold
still for 1 s, the head pointer is recentered (gyro drift), at most every 5 s, never during calibration or the tilt
test.
- Only the *facing* result is used. The preview signal is not even connected, so **no camera image is shown or
  saved**.
- The window shows head_motion_plus's **3D head model** (`HeadCanvas`) top left. It follows the IMU pose, with a
  caption saying what the camera sees in words ("nhìn thẳng ✓", "đang quay trái"…) and when it last recentered.

Rules against mistakes:
- Pointing never acts.
- A tilt needs a steady head first, a held roll and an unchanged yaw (a shake also rolls, but with a large yaw
  swing). One tilt = one turn.
- From the start of a tilt until the head is level again, pointing, nod, shake and full turn are ignored, so the face
  turned is the one selected when the tilt began.
- No tilt while the head gestures are locked (just after a nod or shake).
- Every move is shown for its full animation. A move that arrives meanwhile waits its turn (at most 3 wait; more are
  dropped), so moves recognised in a row are never cut short.
- While the calibration or the tilt test is on screen, the game is locked: keys, clicks and gestures do not change
  the cube. Only Esc (skip) passes.

**Pointing differs from the first design**: up = top was replaced by centre = top, so pointing never competes with
the look-up hold. The three yaw zones are the food_order card zones.

**The tilt threshold is not settled.** It is 15° by default, then 60% of the calibrated tilt (at least 10°). The
**tilt test** (**T** or the tab button, about 2 min) decides whether the tilt control stays:
- 32 prompts of 4 s in a random order: tilt right ×10, tilt left ×10, and pointing / nodding / centring ×12, during
  which any tilt counts as **false**;
- a tilt prompt counts only when **exactly one tilt on the asked side** was seen (a wrong side or a repeat is a miss);
- a tilt is scored at the prompt shown **when it began**, not when it was recognised (up to ~0.4 s later), so a tilt
  started at the end of a prompt is never scored as false in the next one;
- pass: **≥ 8/10 on each side, no false tilt and no wrong-side tilt**;
- the result shows in the tab and is remembered.

**The test decides.** Before any test, tilt is on provisionally (the tab says so). A failed test **switches tilt
off**: the window then shows the **↺ / Lớp kế / ↻ buttons** under the selected layer even in head mode (pointing and
nod still select), keys work too, and the tab's tilt check box is disabled. A passed retry switches it
back on. During a retry, tilts are still detected for scoring, but they turn nothing.

If the tilt control does not pass, it is redesigned as two-way buttons on screen (not "nod three times").

**Where the gestures come from** (`adapter.py`, the only module that loads other extensions, read-only):
head_motion_plus (`PoseTracker`, `axes_from_motions`, `pose_angles` with roll) and `food_order/gestures.py`
(`HeadGestures`: zones, full turn, look-up hold, nod, shake, drift pull). Each capability is checked on its own. A
missing or changed one switches off only that control, with its reason in the tab, and the keyboard game always
works.

**The selected layer is easy to see**: its cubies are outlined in blue (body and stickers), the rest of the cube is
dimmed, and a badge names it ("lớp giữa (song song mặt phải)") with one bar per layer, the chosen one lit.

## How it stays right

- Moves are stored in standard notation: an outer layer as its face (R, U′…), the opposite layer as that face's own
  move, a 3×3 middle slice as M / E / S.
- The model (`cube.py`) knows only **logical** faces. A cube of size n has **6 × n² stickers** (24 for 2×2, 54 for
  3×3).
- Turning the whole cube changes only the **view**. Keys name the face on the **screen**, and the view maps it to the
  logical face. History, undo and the hint are stored in logical faces, so they stay right after any view change.
- The **hint is the way back to the start**: the inverse of the scramble plus your moves, with cancelling turns
  merged. It always solves, but it is **not** the shortest solution and can be long.
- A game in which the hint was shown is marked **with hints**. It will be kept apart from games solved alone (R4
  ranks only the latter).

## Files

| File | Role |
|---|---|
| `cube.py` | model (N×N, logical faces), view, seeded scramble without same-axis repeats, way back; Qt-free |
| `game.py` | one game: commands in screen terms, clock (starts on the first turn), result, hinted flag; Qt-free |
| `board.py` | the window: QPainter perspective, Glass / Classic, turn and view animations, paint-time hit boxes, dock, the 2D panel |
| `flat.py` | geometry of the 2D views (ring clusters, cross net); Qt-free |
| `adapter.py` | loads and checks the reused estimators; capabilities `head`, `tilt` |
| `tilt.py` | the tilt detector and the tilt test; Qt-free |
| `jaw.py` | the jaw-clench detector (30–45 Hz EMG, fast); Qt-free |
| `pictos.py` | animated pictograms of the calibration / tilt-test movements (QPainter) |
| `signals.py` | the tab's live EOG / EMG plots, thresholds and filter bands by hand (pyqtgraph) |
| `controller.py` | calibration, gestures → window commands, the tilt test run |
| `tutorial.py` | the tutorial steps and their checks; Qt-free |
| `text.py` | Vietnamese / English texts |
| `__init__.py` | the tab (size, scramble, style, language — remembered) and the extension |

## Next stages

- **R3**: eye shortcuts (double blink → hint, eyes closed → flat map of the six faces), camera recenter, demo video.
- **R4**: levels, 3×3, daily challenge, scores (solved alone and with hints kept apart).

## Limits

- Offscreen tests and screenshots only. Not tried on a real screen with users, nor on Muse S Athena.
- The head tests use synthetic IMU through the real calibration and PoseTracker. They show the algorithm works as
  described, not that people can tilt reliably. The tilt test on a person decides that.
- The hint is not a solver. It can only walk back the scramble.
