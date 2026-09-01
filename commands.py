# from widgets.chat_history import ChatHistory
from config import Config
from version import __version__
from paths import search_dirs, resolve_file, user_dir
from widgets.status_bar import StatusBar
import tools
import time
import os
import re
import json
import yaml
import shutil
import subprocess
import difflib
from datetime import datetime

SESSIONS_DIR = os.path.join(user_dir(), "sessions")
PERSONAS_DIR = "personas"
AUTOSAVE_NAME = "autosave"

TREE_IGNORE = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
}
TREE_MAX_DEPTH = 3
TREE_MAX_ENTRIES = 50
GREP_MAX_MATCHES = 50
GREP_FLAGS = {"-i", "-v", "-w", "-c", "-l"}
LS_FLAGS = {"-a", "-l", "-r", "-t"}
TREE_FLAGS = {"-a", "-d"}
TREE_VALUE_FLAGS = {"-L"}

# Settable /config keys, in display order. api_key is deliberately excluded:
# it's env-var-derived (OPENAI_API_KEY) and read-only, so it has no setter.
CONFIG_KEYS = ["backend", "api_base", "timeout", "model", "temperature", "max_tokens", "context_window", "tools_enabled"]

class CommandProcessor:

    def __init__(self, app):
        self.app = app

        self.commands = {
            "/quit": (self.cmd_quit, "Exit the Application"),
            "/exit": (self.cmd_quit, "Exit the Application"),
            "/clear": (self.cmd_clear, "Clear the Display Window"),
            "/compact": (self.cmd_compact, "Summarize and compact the conversation history: /compact [focus instructions]"),
            "/help": (self.cmd_help, "Show detailed help and keybindings"),
            "/commands": (self.cmd_commands, "List all available commands"),
            "/backend": (self.cmd_backend, "Get backend info"),
            "/config": (self.cmd_config, "Show the config"),
            "/context": (self.cmd_context, "Show context-window usage as a bar"),
            "/cat": (self.cmd_cat, "Display a file's contents"),
            "/edit": (self.cmd_edit, "Edit a file: /edit <path> <old text> -> <new text>"),
            "/grep": (self.cmd_grep, "Search file contents: /grep [-i] [-v] [-w] [-c] [-l] <pattern> [path]"),
            "/delete": (self.cmd_delete, "Delete a saved session"),
            "/history": (self.cmd_history, "Show messages from the current session"),
            "/list": (self.cmd_list, "List sessions"),
            "/ls": (self.cmd_ls, "List a directory's contents: /ls [-a] [-l] [-r] [-t] [path]"),
            "/load": (self.cmd_load, "Load a session"),
            "/model": (self.cmd_model, "Get or Set the current model"),
            "/models": (self.cmd_models, "Get a list of models"),
            "/max_tokens": (self.cmd_max_tokens, "Get or Set max_tokens"),
            "/min_p": (self.cmd_min_p, "Get or Set min_p"),
            "/new": (self.cmd_new, "Start new session"),
            "/persona": (self.cmd_persona, "Get or switch personas"),
            "/personas": (self.cmd_personas, "Get a list of personas"),
            "/read": (self.cmd_read, "Read one or more files into the LLM context: /read <file> [file...] | /read | /read clear"),
            "/tree": (self.cmd_tree, "Show a directory tree: /tree [-a] [-d] [-L depth] [path]"),
            "/reload": (self.cmd_reload, "Update runtime with config settings"),
            "/save": (self.cmd_save, "Save a session"),
            "/session": (self.cmd_session, "Show session info"),
            "/permissions": (self.cmd_permissions, "Show or revoke always-allowed tools"),
            "/stop": (self.cmd_stop, "Stop the in-progress response"),
            "/show": (self.cmd_show, "Show messages from a saved session"),
            "/system_prompt": (self.cmd_system_prompt, "Get or Set the SystemPrompt"),
            "/temperature": (self.cmd_temperature, "Get or Set the temperature"),
            "/timeout": (self.cmd_timeout, "Get or Set timeout"),
            "/top_k": (self.cmd_top_k, "Get or Set top_k"),
            "/provider": (self.cmd_provider, "Get provider info"),
            "/write": (self.cmd_write, "Write the last AI response to a file: /write <path> or /write code <path>"),
            "/diff": (self.cmd_diff, "Preview what /write code <path> would change, without writing anything"),
            "/version": (self.cmd_version, "Show app version"),
        }

    def execute(self, text):
        parts = text.split()
        if not parts:
            return False

        command = parts[0].lower()

        if command == "/edit":
            raw = text[len(parts[0]):].strip()
            return self.cmd_edit(raw)

        args = parts[1:]

        command_info = self.commands.get(command)

        if command_info:
            handler, _ = command_info
            return handler(args)

        self.history.write(f"\nUnknown command: {command}\n")
        return False

    @property
    def history(self):
        return self.app.query_one("#history")

    def _set_model(self, name):
        self.app.model = name
        self.app.llm.model = name
        self.app.query_one(StatusBar).set_model(name)

    def _set_temperature(self, value):
        self.app.temperature = value
        self.app.llm.temperature = value

    def cmd_help(self, args):
        path = resolve_file("help.txt", bundled_path="help.txt")

        try:
            with open(path) as f:
                content = f.read()
        except FileNotFoundError:
            self.history.write("help.txt not found.\n")
            return True

        self.history.write(content)
        return True

    def cmd_commands(self, args):
        self.history.write("Available commands...")
        for command, (_, description) in sorted(self.commands.items()):
            self.history.write(f"{command:<15} {description}")
        self.history.write("")
        return True

    def cmd_clear(self, args):
        self.history.clear()
        return True

    def cmd_new(self, args):
        self.history.clear()
        self.app.chat_log = []
        self.app.message_count = 0
        self.app.session_start = time.monotonic()
        self.clear_autosave()
        self.app.query_one(StatusBar).reset_context()
        self.history.write("Started a new session.\n")
        return True

    def cmd_compact(self, args):
        if not self.app.chat_log:
            self.history.write("Nothing to compact.\n")
            return True

        self.history.write("Compacting conversation history...")
        self.app.query_one(StatusBar).set_thinking()
        focus = " ".join(args)
        self.app.run_worker(lambda: self._do_compact(focus), thread=True)
        return True

    def _do_compact(self, focus):
        status_bar = self.app.query_one(StatusBar)

        transcript = "\n\n".join(
            f"{entry['role'].capitalize()}: {entry['content']}"
            for entry in self.app.chat_log
        )

        instructions = (
            "Summarize the conversation below concisely, preserving important facts, "
            "decisions, and any context needed to continue it. Write the summary as "
            "plain prose or a short bullet list."
        )

        if focus:
            instructions += f" Focus especially on: {focus}"

        prompt = f"{instructions}\n\n{transcript}"
        original_count = len(self.app.chat_log)
        summary = ""

        try:
            for event in self.app.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=self.app.max_tokens,
                timeout=self.app.timeout,
            ):
                if event[0] == "content":
                    summary += event[1]
        except Exception as e:
            self.app.call_from_thread(self.history.write, f"Error compacting history: {e}\n")
            self.app.call_from_thread(status_bar.set_ready, None)
            return

        summary = summary.strip()

        if not summary:
            self.app.call_from_thread(
                self.history.write,
                "Compaction produced an empty summary; history left unchanged.\n",
            )
            self.app.call_from_thread(status_bar.set_ready, None)
            return

        self.app.chat_log = [{"role": "assistant", "content": summary}]
        self.autosave()

        def apply():
            self.history.clear()
            status_bar.reset_context()
            status_bar.set_ready(None)
            self.history.write(f"Compacted {original_count} message(s) into a summary:\n")
            self.history.write(summary)
            self.history.write("")

        self.app.call_from_thread(apply)

    def cmd_quit(self, args):
        # self.app.action_confirm_quit()
        self.app.quit_response(True)
        return True

    def cmd_version(self, args):
        if not args:
            self.history.write(f"Version: {__version__}\n")
            return True



    def cmd_backend(self, args):
        self.history.write(f"Backend: {self.app.backend}")
        self.history.write(f"API Base: {self.app.api_base}")
        self.history.write(f"Timeout: {self.app.config.timeout}\n")
        return True

    def cmd_provider(self, args):
        self.history.write(f"Provider: {self.app.backend}\n")
        return True

    def cmd_timeout(self, args):
        if not args:
            self.history.write(f"Current timeout: {self.app.timeout}s\n")
            return True

        try:
            value = int(args[0])
        except ValueError:
            self.history.write(f"timeout must be an integer, got: {args[0]}\n")
            return True

        self.app.timeout = value
        self.history.write(f"Setting timeout to {value}s\n")
        return True

    def cmd_model(self, args):
        if not args:
            self.history.write(f"Current model: {self.app.model}\n")
            return True

        value = args[0]
        self._set_model(value)
        self.history.write(f"Switching model to: {value}\n")
        return True

    def cmd_models(self, args):
        self.history.write("Fetching available models...")
        self.app.run_worker(self._fetch_models, thread=True)
        return True

    def _fetch_models(self):
        try:
            models = self.app.llm.list_models()
        except Exception as e:
            self.app.call_from_thread(self.history.write, f"Error fetching models: {e}\n")
            return

        lines = ["Available models:"]

        for model_id in models:
            marker = " (current)" if model_id == self.app.model else ""
            lines.append(f"  {model_id}{marker}")

        lines.append("")

        for line in lines:
            self.app.call_from_thread(self.history.write, line)

    def cmd_max_tokens(self, args):
        if not args:
            self.history.write(f"Current max_tokens: {self.app.max_tokens}\n")
            return True

        try:
            value = int(args[0])
        except ValueError:
            self.history.write(f"max_tokens must be an integer, got: {args[0]}\n")
            return True

        self.app.max_tokens = value
        self.history.write(f"Setting max_tokens to {value}\n")
        return True

    def cmd_min_p(self, args):
        if not args:
            current = self.app.min_p if self.app.min_p is not None else "(not set)"
            self.history.write(f"Current min_p: {current}\n")
            return True

        try:
            value = float(args[0])
        except ValueError:
            self.history.write(f"min_p must be a number, got: {args[0]}\n")
            return True

        self.app.min_p = value
        self.history.write(f"Setting min_p to {value}\n")
        return True

    def cmd_top_k(self, args):
        if not args:
            current = self.app.top_k if self.app.top_k is not None else "(not set)"
            self.history.write(f"Current top_k: {current}\n")
            return True

        try:
            value = int(args[0])
        except ValueError:
            self.history.write(f"top_k must be an integer, got: {args[0]}\n")
            return True

        self.app.top_k = value
        self.history.write(f"Setting top_k to {value}\n")
        return True

    def cmd_temperature(self, args):
        if not args:
            self.history.write(f"Current temperature: {self.app.temperature}\n")
            return True

        value = args[0]
        self._set_temperature(value)
        self.history.write(f"Setting Temperature to {value}\n")
        return True


    def cmd_reload(self, args):
        self.app.config = Config()

        self._set_model(self.app.config.model)
        self._set_temperature(self.app.config.temperature)
        self.app.api_base = self.app.config.api_base
        self.app.backend = self.app.config.backend
        self.app.max_tokens = self.app.config.max_tokens
        self.app.timeout = self.app.config.timeout
        self.app.context_window = self.app.config.context_window
        self.app.tools_enabled = self.app.config.tools_enabled

        self.history.write("Configuration reloaded from disk.\n")
        return True

    def cmd_session(self, args):
        elapsed = time.monotonic() - self.app.session_start
        minutes, seconds = divmod(int(elapsed), 60)
        duration = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"

        self.history.write("Session info:")
        self.history.write(f"Model: {self.app.model}")
        self.history.write(f"Temperature: {self.app.temperature}")
        self.history.write(f"Backend: {self.app.backend}")
        self.history.write(f"Messages sent: {self.app.message_count}")
        self.history.write(f"Duration: {duration}\n")
        return True

    def cmd_context(self, args):
        status_bar = self.app.query_one(StatusBar)
        pct = status_bar.context_pct

        if pct is None:
            self.history.write("No context usage yet — send a message first.\n")
            return True

        usage = self.app.llm.last_usage
        used = usage.total_tokens if usage else 0
        window = self.app.context_window

        width = 30
        filled = min(width, round(width * pct / 100))
        bar = "█" * filled + "░" * (width - filled)

        self.history.write("")
        self.history.write(f"[{bar}] {pct:.0f}%  ({used:,} / {window:,} tokens)")
        self.history.write("")
        return True

    def cmd_permissions(self, args):
        if args and args[0] == "revoke":
            if len(args) < 2:
                self.history.write("Usage: /permissions revoke <tool>|all\n")
                return True

            target = args[1]

            if target == "all":
                count = len(self.app.allowed_tools)
                self.app.allowed_tools.clear()
                self.history.write(f"Revoked {count} tool permission(s).\n")
                return True

            if target not in self.app.allowed_tools:
                self.history.write(f"{target} is not currently always-allowed.\n")
                return True

            self.app.allowed_tools.discard(target)
            self.history.write(f"Revoked always-allow for {target}.\n")
            return True

        if self.app.allowed_tools:
            self.history.write("Always-allowed this session:")
            for name in sorted(self.app.allowed_tools):
                self.history.write(f"  {name}")
            self.history.write("")
        else:
            self.history.write("No tools are set to always-allow this session.\n")

        prompting = sorted(tools.MUTATING_TOOLS - self.app.allowed_tools)

        if prompting:
            self.history.write("Still prompting before use:")
            for name in prompting:
                self.history.write(f"  {name}")
            self.history.write("")

        self.history.write("Usage: /permissions revoke <tool>|all\n")
        return True

    def cmd_stop(self, args):
        if not self.app.is_generating:
            self.history.write("Nothing to stop.\n")
            return True

        self.app.stop_event.set()
        self.history.write("Stopping...\n")
        return True

    def cmd_system_prompt(self, args):
        if not args:
            current = self.app.system_prompt or "(none set)"
            self.history.write(f"Current system prompt: {current}\n")
            return True

        value = " ".join(args)
        self.app.system_prompt = value
        self.app.persona = None
        self.history.write(f"System prompt set to: {value}\n")
        return True

    def _find_persona_file(self, name):
        safe_name = os.path.basename(name)

        for directory in search_dirs(PERSONAS_DIR):
            for ext in (".yaml", ".yml", ".txt"):
                path = os.path.join(directory, f"{safe_name}{ext}")
                if os.path.isfile(path):
                    return path

        return None

    def cmd_personas(self, args):
        names = set()

        for directory in search_dirs(PERSONAS_DIR):
            if not os.path.isdir(directory):
                continue

            for filename in os.listdir(directory):
                if filename.endswith((".txt", ".yaml", ".yml")):
                    names.add(os.path.splitext(filename)[0])

        if not names:
            self.history.write("No personas found.\n")
            return True

        self.history.write("Available personas:")

        for name in sorted(names):
            marker = " (current)" if name == self.app.persona else ""
            self.history.write(f"  {name}{marker}")

        self.history.write("")
        return True

    def cmd_persona(self, args):
        if not args:
            current = self.app.persona or "(none selected)"
            self.history.write(f"Current persona: {current}\n")
            return True

        name = args[0]
        path = self._find_persona_file(name)

        if not path:
            self.history.write(f"Persona not found: {name}\n")
            return True

        try:
            if path.endswith((".yaml", ".yml")):
                with open(path) as f:
                    data = yaml.safe_load(f) or {}

                system_prompt = data.get("system_prompt", "")
            else:
                with open(path) as f:
                    system_prompt = f.read().strip()
                data = {}
        except (OSError, yaml.YAMLError) as e:
            self.history.write(f"Error loading persona: {e}\n")
            return True

        self.app.system_prompt = system_prompt
        self.app.persona = name

        if "model" in data:
            self._set_model(data["model"])

        if "temperature" in data:
            self._set_temperature(data["temperature"])

        if "max_tokens" in data:
            self.app.max_tokens = data["max_tokens"]

        self.history.write(f"Switched to persona: {name}\n")
        return True

    def _write_messages(self, messages):
        for i, entry in enumerate(messages, 1):
            role = entry["role"].capitalize()
            content = entry["content"].replace("\n", " ")

            if len(content) > 80:
                content = content[:77] + "..."

            self.history.write(f"{i}. {role}: {content}")

        self.history.write("")

    def cmd_history(self, args):
        if not self.app.chat_log:
            self.history.write("No messages yet this session.\n")
            return True

        self.history.write("Session history:")
        self._write_messages(self.app.chat_log)
        return True

    def cmd_show(self, args):
        if not args:
            self.history.write("Usage: /show <name>")
            return True

        name = args[0]

        try:
            with open(self._session_path(name)) as f:
                data = json.load(f)
        except FileNotFoundError:
            self.history.write(f"Session not found: {name}\n")
            return True
        except (OSError, json.JSONDecodeError) as e:
            self.history.write(f"Error loading session: {e}\n")
            return True

        messages = data.get("messages", [])

        if not messages:
            self.history.write(f"Session '{name}' has no messages.\n")
            return True

        self.history.write(f"Session '{name}':")
        self._write_messages(messages)
        return True

    def _session_path(self, name):
        safe_name = os.path.basename(name)
        return os.path.join(SESSIONS_DIR, f"{safe_name}.json")

    def _save_session_data(self, name):
        os.makedirs(SESSIONS_DIR, exist_ok=True)

        data = {
            "name": name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "model": self.app.model,
            "temperature": self.app.temperature,
            "system_prompt": self.app.system_prompt,
            "messages": self.app.chat_log,
        }

        with open(self._session_path(name), "w") as f:
            json.dump(data, f, indent=2)

    def autosave(self):
        """Persist the live chat_log after every turn, so a crash can be recovered
        from with /load autosave instead of losing the whole conversation."""
        if not self.app.chat_log:
            return

        try:
            self._save_session_data(AUTOSAVE_NAME)
        except OSError:
            pass

    def clear_autosave(self):
        try:
            os.remove(self._session_path(AUTOSAVE_NAME))
        except OSError:
            pass

    def save_exit_session(self):
        """Save the current chat as a named session on a clean exit, so the user
        can resume it later with `llm-tui.sh <name>` or `/load <name>`."""
        if not self.app.chat_log:
            return None

        name = "exit-" + datetime.now().strftime("%Y%m%d-%H%M%S")

        try:
            self._save_session_data(name)
        except OSError:
            return None

        return name

    def autosave_info(self):
        try:
            with open(self._session_path(AUTOSAVE_NAME)) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

        messages = data.get("messages", [])

        if not messages:
            return None

        return len(messages), data.get("saved_at", "unknown")

    def cmd_save(self, args):
        if not args:
            self.history.write("Usage: /save <name>")
            return True

        name = args[0]

        try:
            self._save_session_data(name)
        except OSError as e:
            self.history.write(f"Error saving session: {e}\n")
            return True

        self.history.write(f"Session saved as '{name}' ({len(self.app.chat_log)} messages)\n")
        return True

    def cmd_list(self, args):
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        filenames = sorted(f for f in os.listdir(SESSIONS_DIR) if f.endswith(".json"))

        if not filenames:
            self.history.write("No saved sessions.\n")
            return True

        self.history.write("Saved sessions:")

        for filename in filenames:
            name = filename[:-len(".json")]

            try:
                with open(os.path.join(SESSIONS_DIR, filename)) as f:
                    data = json.load(f)
                count = len(data.get("messages", []))
                saved_at = data.get("saved_at", "unknown")
                self.history.write(f"  {name}  ({count} messages, saved {saved_at})")
            except (OSError, json.JSONDecodeError):
                self.history.write(f"  {name}  (unreadable)")

        self.history.write("")
        return True

    def cmd_delete(self, args):
        if not args:
            self.history.write("Usage: /delete <name>")
            return True

        name = args[0]

        try:
            os.remove(self._session_path(name))
        except FileNotFoundError:
            self.history.write(f"Session not found: {name}\n")
            return True
        except OSError as e:
            self.history.write(f"Error deleting session: {e}\n")
            return True

        self.history.write(f"Deleted session '{name}'\n")
        return True

    def cmd_load(self, args):
        if not args:
            self.history.write("Usage: /load <name>")
            return True

        name = args[0]

        try:
            with open(self._session_path(name)) as f:
                data = json.load(f)
        except FileNotFoundError:
            self.history.write(f"Session not found: {name}\n")
            return True
        except (OSError, json.JSONDecodeError) as e:
            self.history.write(f"Error loading session: {e}\n")
            return True

        self.history.clear()
        self.app.chat_log = []
        self.app.message_count = 0

        for entry in data.get("messages", []):
            role = entry.get("role")
            content = entry.get("content", "")

            if role == "user":
                self.history.add_user_message(content)
                self.app.message_count += 1
            elif role == "assistant":
                self.history.start_ai_response()
                self.history.append_ai_response(content)

            self.app.chat_log.append({"role": role, "content": content})

        if "model" in data:
            self._set_model(data["model"])

        if "temperature" in data:
            self._set_temperature(data["temperature"])

        if "system_prompt" in data:
            self.app.system_prompt = data["system_prompt"]

        self.app.persona = None
        self.autosave()
        self.app.query_one(StatusBar).reset_context()

        self.history.write(f"Loaded session '{name}' ({len(data.get('messages', []))} messages)\n")
        return True

    def cmd_read(self, args):
        if not args:
            if not self.app.context_files:
                self.history.write("No files loaded into context.\n")
                return True

            self.history.write("Files loaded into context:")
            for cf in self.app.context_files:
                self.history.write(f"  {cf['filename']} ({len(cf['content'])} characters)")
            self.history.write("")
            return True

        if args[0] == "clear":
            count = len(self.app.context_files)
            self.app.context_files = []
            self.history.write(f"Cleared {count} file(s) from context.\n")
            return True

        loaded = []

        for filename in args:
            try:
                with open(filename, "r") as f:
                    content = f.read()
            except FileNotFoundError:
                self.history.write(f"File not found: {filename}")
                continue
            except Exception as e:
                self.history.write(f"Error reading {filename}: {e}")
                continue

            self.app.context_files = [
                cf for cf in self.app.context_files if cf["filename"] != filename
            ]
            self.app.context_files.append({"filename": filename, "content": content})
            loaded.append(f"{filename} ({len(content)} characters)")

        if loaded:
            self.history.write(f"Loaded {len(loaded)} file(s):")
            for entry in loaded:
                self.history.write(f"  {entry}")

        return True

    def cmd_ls(self, args):
        flags = set()
        i = 0

        while i < len(args) and args[i] in LS_FLAGS:
            flags.add(args[i])
            i += 1

        rest = args[i:]
        path = rest[0] if rest else "."

        try:
            names = os.listdir(path)
        except FileNotFoundError:
            self.history.write(f"No such directory: {path}\n")
            return True
        except NotADirectoryError:
            self.history.write(f"Not a directory: {path}\n")
            return True
        except OSError as e:
            self.history.write(f"Error listing {path}: {e}\n")
            return True

        if "-a" not in flags:
            names = [n for n in names if not n.startswith(".")]

        entries = []

        for name in names:
            full = os.path.join(path, name)

            try:
                st = os.stat(full)
            except OSError:
                st = None

            entries.append((name, full, st))

        if "-t" in flags:
            entries.sort(key=lambda e: e[2].st_mtime if e[2] else 0, reverse=True)
        else:
            entries.sort(key=lambda e: e[0].lower())

        if "-r" in flags:
            entries.reverse()

        if not entries:
            self.history.write(f"{path} is empty\n")
            return True

        self.history.write(f"{path}:")

        for name, full, st in entries:
            label = f"{name}/" if os.path.isdir(full) else name

            if "-l" in flags and st is not None:
                mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                self.history.write(f"  {label:<30} {st.st_size:>10}  {mtime}")
            else:
                self.history.write(f"  {label}")

        self.history.write("")
        return True

    def _build_tree(self, path, prefix, lines, depth, flags, max_depth):
        if depth >= max_depth:
            return

        try:
            names = [e for e in os.listdir(path) if e not in TREE_IGNORE]
        except OSError:
            return

        if "-a" not in flags:
            names = [n for n in names if not n.startswith(".")]

        if "-d" in flags:
            names = [n for n in names if os.path.isdir(os.path.join(path, n))]

        entries = sorted(names, key=str.lower)

        truncated = len(entries) > TREE_MAX_ENTRIES
        entries = entries[:TREE_MAX_ENTRIES]

        for i, name in enumerate(entries):
            is_last = i == len(entries) - 1 and not truncated
            connector = "└── " if is_last else "├── "
            full = os.path.join(path, name)
            is_dir = os.path.isdir(full)
            lines.append(f"{prefix}{connector}{name}{'/' if is_dir else ''}")

            if is_dir:
                extension = "    " if is_last else "│   "
                self._build_tree(full, prefix + extension, lines, depth + 1, flags, max_depth)

        if truncated:
            lines.append(f"{prefix}└── ... more entries omitted")

    def cmd_tree(self, args):
        flags = set()
        max_depth = TREE_MAX_DEPTH
        i = 0

        while i < len(args):
            if args[i] in TREE_FLAGS:
                flags.add(args[i])
                i += 1
            elif args[i] in TREE_VALUE_FLAGS and i + 1 < len(args):
                try:
                    max_depth = int(args[i + 1])
                except ValueError:
                    self.history.write(f"Invalid value for -L: {args[i + 1]}\n")
                    return True
                i += 2
            else:
                break

        rest = args[i:]
        path = rest[0] if rest else "."

        if not os.path.isdir(path):
            self.history.write(f"No such directory: {path}\n")
            return True

        lines = [f"{path}/"]
        self._build_tree(path, "", lines, depth=0, flags=flags, max_depth=max_depth)

        for line in lines:
            self.history.write(line)

        self.history.write("")
        return True

    def cmd_grep(self, args):
        flags = set()
        i = 0

        while i < len(args) and args[i] in GREP_FLAGS:
            flags.add(args[i])
            i += 1

        rest = args[i:]

        if not rest:
            self.history.write("Usage: /grep [-i] [-v] [-w] [-c] [-l] <pattern> [path]")
            return True

        pattern = rest[0]
        path = rest[1] if len(rest) > 1 else "."

        if shutil.which("rg"):
            self._grep_ripgrep(pattern, path, flags)
        else:
            self._grep_python(pattern, path, flags)

        return True

    def _grep_ripgrep(self, pattern, path, flags):
        cmd = ["rg", "--line-number", "--no-heading", "--color=never"]
        cmd.extend(sorted(flags))
        cmd.extend([pattern, path])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            self.history.write("grep timed out\n")
            return

        if result.returncode == 2:
            self.history.write(f"grep error: {result.stderr.strip()}\n")
            return

        matches = result.stdout.splitlines()

        if not matches:
            self.history.write(f"No matches for '{pattern}' in {path}\n")
            return

        label = "Files matching" if "-l" in flags else "Match counts for" if "-c" in flags else "Matches for"
        self.history.write(f"{label} '{pattern}' in {path}:")

        for line in matches[:GREP_MAX_MATCHES]:
            self.history.write(f"  {line}")

        if len(matches) > GREP_MAX_MATCHES:
            self.history.write(f"  ... {len(matches) - GREP_MAX_MATCHES} more matches omitted")

        self.history.write("")

    def _grep_python(self, pattern, path, flags):
        re_flags = re.IGNORECASE if "-i" in flags else 0
        search_pattern = rf"\b{pattern}\b" if "-w" in flags else pattern

        try:
            regex = re.compile(search_pattern, re_flags)
        except re.error as e:
            self.history.write(f"Invalid pattern: {e}\n")
            return

        invert = "-v" in flags
        count_only = "-c" in flags
        files_only = "-l" in flags

        if os.path.isfile(path):
            files = [path]
        elif os.path.isdir(path):
            files = []
            for root, dirs, filenames in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in TREE_IGNORE]
                for filename in filenames:
                    if not filename.startswith("."):
                        files.append(os.path.join(root, filename))
        else:
            self.history.write(f"No such file or directory: {path}\n")
            return

        matches = []
        file_counts = {}

        for filepath in files:
            count = 0

            try:
                with open(filepath, encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if bool(regex.search(line)) != invert:
                            count += 1

                            if not count_only and not files_only and len(matches) < GREP_MAX_MATCHES:
                                matches.append(f"{filepath}:{i}:{line.rstrip()}")
            except (UnicodeDecodeError, OSError):
                continue

            if count:
                file_counts[filepath] = count

            if not count_only and not files_only and len(matches) >= GREP_MAX_MATCHES:
                break

        if files_only:
            if not file_counts:
                self.history.write(f"No matches for '{pattern}' in {path}\n")
                return

            self.history.write(f"Files matching '{pattern}' in {path}:")

            for filepath in file_counts:
                self.history.write(f"  {filepath}")

            self.history.write("")
            return

        if count_only:
            if not file_counts:
                self.history.write(f"No matches for '{pattern}' in {path}\n")
                return

            self.history.write(f"Match counts for '{pattern}' in {path}:")

            for filepath, count in file_counts.items():
                self.history.write(f"  {filepath}: {count}")

            self.history.write("")
            return

        if not matches:
            self.history.write(f"No matches for '{pattern}' in {path}\n")
            return

        self.history.write(f"Matches for '{pattern}' in {path}:")

        for m in matches:
            self.history.write(f"  {m}")

        self.history.write("")

    def cmd_cat(self, args):
        if not args:
            self.history.write("Usage: /cat <filename>")
            return True

        filename = args[0]

        try:
            with open(filename) as f:
                content = f.read()
        except FileNotFoundError:
            self.history.write(f"File not found: {filename}\n")
            return True
        except OSError as e:
            self.history.write(f"Error reading file: {e}\n")
            return True

        self.history.write(f"--- {filename} ---")
        self.history.write(content)
        self.history.write(f"--- end {filename} ---\n")
        return True

    def _extract_code(self, text):
        blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)

        if not blocks:
            return None

        return "\n\n".join(block.rstrip("\n") for block in blocks)

    def _last_ai_response(self):
        for entry in reversed(self.app.chat_log):
            if entry["role"] == "assistant":
                return entry["content"]

        return None

    def cmd_write(self, args):
        if not args:
            self.history.write("Usage: /write <path>  or  /write code <path>")
            return True

        code_only = args[0] == "code"

        if code_only:
            if len(args) < 2:
                self.history.write("Usage: /write code <path>")
                return True
            path = args[1]
        else:
            path = args[0]

        last_response = self._last_ai_response()

        if last_response is None:
            self.history.write("No AI response to write yet.\n")
            return True

        if code_only:
            content = self._extract_code(last_response)

            if content is None:
                self.history.write("No code block found in the last response; nothing written.\n")
                return True

            label = "code from last response"
            content += "\n"
        else:
            content = last_response
            label = "last response"

        try:
            with open(path, "w") as f:
                f.write(content)
        except OSError as e:
            self.history.write(f"Error writing file: {e}\n")
            return True

        self.history.write(f"Wrote {label} to {path} ({len(content)} characters)\n")
        return True

    def cmd_diff(self, args):
        if not args:
            self.history.write("Usage: /diff <path>")
            return True

        path = args[0]

        last_response = self._last_ai_response()

        if last_response is None:
            self.history.write("No AI response to diff yet.\n")
            return True

        new_content = self._extract_code(last_response)

        if new_content is None:
            self.history.write("No code block found in the last response; nothing to diff.\n")
            return True

        new_content += "\n"

        try:
            with open(path) as f:
                old_content = f.read()
        except FileNotFoundError:
            old_content = ""
        except OSError as e:
            self.history.write(f"Error reading file: {e}\n")
            return True

        diff_lines = list(difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"{path} (current)",
            tofile=f"{path} (from last response)",
        ))

        if not diff_lines:
            self.history.write(f"No differences between {path} and the last response's code.\n")
            return True

        self.history.write(f"Diff for {path}:")
        self.history.write("".join(diff_lines))
        self.history.write("")
        return True

    def cmd_edit(self, raw):
        if not raw:
            self.history.write("Usage: /edit <path> <old text> -> <new text>")
            return True

        path, sep, rest = raw.partition(" ")

        if not sep or " -> " not in rest:
            self.history.write("Usage: /edit <path> <old text> -> <new text>")
            return True

        old_text, new_text = rest.split(" -> ", 1)
        old_text = old_text.strip()
        new_text = new_text.strip()

        if not old_text:
            self.history.write("Old text cannot be empty.\n")
            return True

        try:
            with open(path) as f:
                content = f.read()
        except FileNotFoundError:
            self.history.write(f"File not found: {path}\n")
            return True
        except OSError as e:
            self.history.write(f"Error reading file: {e}\n")
            return True

        count = content.count(old_text)

        if count == 0:
            self.history.write(f"Text not found in {path}\n")
            return True

        if count > 1:
            self.history.write(
                f"'{old_text}' appears {count} times in {path} - "
                f"must be unique. No changes made.\n"
            )
            return True

        try:
            with open(path, "w") as f:
                f.write(content.replace(old_text, new_text, 1))
        except OSError as e:
            self.history.write(f"Error writing file: {e}\n")
            return True

        self.history.write(f"Edited {path}\n")
        return True




    def cmd_config(self, args):
        if len(args) == 0:
            self.history.write("Usage:")
            self.history.write(" /config")
            self.history.write(" /config <key>")
            self.history.write(" /config <key> <value>")
            self.history.write("")

            for key in CONFIG_KEYS:
                self.history.write(f"{key}: {self.app.config.get(key)}")

            self.history.write("")
            return True

        elif len(args) == 1:
            k = args[0]

            if k not in CONFIG_KEYS:
                self.history.write(
                    f"Unknown config item: {k}\n"
                    f"Valid keys: {', '.join(CONFIG_KEYS)}\n"
                )
                return True

            self.history.write(f"{k}: {self.app.config.get(k)}\n")
            return True

        elif len(args) == 2:
            k, v = args[0], args[1]

            if k not in CONFIG_KEYS:
                self.history.write(
                    f"Unknown config item: {k}\n"
                    f"Valid keys: {', '.join(CONFIG_KEYS)}\n"
                )
                return True

            try:
                self.app.config.set(k, v)
                self.history.write(f"{k} updated to: {v}\n")
            except (KeyError, AttributeError) as e:
                self.history.write(f"Could not set {k}: {e}\n")

            return True
