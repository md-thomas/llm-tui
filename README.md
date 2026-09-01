# llm-tui

A terminal chat UI for local/OpenAI-compatible LLM backends (e.g. [LM Studio](https://lmstudio.ai/)), built with [Textual](https://textual.textualize.io/).

## Features

- Streaming chat with a live token count and elapsed-time display
- Status bar showing a cycling "thinking" indicator, braille spinner, temperature, live token count, elapsed time, context-window usage, and current model
- Reasoning-model "thinking" output is tracked separately from visible content (and still counts toward the live token display)
- LLM tool calling: the model can call `read_file`, `list_dir`, `grep`, `edit_file`, and `write_file` itself mid-response — see [Tool calling](#tool-calling) below
- Named personas (system prompt + optional model/temperature/max_tokens bundled together)
- Session persistence: save, load, list, preview, and delete named conversations
- File tools: display a file, load one into context, edit it with a precise find/replace, or write the model's last response (or just its code) straight to disk
- Per-user config overrides in your home directory, falling back to the bundled defaults
- Tab-completion (shell-style: fills the common prefix, lists candidates when ambiguous) and input history (↑/↓) for the input box

## Requirements

- Python 3.12+
- An OpenAI-compatible chat completions endpoint (e.g. LM Studio running locally)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with your API key (any non-empty value works for local backends that don't check it):

```
OPENAI_API_KEY=lmstudio
```

Configure the backend, model, and connection details in `config.yaml`:

```yaml
llm:
  provider: lmstudio
  model: google/gemma-4-12b-qat
  temperature: 0.7
  max_tokens: 2048
  context_window: 8192
  tools_enabled: true
connection:
  api_base: http://localhost:1234/v1
  timeout: 300
```

`context_window` drives the context-usage percentage in the status bar. `tools_enabled` turns [tool calling](#tool-calling) on or off — set it to `false` if your model/backend doesn't support OpenAI-style function calling.

## Running

```bash
./llm-tui.sh
```

Resolves its own directory first, so it can be run from anywhere (e.g. symlinked onto your `$PATH`) and still find `config.yaml`, `personas/`, `system_prompt.txt`, and `sessions/` correctly. Equivalent to:

```bash
source .venv/bin/activate
python main.py
```

## Per-user config

`config.yaml`, `system_prompt.txt`, `help.txt`, and `personas/*` are all looked up in `~/.config/llm-tui/` first, falling back to the copies bundled in this install if nothing's there. The first time you change a setting with `/config`, your edit is written to `~/.config/llm-tui/config.yaml` — the bundled `config.yaml` is never modified. Saved sessions and the log file always live under `~/.config/llm-tui/` too (never in the install directory), so a shared, read-only install works cleanly for multiple users — see [Installing for multiple users](#installing-for-multiple-users).

## Personas

A persona is a named system prompt, optionally bundled with a model/temperature/max_tokens override. Two formats are supported in `personas/`:

```yaml
# personas/coder.yaml
system_prompt: "You are an expert coder..."
temperature: 0.1
max_tokens: 1024
```

```
# personas/concise.txt
You are a terse assistant. Answer in as few words as possible...
```

Switch with `/persona <name>`; list what's available with `/personas`.

## Sessions

`/save <name>` writes the current conversation to `~/.config/llm-tui/sessions/<name>.json`. `/list` shows what's saved, `/show <name>` previews a saved session without touching your current conversation, `/load <name>` replaces the current conversation with it (also restoring its model/temperature), and `/delete <name>` removes it.

## Tool calling

When `tools_enabled` is on (the default) and the backend supports it, the model can call five tools mid-response instead of only replying with text:

- **Read-only** — `read_file`, `list_dir`, `grep` — run immediately, no prompt.
- **Mutating** — `edit_file`, `write_file` — pop a confirm dialog (Allow / Always Allow / Deny) before touching disk. Each call and its result is shown inline in the chat transcript.

**Always Allow** on that dialog stops prompting for that tool for the rest of the running session (not persisted — resets on restart). Manage grants with `/permissions` (lists what's currently allowed) and `/permissions revoke <tool>|all` (takes a grant back without restarting).

## Commands

| Command | Description |
|---|---|
| `/help` | Show the full command reference and keybindings |
| `/commands` | List all commands with a one-line description each |
| `/quit`, `/exit` | Exit the application |
| `/clear` | Clear the chat history |
| `/new` | Clear the display and reset session tracking |
| `/stop` | Stop the in-progress response |
| `/reload` | Re-read `config.yaml` and apply it to the running app |
| `/config [key] [value]` | Show or update config values (keys: `backend`, `api_base`, `timeout`, `model`, `temperature`, `max_tokens`, `context_window`, `tools_enabled`) |
| `/backend` | Show backend/connection info |
| `/provider` | Show the current provider |
| `/model [name]` | Get or set the current model |
| `/models` | List models available from the backend |
| `/temperature [value]` | Get or set the temperature |
| `/max_tokens [value]` | Get or set max_tokens |
| `/min_p [value]` | Get or set min_p |
| `/top_k [value]` | Get or set top_k |
| `/timeout [seconds]` | Get or set the request timeout |
| `/system_prompt [text]` | Get or set the system prompt |
| `/persona [name]` | Get or switch personas |
| `/personas` | List available personas |
| `/session` | Show model/temperature/message count/duration for this run |
| `/permissions [revoke <tool>\|all]` | Show or revoke tools the model can always use without confirmation |
| `/history` | Show messages from the current session |
| `/save <name>` | Save the current session |
| `/list` | List saved sessions |
| `/show <name>` | Preview a saved session without loading it |
| `/load <name>` | Load a saved session |
| `/delete <name>` | Delete a saved session |
| `/ls [-a] [-l] [-r] [-t] [path]` | List a directory's contents |
| `/tree [-a] [-d] [-L n] [path]` | Show a recursive directory tree (skips `.git`/`__pycache__`/`node_modules`/etc.) |
| `/grep [-i] [-v] [-w] [-c] [-l] <pattern> [path]` | Search file contents (ripgrep if installed, plain-Python fallback otherwise) |
| `/cat <file>` | Display a file's contents |
| `/read [file...]` | Load one or more files into the LLM context; no args lists what's loaded, `/read clear` clears it |
| `/edit <path> <old> -> <new>` | Edit a file via exact find/replace (must be unique in the file) |
| `/write <path>` / `/write code <path>` | Write the last AI response (or just its code) to a file |
| `/diff <path>` | Preview what `/write code <path>` would change, without writing anything |
| `/version` | Show the app version |

## Keybindings

| Key | Action |
|---|---|
| `Enter` | Send message |
| `Ctrl+J` | Insert newline |
| `Tab` | Autocomplete a slash command |
| `Ctrl+↑` / `Ctrl+↓` | Navigate input history |
| `Ctrl+L` | Clear the chat history |
| `Ctrl+N` | Start a new session |
| `Ctrl+D` | Quit (with confirmation) |

## Testing

A full, offline test suite covers every command plus the tool-calling flow (102 tests as of writing). It never touches your real `~/.config/llm-tui/` — each run redirects `XDG_CONFIG_HOME` to an isolated temp directory before anything is imported, and no live LLM backend is required (network-dependent commands like `/models`, and tool-calling itself, are tested against a mocked/scripted backend).

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
```

`requirements-dev.txt`, `pytest.ini`, and `tests/` are test-only — `package.sh` never includes them in the shipped tarball.

## Installing for multiple users

The app is designed to run from a single shared, read-only install (e.g. `/opt/llm-tui`) used by any number of unprivileged users — nothing it writes at runtime (config edits, sessions, the log file) ever touches the install directory itself; it all goes to each user's own `~/.config/llm-tui/`.

One command, from this repo, builds and installs it in one shot:

```bash
./deploy.sh          # deploys to /opt/llm-tui
./deploy.sh /srv      # or any other parent directory, e.g. /srv/llm-tui
```

Or do it in steps — build the tarball with `./package.sh` (outputs `dist/llm-tui.tar.gz`), then on the target machine:

```bash
sudo tar -xzf llm-tui.tar.gz -C /opt
sudo /opt/llm-tui/install.sh
```

Either way, `install.sh` creates a shared `.venv` inside the install directory and installs dependencies into it — the one step that needs root, since regular users won't have write access there. Re-running `deploy.sh`/`install.sh` on an existing install is safe and leaves the `.venv` alone if it's already set up. After that, any user can run `/opt/llm-tui/llm-tui.sh` (or symlink it onto their `$PATH`) and get their own independent config, personas, sessions, and log — all isolated from every other user, with no shared mutable state between concurrent sessions.

## Project layout

```
app.py              Textual App, top-level event wiring
commands.py         Slash command definitions and handlers
config.py           config.yaml loader/accessor (user-dir aware)
paths.py            User-config-dir resolution shared by config/personas/sessions/log
llm_client.py       OpenAI-compatible streaming client, incl. the tool-call loop
tools.py            LLM tool implementations (read_file, grep, edit_file, etc.) and their schemas
widgets/            ChatHistory, ChatInput, StatusBar, Spinner, ToolConfirmModal
css/app.tcss         Styling
personas/            Bundled default personas
system_prompt.txt    Bundled default system prompt
help.txt             Bundled default help text (shown by /help)
llm-tui.sh           Startup script
package.sh           Builds dist/llm-tui.tar.gz from the current source
install.sh           Runs inside an extracted install: creates .venv, installs deps
deploy.sh            One-shot: package.sh + extract + install.sh to a target dir (default /opt)
tests/               Offline command test suite (not shipped in the tarball)
```
