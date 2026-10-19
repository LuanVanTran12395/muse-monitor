# 3D Head Motion Plus

An independent Muse Monitor extension. It adds the **3D head +** tab and leaves the original **3D head** extension unchanged.

## Use

1. Connect Muse S Athena and open **3D head +** on the recording screen.
2. Optional calibration — click the steps or press **1–3** while the tab is open (these keys run the steps here
   instead of marking quick events), or press **▶ Calibrate 1–3** to run them one after another (press it again,
   **■ Cancel**, to stop). Each step counts down "GO in 3… 2… 1…" while you face forward, then a progress bar shows
   the seconds left:
   1. **Hold still** for one second.
   2. **Turn left** once at GO and hold until the end tones. Do not turn back during capture.
   3. **Look up** once at GO and hold until the end tones.
3. Face forward, stay still for about one second, then press **Recenter (R)** (button or the R key). The tab
   refuses recentering during movement.

**Sound cues** (on by default, untick *Sound cues* to silence them; remembered): a short high beep at **GO**, two
rising tones when a capture **ends successfully**, one low tone when the step **must be repeated** — you cannot
watch the screen while your head is turned. The step buttons show **✓** done · **✕** repeat · **●** capturing ·
**…** counting down; a step that cannot run yet is greyed out (its tooltip says why) and the next one is bold.

Each motion calibrates a different IMU axis. If a motion is too small, cancels itself by returning, or overlaps the
other motion's axis, the tab asks you to repeat it. The third axis is inferred so the coordinate system remains
right-handed.

**Reading the head.** The angles describe *your* head: **yaw +** = turned left, **pitch +** = looking up,
**roll +** = tilted to the left. With **Mirror view** ticked (default) the model moves like your reflection — turn
left and it turns to the screen's left; unticked it moves like a person facing you. The line under the head says
when it was last recentered (*manual* or *camera*); after a recenter the model may jump, and "Recentered (…)"
appears on it for two seconds. **IMU:** shows *stable*, *moving*, *no data for over 1 s* or *waiting*; hover it for
the sample count and rate. Orientation is relative; yaw is based on gyroscope integration and drifts until the next
recenter. The display is an estimate of rotation, not head position. No additional package is needed.

## Camera reference (optional)

Tick **Use the computer camera to detect when I face the screen** under the 3D head. The camera is
**off by default** and every time you turn it on the app asks for your permission first; the first
time, macOS also asks to allow camera access for the app that runs Muse Monitor (Terminal or VS Code).
If macOS access was refused, enable it in *System Settings › Privacy & Security › Camera*.

Choose the device in **Camera:**. The Mac's built-in camera is selected by default, even when macOS
offers a nearby iPhone/iPad as Continuity Camera (which it may list first or make the system
default); your choice is remembered and the list updates when devices come and go. Capture uses Qt
Multimedia with that exact device.

While it runs, a red **● Camera on** mark and a small mirrored preview are shown. When your face is
frontal (nose centred between the eyes, eye line level) and the IMU says your head is still for one
second, the model is recentered so that "looking at the screen" is forward. This also removes
gyroscope yaw drift. Untick **Auto-recenter…** (shown while the camera is on) to only show the status. When you
are not facing the screen the status says why, in your own directions: *turned left / right*, *looking up / down*,
*head tilted*, *too far from camera*.

Privacy: frames are analysed in memory about 6 times per second at 320 px width and are never saved
or sent. The camera stops when the box is unticked, the extension is unloaded or the app closes.

Requirements: `opencv-python-headless` (≥ 4.8, for `FaceDetectorYN`) installed in the app's venv:
`~/.venvs/musemonitor/bin/pip install opencv-python-headless`. Face model:
`models/face_detection_yunet_2023mar.onnx` (YuNet, OpenCV Zoo, MIT licence — `models/LICENSE-YuNet`).
Pitch from the camera is coarse; the IMU's gravity reference keeps pitch and roll, while the camera
mainly fixes yaw.
