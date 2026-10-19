"""Sound cues for extensions that guide the user through steps they cannot watch on screen (eyes closed, head
turned away) — used by eye_interaction and head_motion_plus calibration:

    from musemonitor.plugins.cues import Cues
    cues = Cues(folder, enabled=True); cues.play("go")

    go     one short high tone          — start now
    done   two rising tones             — capture finished, open your eyes / carry on
    retry  one long low tone            — capture finished but must be repeated (see the text)

The tones are generated once as small WAV files in the extension's data folder and played with QSoundEffect;
without Qt Multimedia (or if a file cannot be written) the system beep is used instead."""
import tempfile
import wave
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtWidgets

RATE = 44100
TONES = {                       # (frequency Hz, duration s) per tone, silence between tones
    "go": [(1046.5, 0.12)],
    "done": [(659.3, 0.11), (987.8, 0.16)],
    "retry": [(220.0, 0.45)],
}
GAP_S = 0.07


def tone_samples(parts, rate=RATE, gap=GAP_S):
    """16-bit mono samples: sine tones with 8 ms fade in/out (no clicks), separated by ``gap`` seconds."""
    out = []
    for i, (freq, dur) in enumerate(parts):
        t = np.arange(int(rate * dur)) / rate
        y = np.sin(2 * np.pi * freq * t)
        fade = min(len(y) // 2, int(0.008 * rate))
        ramp = np.linspace(0, 1, fade)
        y[:fade] *= ramp; y[len(y) - fade:] *= ramp[::-1]
        out.append(y)
        if i < len(parts) - 1: out.append(np.zeros(int(rate * gap)))
    return (np.concatenate(out) * 0.5 * 32767).astype("<i2")


def write_wav(path, samples, rate=RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(samples.tobytes())


class Cues:
    def __init__(self, folder=None, enabled=True):
        """folder: where the WAV files are generated (default: a temp folder — nothing in the user's data)."""
        folder = folder or Path(tempfile.gettempdir()) / "musemonitor_cues"
        self.enabled = enabled
        self.effects = {}
        self.played = []                      # names played (kept short; lets tests check without audio)
        try:
            from PySide6 import QtMultimedia
        except ImportError:
            return
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        for name, parts in TONES.items():
            path = folder / f"{name}.wav"
            try:
                if not path.exists(): write_wav(path, tone_samples(parts))
            except OSError:
                continue
            fx = QtMultimedia.QSoundEffect()
            fx.setSource(QtCore.QUrl.fromLocalFile(str(path))); fx.setVolume(0.7)
            self.effects[name] = fx                                     # loads in the background

    def play(self, name):
        if not self.enabled: return
        self.played = (self.played + [name])[-20:]
        fx = self.effects.get(name)
        if fx is not None and fx.status() != fx.Status.Error:
            fx.play()
        else:
            QtWidgets.QApplication.beep()
