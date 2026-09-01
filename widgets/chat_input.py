from textual.message import Message
from textual.widgets import TextArea
from textual.suggester import SuggestFromList

import os
import logging


log = logging.getLogger(__name__)


class ChatInput(TextArea):

    MIN_HEIGHT = 3
    MAX_HEIGHT = 8

    class Submitted(Message):
        def __init__(self, text):
            self.text = text
            super().__init__()

    def __init__(self, *args, commands=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.commands = commands or []

        self.input_history = []
        self.history_index = 0


    def on_mount(self):
        self.styles.height = self.MIN_HEIGHT
        self.cursor_location = (0, 0)
        self.scroll_home(animate=False)


    def on_key(self, event):
        if event.key == "tab":
            self.complete_command()
            event.stop()
            return

        if event.key == "ctrl+up":
            self.show_previous_history()
            event.stop()
            return

        if event.key == "ctrl+down":
            self.show_next_history()
            event.stop()
            return

        if event.key == "ctrl+d":
            self.app.action_confirm_quit()
            event.stop()
            return

        if event.key == "enter":
            event.prevent_default()
            text = self.text 
            if text.strip():
                self.input_history.append(text)
                self.history_index = len(self.input_history)

                self.post_message(self.Submitted(text))

                self.text = ""
                self.cursor_location = (0, 0)
                self.styles.height = self.MIN_HEIGHT

                event.stop()
                # log.info("Message Sent... ")
                return

        if event.key == "ctrl+j":
            self.insert("\n")
            event.stop()
            return

    def show_previous_history(self):
        if not self.input_history:
            return

        if self.history_index > 0:
            self.history_index -= 1

        self.text = self.input_history[self.history_index]
        self.call_after_refresh(self.move_cursor_to_end)


    def show_next_history(self):
        if not self.input_history:
            return

        if self.history_index < len(self.input_history) - 1:
            self.history_index += 1
            self.text = self.input_history[self.history_index]
        else:
            self.history_index = len(self.input_history)
            self.text = ""

        # self.cursor_location = (0, len(self.text))
        self.call_after_refresh(self.move_cursor_to_end)


    def move_cursor_to_end(self):
        lines = self.text.split("\n")
        self.cursor_location = (
            len(lines) - 1,
            len(lines[-1])
        )


    def reset_input_position(self):
        self.cursor_location = (0, 0)
        self.scroll_home(animate=False)


    def on_text_area_changed(self, event: TextArea.Changed):
        if event.text_area != self:
            return

        lines = self.text.count("\n") + 1

        new_height = min(max(lines + 2, self.MIN_HEIGHT),self.MAX_HEIGHT)

        self.styles.height = new_height

        # self.call_after_refresh(lambda: self.scroll_end(animate=False))
        if self.text:
            self.call_after_refresh(lambda: self.scroll_end(animate=False))

    def complete_command(self):
        text = self.text

        matches = [
            cmd for cmd in self.commands
            if cmd.startswith(text)
        ]

        if not matches:
            return

        if len(matches) == 1:
            self.text = matches[0]
            self.move_cursor_to_end()
            return

        common = os.path.commonprefix(matches)

        if len(common) > len(text):
            self.text = common
            self.move_cursor_to_end()
        else:
            self.app.query_one("#history").write("  ".join(sorted(matches)))


