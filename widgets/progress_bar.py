from textual.widgets import Static


class ProgressBar(Static):
    """Indeterminate progress bar: a filled segment scans back and forth."""

    WIDTH = 30
    SEGMENT = 6

    def __init__(self, *args, label="", **kwargs):
        super().__init__(*args, **kwargs)
        self.label = label
        self._timer = None
        self._pos = 0
        self._direction = 1

    def on_mount(self):
        self.update(self._render_bar())

    def start(self):
        if self._timer is None:
            self._pos = 0
            self._direction = 1
            self._timer = self.set_interval(0.08, self._advance)

    def stop(self):
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _advance(self):
        self._pos += self._direction

        if self._pos <= 0 or self._pos >= self.WIDTH - self.SEGMENT:
            self._direction *= -1
            self._pos = max(0, min(self._pos, self.WIDTH - self.SEGMENT))

        self.update(self._render_bar())

    def _render_bar(self):
        bar = ["░"] * self.WIDTH

        for i in range(self._pos, min(self._pos + self.SEGMENT, self.WIDTH)):
            bar[i] = "▓"

        prefix = f"{self.label} " if self.label else ""
        return f"{prefix}[{''.join(bar)}]"
