from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ToolConfirmModal(ModalScreen[str]):
    """Dismisses with one of: "allow", "always", "deny"."""

    def __init__(self, name, description, preview=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tool_name = name
        self.description = description
        self.preview = preview

    def compose(self):
        with Vertical(id="tool-confirm"):
            yield Label(f"Allow tool call: {self.tool_name}?")
            yield Static(self.description, id="tool-confirm-description")

            if self.preview:
                with VerticalScroll(id="tool-confirm-preview"):
                    yield Static(self.preview, markup=False)

            yield Static(
                f"\"Always Allow\" skips confirmation for {self.tool_name} "
                "for the rest of this session (see /permissions).",
                id="tool-confirm-hint",
            )

            with Horizontal(id="tool-confirm-buttons"):
                yield Button("Allow", id="allow", variant="success")
                yield Button("Always Allow", id="always", variant="primary")
                yield Button("Deny", id="deny", variant="error")

    def on_button_pressed(self, event):
        self.dismiss(event.button.id)
