# 3D Head Motion Plus

An independent Muse Monitor extension. It adds the **3D head +** tab and leaves the original **3D head** extension unchanged.

## Use

1. Connect Muse S Athena and open **3D head +** on the recording screen.
2. For guided axis calibration, click **1 · Hold still**. Wait for **GO** and remain still for one second.
3. Face forward. Click **2 · Turn left**. Wait for **GO**, turn left once and hold until capture finishes. Do not turn back during capture.
4. Face forward. Click **3 · Look up**. Wait for **GO**, look up once and hold until capture finishes.
5. Face forward, stay still for about one second, then click **Recenter head**. The tab refuses recentering during movement.

Each motion calibrates a different IMU axis. If a motion is too small, cancels itself by returning, or overlaps the other motion's axis, the tab asks you to repeat it. The third axis is inferred so the coordinate system remains right-handed.

The status line shows whether IMU data is arriving and whether the head is stable or moving. Orientation is relative; yaw is based on gyroscope integration and can drift. The display is an estimate of rotation, not head position. No additional package is needed.

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
gyroscope yaw drift. Untick **Auto-recenter…** to only show the status.

Privacy: frames are analysed in memory about 6 times per second at 320 px width and are never saved
or sent. The camera stops when the box is unticked, the extension is unloaded or the app closes.

Requirements: `opencv-python-headless` (≥ 4.8, for `FaceDetectorYN`) installed in the app's venv:
`~/.venvs/musemonitor/bin/pip install opencv-python-headless`. Face model:
`models/face_detection_yunet_2023mar.onnx` (YuNet, OpenCV Zoo, MIT licence — `models/LICENSE-YuNet`).
Pitch from the camera is coarse; the IMU's gravity reference keeps pitch and roll, while the camera
mainly fixes yaw.
