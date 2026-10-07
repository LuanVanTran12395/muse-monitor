from PySide6 import QtWidgets


class BaseTab(QtWidgets.QWidget):
    """Common interface of a tab on the Recording screen.

    New tab: subclass this, override the hooks you need, then add it to
    ``RecordingPage.TAB_CLASSES`` (built-in tab) or call ``app.add_tab`` from an extension.
    ``on_frame``/``on_analysis`` are only called while the tab is visible, so heavy tabs cost no
    CPU when hidden."""
    title = "Tab"
    owner = None           # id of the owning extension (None = built-in tab)
    failed = False         # extension tab raised → stop calling its hooks

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def on_frame(self):            # every config.REDRAW_MS
        pass

    def on_analysis(self):         # every config.ANALYSIS_MS, and right when the tab is selected
        pass

    def update_texts(self):        # every config.TEXT_MS (even when hidden)
        pass

    def on_view_changed(self):     # time range / filters just changed
        pass

    def apply_theme(self, th):     # the tab's own curve colours (background/axes handled by PlotRegistry)
        pass

    def clear(self):               # clear displayed data on reconnect
        pass
