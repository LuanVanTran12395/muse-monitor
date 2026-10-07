# 3D Head Motion

This extension adds a **3D head** tab to Muse Monitor. It uses the Athena IMU's accelerometer and gyroscope channels. No extra dependency is needed beyond the app's existing packages.

Start Muse Monitor from this project with `./run.command`, connect Muse S Athena, and open the **3D head** tab on the recording screen. Keep your head still for a moment and click **Recenter head** to make the current pose face forward and estimate gyro offset. Recenter again whenever the view drifts.

The display estimates **relative orientation**. The accelerometer helps stabilize tilt, while yaw comes from integrating the gyroscope and can drift. The Athena sensor axes are mapped to the model using user checks for left/right turns and nodding; exact angles are still estimates. This extension does not modify EEG processing or recordings.
