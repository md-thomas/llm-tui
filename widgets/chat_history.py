from textual.containers import VerticalScroll
from textual.widgets import Static
from rich.text import Text

class ChatHistory(VerticalScroll):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ai_widget = None
        self.ai_text = ""
        self._segment_text = ""

    def write(self, text):
        self.mount(Static(text, markup=False))
        self.scroll_end(animate=False)

    def clear(self):
        self.remove_children()
        self.ai_widget = None
        self.ai_text = ""
        self._segment_text = ""

    def add_user_message(self, text):
        self.mount(
            Static(
                Text.assemble(
                    ("You >>>>>>>>>>", "bold green"),
                    (f"\n{text}", "italic white"),
                ),
                classes="user-message",
            )
        )
        self.scroll_end(animate=False)

    def add_tool_call(self, name, args, result):
        result = result if len(result) <= 500 else result[:500] + " ... [truncated]"

        self.mount(
            Static(
                Text.assemble(
                    (f"\U0001f527 {name}({args})\n", "bold yellow"),
                    (result, "dim"),
                ),
                classes="tool-call",
            )
        )

        # Force the next append_ai_response to start a fresh widget below
        # this one, so text generated after a tool call doesn't get stuffed
        # into an already-mounted (now out-of-order) widget above it.
        self.ai_widget = None
        self.scroll_end(animate=False)

    def start_ai_response(self):
        self.ai_text = ""
        self._start_ai_segment()

    def _start_ai_segment(self):
        self._segment_text = ""

        self.ai_widget = Static(
            Text.assemble(
                ("AI <<<<<<<<<<", "bold cyan"),
            ),
            classes="ai-response",
        )

        self.mount(self.ai_widget)
        self.scroll_end(animate=False)

    def append_ai_response(self, token):
        if self.ai_widget is None:
            self._start_ai_segment()

        self.ai_text += token
        self._segment_text += token

        self.ai_widget.update(
            Text.assemble(
                ("AI <<<<<<<<<<\n", "bold cyan"),
                (self._segment_text.lstrip(), "white"),
            )
        )
        self.scroll_end(animate=False)

