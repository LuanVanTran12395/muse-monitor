import csv

from .recording import companion_path


class EventWriter:
    """Writes manual events to ``<recording>_events.csv`` (unix timestamp, label), flushing every line."""
    def __init__(self, recording_path):
        self.path = companion_path(recording_path, "events")
        self.f = open(self.path, "w", newline="")
        self.w = csv.writer(self.f); self.w.writerow(["timestamp", "label"])

    def write(self, t, label):
        self.w.writerow([f"{t:.6f}", label]); self.f.flush()

    def close(self):
        self.f.close()
