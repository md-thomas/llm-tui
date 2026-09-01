from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label, Button 
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual import work
from textual.widgets import Static

from widgets.chat_history import ChatHistory
from widgets.chat_input import ChatInput
from widgets.status_bar import StatusBar
from widgets.tool_confirm import ToolConfirmModal
from llm_client import LLMClient

from commands import CommandProcessor
from config import Config
from version import __version__
from paths import resolve_file
import tools

from rich.text import Text
import json
import logging
import time
import threading

log = logging.getLogger(__name__)


class QuitConfirm(ModalScreen[bool]):
    def compose(self):
        yield Vertical(
            Label("Exit LLM TUI?"),
            Button("Yes", id="yes"),
            Button("No", id="no"),
        )

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "yes")


class LLMApp(App):
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "css/app.tcss"

    BINDINGS = [
        ("ctrl+d", "confirm_quit", "Quit"),
        ("ctrl+l", "clear_history", "Clear"),
        ("ctrl+n", "new_session", "New"),
    ]

    def __init__(self, session_to_load=None):
        super().__init__()

        self.session_to_load = session_to_load
        self.exit_session_name = None

        self.config = Config()
        
        self.llm = LLMClient(self.config)

        self.commands = CommandProcessor(self)

        # runtime state
        self.model = self.config.model
        self.temperature = self.config.temperature
        self.api_base = self.config.api_base
        self.backend = self.config.backend
        self.system_prompt = self._load_system_prompt()
        self.persona = None
        self.context_files = []
        self.max_tokens = self.config.max_tokens
        self.context_window = self.config.context_window
        self.tools_enabled = self.config.tools_enabled
        self.allowed_tools = set()
        self.min_p = None
        self.top_k = None
        self.timeout = self.config.timeout

        # session state
        self.session_start = time.monotonic()
        self.message_count = 0
        self.chat_log = []
        self.is_generating = False
        self.stop_event = threading.Event()


    def _load_system_prompt(self, filename="system_prompt.txt"):
        path = resolve_file(filename, bundled_path=filename)

        try:
            with open(path) as f:
                return f.read().strip()
        except FileNotFoundError:
            return ""


    def on_mount(self):
        history = self.query_one("#history", ChatHistory)
        history.mount(Static(f"💬 Starting interactive Chat v:{__version__}"))
        history.mount(Static("Use: /quit, /exit to exit"))

        if self.session_to_load:
            self.commands.execute(f"/load {self.session_to_load}")
        else:
            autosave = self.commands.autosave_info()
            if autosave:
                count, saved_at = autosave
                history.mount(Static(
                    f"Found an auto-saved session from {saved_at} ({count} messages). "
                    f"Run /load autosave to resume it, or /new to discard it."
                ))

        history.mount(Static("-" * 40))
        self.query_one("#input", ChatInput).focus()


    def on_key(self, event):
         if isinstance(self.focused, ChatHistory):
            if event.character:
                input_box = self.query_one("#input", ChatInput)
                input_box.focus()
                input_box.insert(event.character)
                event.stop()


    def action_confirm_quit(self):
        self.push_screen(QuitConfirm(), self.quit_response)


    def action_clear_history(self):
        self.commands.execute("/clear")


    def action_new_session(self):
        self.commands.execute("/new")


    def quit_response(self, confirmed):
        if confirmed:
            self.exit_session_name = self.commands.save_exit_session()
            self.commands.clear_autosave()
            self.exit()


    def compose(self) -> ComposeResult:
        yield Header()
        yield ChatHistory(id="history")
        yield ChatInput(
            id="input", 
            commands=list(self.commands.commands.keys())
        )
        # yield Footer()
        yield StatusBar()


    def on_chat_input_submitted(self, event: ChatInput.Submitted):
        text = event.text.strip()

        if text.startswith("/"):
            self.commands.execute(text)
            return 

        self.message_count += 1
        self.chat_log.append({"role": "user", "content": text})
        self.commands.autosave()

        history = self.query_one("#history", ChatHistory)
        # history.mount(Static("-" * 40))
        history.add_user_message(text)
        # history.mount(Static("-" * 40))
        history.start_ai_response()
        self.query_one(StatusBar).set_thinking()
        self.stop_event.clear()
        self.is_generating = True
        self.get_llm_response(list(self.chat_log))


    def _build_system_prompt(self):
        if not self.context_files:
            return self.system_prompt

        blocks = [
            f"--- {cf['filename']} ---\n{cf['content']}\n--- end {cf['filename']} ---"
            for cf in self.context_files
        ]

        files_block = (
            "The user has loaded the following files for reference:\n\n"
            + "\n\n".join(blocks)
        )

        if self.system_prompt:
            return f"{self.system_prompt}\n\n{files_block}"

        return files_block


    @work(thread=True)
    def get_llm_response(self, messages):
        status_bar = self.query_one(StatusBar)
        history = self.query_one("#history", ChatHistory)

        try:
            for event in self.llm.chat(
                messages,
                system_prompt=self._build_system_prompt(),
                tools=tools.TOOL_SCHEMAS if self.tools_enabled else None,
                tool_executor=self._execute_tool,
                max_tokens=self.max_tokens,
                min_p=self.min_p,
                top_k=self.top_k,
                timeout=self.timeout,
                stop_event=self.stop_event,
            ):
                if event[0] == "tool_result":
                    _, name, args, result = event
                    self.call_from_thread(history.add_tool_call, name, args, result)
                else:
                    kind, text_piece = event
                    self.call_from_thread(self.on_token, kind, text_piece, status_bar)
        except Exception as e:
            detail = str(e)

            if e.__cause__ and str(e.__cause__) not in detail:
                detail += f" ({e.__cause__})"

            self.call_from_thread(self.append_response, f"\n\n[Error: {detail}]")
            self.chat_log.append({"role": "assistant", "content": history.ai_text})
            self.commands.autosave()
            self.is_generating = False
            self.call_from_thread(status_bar.set_ready, None)
            return

        if self.stop_event.is_set():
            self.call_from_thread(self.append_response, "\n\n[Stopped]")

        self.chat_log.append({"role": "assistant", "content": history.ai_text})
        self.commands.autosave()
        self.is_generating = False
        self.call_from_thread(status_bar.set_ready, self.llm.last_usage)
        self.call_from_thread(self._append_completion_summary, status_bar)


    def on_token(self, kind, text_piece, status_bar):
        if kind == "content":
            self.append_response(text_piece)

        status_bar.increment_tokens()

    def _execute_tool(self, name, arguments_json):
        try:
            args = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as e:
            return f"Error: invalid arguments for {name}: {e}"

        tool_fn = tools.TOOLS.get(name)

        if tool_fn is None:
            return f"Error: unknown tool: {name}"

        if name in tools.MUTATING_TOOLS and name not in self.allowed_tools:
            description, preview = tools.describe_tool_call(name, args)

            if not self._confirm_tool(name, description, preview):
                return "User denied this tool call; no changes were made."

        try:
            return tool_fn(**args)
        except TypeError as e:
            return f"Error: invalid arguments for {name}: {e}"
        except Exception as e:
            return f"Error running {name}: {e}"

    def _confirm_tool(self, name, description, preview):
        done = threading.Event()
        result = {"choice": "deny"}

        def handle_result(choice):
            result["choice"] = choice
            done.set()

        self.call_from_thread(
            self.push_screen, ToolConfirmModal(name, description, preview), handle_result
        )
        done.wait()

        if result["choice"] == "always":
            self.allowed_tools.add(name)

        return result["choice"] in ("allow", "always")


    def append_response(self, token):
        history = self.query_one("#history", ChatHistory)
        history.append_ai_response(token)

    def _append_completion_summary(self, status_bar):
        history = self.query_one("#history", ChatHistory)
        history.write("")
        history.write(status_bar.completion_summary())
        history.write("")



if __name__ == "__main__":
    LLMApp().run()