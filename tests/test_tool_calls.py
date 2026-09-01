"""
Tests for LLM-driven tool calling: the model can call read_file/list_dir/grep
automatically, but edit_file/write_file must be confirmed via ToolConfirmModal
before anything on disk changes.
"""

import json
import os
from types import SimpleNamespace

from textual.widgets import Button

from app import LLMApp
from commands import SESSIONS_DIR
from widgets.tool_confirm import ToolConfirmModal
from llm_client import MAX_TOOL_ITERATIONS

from tests.helpers import submit, lines, wait_for


def make_chunk(content=None, tool_calls=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def make_tool_call(index, id, name, arguments):
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments))


class FakeResponse:
    def __init__(self, chunks):
        self._chunks = chunks

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        pass


def scripted_create(responses):
    """Returns a fake `create()` that hands back one scripted response per call."""
    responses = list(responses)
    calls = []

    def _create(**kwargs):
        calls.append(kwargs)
        return FakeResponse(responses.pop(0))

    _create.calls = calls
    return _create


async def test_read_only_tool_runs_without_confirmation(app_pilot, tmp_path):
    app, pilot = app_pilot
    target = tmp_path / "notes.txt"
    target.write_text("hello from disk")

    call = make_tool_call(0, "call_1", "read_file", json.dumps({"path": str(target)}))
    create = scripted_create([
        [make_chunk(tool_calls=[call])],
        [make_chunk(content="I read the file.")],
    ])
    app.llm.client.chat.completions.create = create

    await submit(app, pilot, "read the notes file")
    await wait_for(app, pilot, lambda app: not app.is_generating)

    assert "I read the file." in lines(app)[-1]
    assert any("read_file" in line for line in lines(app))
    assert len(create.calls) == 2


async def test_glob_files_runs_without_confirmation(app_pilot, tmp_path):
    app, pilot = app_pilot
    (tmp_path / "app.py").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / ".hidden.py").write_text("x")
    (tmp_path / "widgets").mkdir()
    (tmp_path / "widgets" / "status_bar.py").write_text("x")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-312.pyc.py").write_text("x")

    call = make_tool_call(0, "call_1", "glob_files", json.dumps({"pattern": "*.py", "path": str(tmp_path)}))
    create = scripted_create([
        [make_chunk(tool_calls=[call])],
        [make_chunk(content="Found two Python files.")],
    ])
    app.llm.client.chat.completions.create = create

    await submit(app, pilot, "find python files")
    await wait_for(app, pilot, lambda app: not app.is_generating)

    transcript = "\n".join(lines(app))
    assert "Found two Python files." in lines(app)[-1]
    assert str(tmp_path / "app.py") in transcript
    assert str(tmp_path / "widgets" / "status_bar.py") in transcript
    assert ".hidden.py" not in transcript
    assert "__pycache__" not in transcript


async def test_mutating_tool_denied_leaves_file_untouched(app_pilot, tmp_path):
    app, pilot = app_pilot
    target = tmp_path / "target.txt"
    target.write_text("hello world\n")

    call = make_tool_call(
        0, "call_1", "edit_file",
        json.dumps({"path": str(target), "old_text": "hello", "new_text": "goodbye"}),
    )
    create = scripted_create([
        [make_chunk(tool_calls=[call])],
        [make_chunk(content="Okay, I left it alone.")],
    ])
    app.llm.client.chat.completions.create = create

    await submit(app, pilot, "edit the target file")
    await wait_for(app, pilot, lambda app: isinstance(app.screen, ToolConfirmModal))

    app.screen.query_one("#deny", Button).press()
    await wait_for(app, pilot, lambda app: not app.is_generating)

    assert target.read_text() == "hello world\n"
    assert any("denied" in line.lower() for line in lines(app))


