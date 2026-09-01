from textual.widgets import Static
import logging

log = logging.getLogger(__name__)


class Spinner(Static):

    FRAMES = [
        "⠋",
        "⠙",
        "⠹",
        "⠸",
        "⠰",
        "⠠",
        "⠰",
        "⠸",
        "⠹",
        "⠙",
    ]

    def on_mount(self):
        self.frame = 0
        self._timer = None
        self.update("")

    def start(self):
        if self._timer is None:
            self.frame = 0
            self._timer = self.set_interval(0.1, self.animate)

    def stop(self):
        if self._timer:
            self._timer.stop()
            self._timer = None

        self.update("")

    def animate(self):
        value = self.FRAMES[self.frame]
        self.update(value)
        self.frame = (self.frame + 1) % len(self.FRAMES)