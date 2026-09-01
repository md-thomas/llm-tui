import difflib
import fnmatch
import os
import re
import shutil
import subprocess

MAX_READ_CHARS = 20000
GREP_MAX_MATCHES = 50
GREP_TIMEOUT = 30
GLOB_MAX_MATCHES = 100
TREE_IGNORE = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
}


def read_file(path):
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except IsADirectoryError:
        return f"Error: {path} is a directory"
    except OSError as e:
        return f"Error reading {path}: {e}"

    if len(content) > MAX_READ_CHARS:
        omitted = len(content) - MAX_READ_CHARS
        content = content[:MAX_READ_CHARS] + f"\n... [truncated, {omitted} more characters]"

    return f"--- {path} ---\n{content}\n--- end {path} ---"


def list_dir(path="."):
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except FileNotFoundError:
        return f"Error: no such directory: {path}"
    except NotADirectoryError:
        return f"Error: not a directory: {path}"
    except OSError as e:
        return f"Error listing {path}: {e}"

    names = [n for n in names if not n.startswith(".")]

    if not names:
        return f"{path} is empty"

    lines = [f"{path}:"]

    for name in names:
        full = os.path.join(path, name)
        lines.append(f"  {name}/" if os.path.isdir(full) else f"  {name}")

    return "\n".join(lines)


def grep(pattern, path="."):
    if shutil.which("rg"):
        return _grep_ripgrep(pattern, path)

    return _grep_python(pattern, path)


def _grep_ripgrep(pattern, path):
    cmd = ["rg", "--line-number", "--no-heading", "--color=never", pattern, path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=GREP_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "Error: grep timed out"

    if result.returncode == 2:
        return f"Error: {result.stderr.strip()}"

    matches = result.stdout.splitlines()

    if not matches:
        return f"No matches for '{pattern}' in {path}"

    lines = [f"Matches for '{pattern}' in {path}:"] + matches[:GREP_MAX_MATCHES]

    if len(matches) > GREP_MAX_MATCHES:
        lines.append(f"... {len(matches) - GREP_MAX_MATCHES} more matches omitted")

    return "\n".join(lines)


def _grep_python(pattern, path):
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid pattern: {e}"

    if os.path.isfile(path):
        files = [path]
    elif os.path.isdir(path):
        files = []

        for root, dirs, filenames in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in TREE_IGNORE]
            files.extend(os.path.join(root, f) for f in filenames if not f.startswith("."))
    else:
        return f"Error: no such file or directory: {path}"

    matches = []

    for filepath in files:
        try:
            with open(filepath, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if regex.search(line):
                        matches.append(f"{filepath}:{i}:{line.rstrip()}")

                        if len(matches) >= GREP_MAX_MATCHES:
                            break
        except (UnicodeDecodeError, OSError):
            continue

        if len(matches) >= GREP_MAX_MATCHES:
            break

    if not matches:
        return f"No matches for '{pattern}' in {path}"

    return "\n".join([f"Matches for '{pattern}' in {path}:"] + matches)


def glob_files(pattern, path="."):
    if not os.path.isdir(path):
        return f"Error: no such directory: {path}"

    matches = []

    for root, dirs, filenames in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in TREE_IGNORE]

        for filename in filenames:
            if filename.startswith("."):
                continue

            filepath = os.path.join(root, filename)

            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(filepath, pattern):
                matches.append(filepath)

                if len(matches) >= GLOB_MAX_MATCHES:
                    break

        if len(matches) >= GLOB_MAX_MATCHES:
            break

    matches.sort()

    if not matches:
        return f"No files matching '{pattern}' in {path}"

    lines = [f"Files matching '{pattern}' in {path}:"] + [f"  {m}" for m in matches]

    if len(matches) >= GLOB_MAX_MATCHES:
        lines.append(f"... stopped at {GLOB_MAX_MATCHES} matches")

    return "\n".join(lines)


def edit_file(path, old_text, new_text):
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except OSError as e:
        return f"Error reading {path}: {e}"

    count = content.count(old_text)

    if count == 0:
        return f"Error: text not found in {path}"

    if count > 1:
        return f"Error: '{old_text}' appears {count} times in {path} - must be unique. No changes made."

    try:
        with open(path, "w") as f:
            f.write(content.replace(old_text, new_text, 1))
    except OSError as e:
        return f"Error writing {path}: {e}"

    return f"Edited {path}"


def write_file(path, content):
    try:
        with open(path, "w") as f:
            f.write(content)
    except OSError as e:
        return f"Error writing {path}: {e}"

    return f"Wrote {path} ({len(content)} characters)"


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a text file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file, relative to the current working directory.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List the contents of a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory to list. Defaults to the current directory.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search for a regular expression pattern in files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression to search for."},
                    "path": {
                        "type": "string",
                        "description": "File or directory to search. Defaults to the current directory.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": (
                "Find files by name pattern (e.g. '*.py', 'test_*.py'). Searches recursively "
                "from the given directory, skipping .git/__pycache__/node_modules/etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob-style filename pattern, e.g. '*.py' or 'test_*.py'.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search from. Defaults to the current directory.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace a unique block of text in an existing file with new text. "
                "Fails if old_text does not appear in the file exactly once."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to edit."},
                    "old_text": {
                        "type": "string",
                        "description": "Exact text to replace. Must appear exactly once in the file.",
                    },
                    "new_text": {"type": "string", "description": "Text to replace it with."},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file, overwriting it if it exists or creating it if not.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to write."},
                    "content": {"type": "string", "description": "Full content to write to the file."},
                },
                "required": ["path", "content"],
            },
        },
    },
]

TOOLS = {
    "read_file": read_file,
    "list_dir": list_dir,
    "grep": grep,
    "glob_files": glob_files,
    "edit_file": edit_file,
    "write_file": write_file,
}

MUTATING_TOOLS = {"edit_file", "write_file"}


def describe_tool_call(name, args):
    """Return (description, preview) for display and confirmation prompts."""
    if name == "edit_file":
        path = args.get("path", "?")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")
        description = f"Edit {path}"

        try:
            with open(path) as f:
                content = f.read()
        except OSError:
            content = ""

        if old_text and content.count(old_text) == 1:
            new_content = content.replace(old_text, new_text, 1)
            diff = "".join(difflib.unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"{path} (current)",
                tofile=f"{path} (after edit)",
            ))
            preview = diff or "(no visible diff)"
        else:
            preview = f"- {old_text}\n+ {new_text}"

        return description, preview

    if name == "write_file":
        path = args.get("path", "?")
        content = args.get("content", "")
        description = f"Write {path} ({len(content)} characters)"
        preview = content if len(content) <= 2000 else content[:2000] + "\n... [truncated]"
        return description, preview

    args_repr = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{name}({args_repr})", None
