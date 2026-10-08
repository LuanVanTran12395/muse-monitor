# Artifact Log

Marks the parts of a recording that are not clean brain signal, and shows each mark **behind the signal
it was found in**, so you can check it. Every rule is explicit; every threshold is a setting.

| Kind | Rule | Marks | Default |
|---|---|---|---|
| `blink` | a **peak** in the mean of the frontal pair (AF7/AF8, AF3/AF4, Fp1/Fp2) filtered 0.5–6 Hz: prominence ≥ `blink_uv`, width at half height `blink_min_s`…`blink_max_s`, and **both** frontal channels deflected the same way (each ≥ `blink_pair_frac` × `blink_uv`). Either polarity | the blink itself (≈ 1.5× its half-height width), on both frontal channels | 100 µV · 0.08–0.5 s · 0.4 |
| `emg` | RMS in 30–45 Hz (muscle: jaw clench, frowning) | the 1 s epoch, per channel | 8 µV |
| `amplitude` | peak-to-peak in 1–40 Hz; frontal channels skipped in an epoch that holds a blink | the epoch, per channel | 250 µV |
| `flat` | standard deviation of the raw signal | the epoch, per channel | 1 µV |
| `motion` | peak gyroscope magnitude | the epoch, `head` row (needs an IMU) | 30 °/s |

Not blinks, by construction: a **glance** (AF7 and AF8 move in opposite directions, so their mean stays
small), a **slow drift** (wider than `blink_max_s`), a deflection on **one side only**.

Each 1 s epoch is analysed when the next second has arrived, so the zero-phase filters have data on both
sides of it. Marks therefore appear about 1 s late; nothing is lost at epoch boundaries (a blink belongs
to the epoch that holds its peak).

**Tab "Artifacts"** (Analysis ▸ Data quality):

- Upper plot — one row per channel: the EEG as shown on the Signals tab (fixed ±200 µV per row), with a
  light shading behind it where that channel has an artifact and coloured lanes (one per kind) under it.
  The `head` row shows the gyroscope magnitude relative to `motion_dps`.
- Lower plot — the **blink detector**: the exact signal the blink rule uses, the ±`blink_uv` threshold
  lines, and ▼ on each accepted blink. A peak above the line without ▼ was rejected by the width or
  both-sides rule.

**While recording** — `<recording>_artifacts.csv`:

```
timestamp_start,duration_s,channel,kind,value,threshold,unit
1791428361.284000,0.212,AF7,blink,146.572,100,µV
1791428373.004000,1.000,TP9,emg,12.410,8,µV rms
```

**Review windows** — supported: the recording is replayed, the tab follows the scrollbar, the summary
covers the whole recording. Nothing is written in review.

**Thresholds** are starting points, not validated on many recordings. Change them with the extension
settings (`extensions/artifact_log/<key>` in the app's QSettings): `blink_uv`, `blink_min_s`,
`blink_max_s`, `blink_pair_frac`, `emg_uv`, `amplitude_uv`, `flat_uv`, `motion_dps`.
