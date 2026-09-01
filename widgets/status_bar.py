import random
import time
from datetime import datetime
from textual.containers import Horizontal
from textual.widgets import Static
from widgets.spinner import Spinner
import logging

log = logging.getLogger(__name__)

THINKING_SYNONYMS = [
    "Pondering", "Ruminating", "Cogitating", "Contemplating", "Musing",
    "Deliberating", "Reflecting", "Mulling", "Noodling", "Percolating",
    "Processing", "Computing", "Chewing on it", "Considering", "Digesting",
    "Ideating", "Speculating", "Theorizing", "Meditating", "Introspecting",
    "Analyzing", "Evaluating", "Weighing options", "Assessing", "Calculating",
    "Reasoning", "Formulating", "Devising", "Working it out", "Puzzling",
    "Wondering", "Deducing", "Inferring", "Conceptualizing", "Envisioning",
    "Imagining", "Hypothesizing", "Strategizing", "Plotting", "Scheming",
    "Concocting", "Brewing", "Fermenting", "Incubating", "Gestating",
    "Synthesizing", "Distilling", "Crunching numbers", "Number crunching", "Whirring",
    "Buzzing", "Humming", "Churning", "Grinding gears", "Spinning up",
    "Booting up", "Warming up", "Loading", "Rendering", "Compiling",
    "Parsing", "Tokenizing", "Inferencing", "Generating", "Composing",
    "Drafting", "Crafting", "Assembling", "Constructing", "Building",
    "Piecing together", "Working through it", "Sorting it out", "Figuring out", "Untangling",
    "Unpacking", "Dissecting", "Examining", "Scrutinizing", "Inspecting",
    "Probing", "Exploring", "Investigating", "Researching", "Studying",
    "Reviewing", "Perusing", "Combing through", "Sifting through", "Rifling through",
    "Searching", "Seeking answers", "Hunting for answers", "Foraging", "Excavating",
    "Mining data", "Extracting insight", "Deriving", "Concluding", "Discerning",
]


class StatusBar(Horizontal):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thinking_timer = None
        self._elapsed_timer = None
        self._token_count = 0
        self._elapsed = None
        self._start_time = None
        self._context_pct = None

    def compose(self):
        yield Spinner(id="spinner")
        yield Static("Ready", id="status")
        yield Static(f"Temperature: {self.app.temperature}", id="stats")
        yield Static(self.app.model, id="model")

    def set_model(self, model):
        self.query_one("#model", Static).update(model)

    def reset_context(self):
        self._context_pct = None
        self._refresh_stats()

    @property
    def context_pct(self):
        return self._context_pct

    def set_thinking(self):
        self._token_count = 0
        self._elapsed = 0.0
        self._start_time = time.monotonic()
        self._cycle_word()
        self._thinking_timer = self.set_interval(1.2, self._cycle_word)
        self._elapsed_timer = self.set_interval(0.1, self._tick_elapsed)
        self._refresh_stats()
        self.query_one("#spinner", Spinner).start()

    def _cycle_word(self):
        self.query_one("#status", Static).update(random.choice(THINKING_SYNONYMS))

    def _tick_elapsed(self):
        self._elapsed = time.monotonic() - self._start_time
        self._refresh_stats()

    def increment_tokens(self):
        self._token_count += 1
        self._refresh_stats()

    def _refresh_stats(self):
        text = f"Temperature: {self.app.temperature}"

        if self._token_count:
            text += f" | Tokens: {self._token_count}"

        if self._elapsed is not None:
            text += f" | {self._elapsed:.2f}s"

        if self._context_pct is not None:
            text += f" | Ctx: {self._context_pct:.0f}%"

        self.query_one("#stats", Static).update(text)

    def set_ready(self, usage=None):
        if self._thinking_timer:
            self._thinking_timer.stop()
            self._thinking_timer = None

        if self._elapsed_timer:
            self._elapsed_timer.stop()
            self._elapsed_timer = None

        if self._start_time is not None:
            self._elapsed = time.monotonic() - self._start_time

        if usage:
            self._token_count = usage.completion_tokens

            context_window = getattr(self.app, "context_window", None)
            if context_window:
                self._context_pct = min(usage.total_tokens / context_window * 100, 100)

        self._refresh_stats()
        self.query_one("#status", Static).update("Ready")
        self.query_one("#spinner", Spinner).stop()

    def completion_summary(self):
        elapsed = round(self._elapsed) if self._elapsed is not None else 0
        tokens_part = f" · {self._token_count} tokens" if self._token_count else ""
        done_at = datetime.now().strftime("%-I:%M %p")
        return f"✻ Churned for {elapsed}s{tokens_part} · done {done_at}"
