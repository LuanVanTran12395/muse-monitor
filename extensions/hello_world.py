"""Minimal extension: one .py file, one menu action, listens to events and recording."""
from musemonitor.plugins.api import Extension


class HelloWorld(Extension):
    name = "Hello World"
    category = "Other"           # panels go to Analysis ▸ Other
    version = "1.0.0"
    description = "Minimal example: adds a menu action and logs events / recording to the status bar."
    author = "Muse Monitor"
    supports_review = True          # also runs in review windows (File ▸ Open session); settings stay in memory there

    def activate(self, app):
        self.count = app.setting("greetings", 0, type=int)     # private setting, persisted across runs
        app.add_action("Say hi", self.say_hi)

    def say_hi(self):
        self.count += 1
        self.app.set_setting("greetings", self.count)
        self.app.show_status(f"Hi! (#{self.count}) — streaming: {self.app.is_streaming}")

    def on_event(self, t, label):
        self.app.show_status(f"event “{label}” received")

    def on_recording_started(self, path):
        self.app.show_status(f"recording to {path}")


EXTENSION = HelloWorld