async def test_mutating_tool_allowed_applies_edit(app_pilot, tmp_path):
    app, pilot = app_pilot
    target = tmp_path / "target.txt"
    target.write_text("hello world\n")

    call = make_tool_call(
        0, "call_1", "edit_file",
        json.dumps({"path": str(target), "old_text": "hello", "new_text": "goodbye"}),
    )
    create = scripted_create([
        [make_chunk(tool_calls=[call])],
        [make_chunk(content="Done.")],
    ])
    app.llm.client.chat.completions.create = create

    await submit(app, pilot, "edit the target file")
    await wait_for(app, pilot, lambda app: isinstance(app.screen, ToolConfirmModal))

    app.screen.query_one("#allow", Button).press()
    await wait_for(app, pilot, lambda app: not app.is_generating)

    assert target.read_text() == "goodbye world\n"


async def test_always_allow_skips_future_confirmations(app_pilot, tmp_path):
    app, pilot = app_pilot
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("hello world\n")
    second.write_text("hello moon\n")

    call1 = make_tool_call(
        0, "call_1", "edit_file",
        json.dumps({"path": str(first), "old_text": "hello", "new_text": "goodbye"}),
    )
    call2 = make_tool_call(
        0, "call_2", "edit_file",
        json.dumps({"path": str(second), "old_text": "hello", "new_text": "goodbye"}),
    )
    create = scripted_create([
        [make_chunk(tool_calls=[call1])],
        [make_chunk(content="First edit done.")],
        [make_chunk(tool_calls=[call2])],
        [make_chunk(content="Second edit done.")],
    ])
    app.llm.client.chat.completions.create = create

    await submit(app, pilot, "edit the first file")
    await wait_for(app, pilot, lambda app: isinstance(app.screen, ToolConfirmModal))
    app.screen.query_one("#always", Button).press()
    await wait_for(app, pilot, lambda app: not app.is_generating)

    assert first.read_text() == "goodbye world\n"
    assert app.allowed_tools == {"edit_file"}

    # Second edit_file call should apply without any modal appearing.
    await submit(app, pilot, "edit the second file")
    await wait_for(app, pilot, lambda app: not app.is_generating)

    assert second.read_text() == "goodbye moon\n"
    assert len(create.calls) == 4


async def test_message_exchange_autosaves(app_pilot):
    app, pilot = app_pilot
    create = scripted_create([[make_chunk(content="Hello there.")]])
    app.llm.client.chat.completions.create = create

    await submit(app, pilot, "hi")
    await wait_for(app, pilot, lambda app: not app.is_generating)

    with open(os.path.join(SESSIONS_DIR, "autosave.json")) as f:
        data = json.load(f)

    assert data["messages"] == app.chat_log
    assert data["messages"][-1]["content"] == "Hello there."


async def test_autosave_survives_a_restart(app_pilot):
    app, pilot = app_pilot
    create = scripted_create([[make_chunk(content="Hello there.")]])
    app.llm.client.chat.completions.create = create

    await submit(app, pilot, "hi")
    await wait_for(app, pilot, lambda app: not app.is_generating)

    # Simulate the app crashing and a fresh process starting back up.
    new_app = LLMApp()
    async with new_app.run_test() as new_pilot:
        notice = "\n".join(lines(new_app))
        assert "auto-saved session" in notice.lower()

        await submit(new_app, new_pilot, "/load autosave")
        assert any(e["content"] == "Hello there." for e in new_app.chat_log)


async def test_tool_loop_stops_at_iteration_cap(app_pilot, tmp_path):
    app, pilot = app_pilot
    target = tmp_path / "notes.txt"
    target.write_text("hello from disk")

    calls = []

    def _create(**kwargs):
        calls.append(kwargs)
        call = make_tool_call(
            0, f"call_{len(calls)}", "read_file", json.dumps({"path": str(target)})
        )
        return FakeResponse([make_chunk(tool_calls=[call])])

    app.llm.client.chat.completions.create = _create

    await submit(app, pilot, "keep reading the notes file forever")
    await wait_for(app, pilot, lambda app: not app.is_generating, timeout=10)

    assert len(calls) == MAX_TOOL_ITERATIONS
    assert "limit reached" in lines(app)[-1].lower()
