"""
Repeatable command test suite for llm-tui.

Runs entirely offline against an isolated config directory (see
conftest.py) -- no live LLM backend is required. Run with:

    source .venv/bin/activate
    pip install -r requirements-dev.txt
    python -m pytest
"""

import os
import json
import yaml
import pytest

from unittest.mock import patch

from tests.helpers import submit, lines, last, wait_for


# ---------------------------------------------------------------------------
# GENERAL
# ---------------------------------------------------------------------------

async def test_help_shows_full_reference(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/help")
    assert "llm-tui" in last(app)
    assert "/model" in last(app)
    assert "KEYBINDINGS" in last(app)


async def test_commands_lists_registered_commands(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/commands")
    text = "\n".join(lines(app, len(app.commands.commands) + 3))
    for cmd in ("/help", "/model", "/grep", "/stop"):
        assert cmd in text


async def test_clear_empties_history(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/version")
    assert len(lines(app)) > 3
    await submit(app, pilot, "/clear")
    assert lines(app) == []


async def test_new_resets_session_state(app_pilot):
    app, pilot = app_pilot
    app.chat_log = [{"role": "user", "content": "hi"}]
    app.message_count = 5
    await submit(app, pilot, "/new")
    assert app.chat_log == []
    assert app.message_count == 0
    assert "new session" in last(app).lower()


async def test_compact_with_nothing_to_compact(app_pilot):
    app, pilot = app_pilot
    app.chat_log = []
    await submit(app, pilot, "/compact")
    assert "nothing to compact" in last(app).lower()


async def test_compact_summarizes_and_replaces_history(app_pilot):
    app, pilot = app_pilot
    app.chat_log = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]

    def fake_chat(*args, **kwargs):
        yield ("content", "Short ")
        yield ("content", "summary.")

    with patch.object(app.llm, "chat", side_effect=fake_chat):
        await submit(app, pilot, "/compact")
        await wait_for(app, pilot, lambda a: app.chat_log == [{"role": "assistant", "content": "Short summary."}])

    text = "\n".join(lines(app))
    assert "compacted" in text.lower()
    assert "Short summary." in text


async def test_compact_handles_backend_error(app_pilot):
    app, pilot = app_pilot
    app.chat_log = [{"role": "user", "content": "hi"}]

    def fake_chat(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover -- keeps this a generator function

    with patch.object(app.llm, "chat", side_effect=fake_chat):
        await submit(app, pilot, "/compact")
        await wait_for(app, pilot, lambda a: "error" in last(a).lower())

    assert "boom" in last(app)
    assert app.chat_log == [{"role": "user", "content": "hi"}]


async def test_new_clears_autosave(app_pilot):
    app, pilot = app_pilot
    app.chat_log = [{"role": "user", "content": "hi"}]
    app.commands.autosave()
    assert app.commands.autosave_info() is not None

    await submit(app, pilot, "/new")
    assert app.commands.autosave_info() is None


async def test_startup_shows_resume_notice_for_existing_autosave():
    from app import LLMApp
    from commands import SESSIONS_DIR

    os.makedirs(SESSIONS_DIR, exist_ok=True)

    with open(os.path.join(SESSIONS_DIR, "autosave.json"), "w") as f:
        json.dump({
            "name": "autosave",
            "saved_at": "2024-01-01T00:00:00",
            "messages": [{"role": "user", "content": "hi"}],
        }, f)

    app = LLMApp()

    async with app.run_test() as pilot:
        text = "\n".join(lines(app))
        assert "auto-saved session" in text.lower()
        assert "/load autosave" in text


async def test_no_resume_notice_when_no_autosave(app_pilot):
    app, pilot = app_pilot
    text = "\n".join(lines(app))
    assert "auto-saved session" not in text.lower()


async def test_context_with_no_usage_yet(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/context")
    assert "no context usage yet" in last(app).lower()


async def test_context_shows_bar_and_percentage(app_pilot):
    from types import SimpleNamespace
    from widgets.status_bar import StatusBar

    app, pilot = app_pilot
    app.context_window = 1000
    app.llm.last_usage = SimpleNamespace(total_tokens=500, completion_tokens=100)
    status_bar = app.query_one(StatusBar)
    status_bar._context_pct = 50

    await submit(app, pilot, "/context")
    text = lines(app)[-2]
    assert "50%" in text
    assert "500" in text and "1,000" in text
    assert "█" in text and "░" in text
    assert lines(app)[-1] == ""
    assert lines(app)[-3] == ""


async def test_new_resets_context_indicator(app_pilot):
    from widgets.status_bar import StatusBar

    app, pilot = app_pilot
    status_bar = app.query_one(StatusBar)
    status_bar._context_pct = 87
    status_bar._refresh_stats()
    assert "Ctx: 87%" in str(status_bar.query_one("#stats").render())

    await submit(app, pilot, "/new")
    assert "Ctx:" not in str(status_bar.query_one("#stats").render())


async def test_compact_resets_context_indicator(app_pilot):
    from widgets.status_bar import StatusBar

    app, pilot = app_pilot
    app.chat_log = [{"role": "user", "content": "hi"}]
    status_bar = app.query_one(StatusBar)
    status_bar._context_pct = 87
    status_bar._refresh_stats()

    def fake_chat(*args, **kwargs):
        yield ("content", "summary")

    with patch.object(app.llm, "chat", side_effect=fake_chat):
        await submit(app, pilot, "/compact")
        await wait_for(app, pilot, lambda a: "Ctx:" not in str(status_bar.query_one("#stats").render()))


async def test_compact_shows_thinking_state_until_done(app_pilot):
    import threading

    from widgets.spinner import Spinner
    from widgets.status_bar import StatusBar

    app, pilot = app_pilot
    app.chat_log = [{"role": "user", "content": "hi"}]
    status_bar = app.query_one(StatusBar)
    spinner = status_bar.query_one("#spinner", Spinner)

    release = threading.Event()

    def fake_chat(*args, **kwargs):
        release.wait(timeout=5)
        yield ("content", "summary")

    with patch.object(app.llm, "chat", side_effect=fake_chat):
        await submit(app, pilot, "/compact")
        await pilot.pause()

        assert spinner._timer is not None
        assert str(status_bar.query_one("#status").render()) != "Ready"

        release.set()
        await wait_for(app, pilot, lambda a: spinner._timer is None)

    assert str(status_bar.query_one("#status").render()) == "Ready"


async def test_stop_with_nothing_running(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/stop")
    assert "nothing to stop" in last(app).lower()


async def test_stop_sets_event_when_generating(app_pilot):
    app, pilot = app_pilot
    app.is_generating = True
    app.stop_event.clear()
    await submit(app, pilot, "/stop")
    assert app.stop_event.is_set()
    assert "stopping" in last(app).lower()


async def test_version(app_pilot):
    app, pilot = app_pilot
    from version import __version__

    await submit(app, pilot, "/version")
    assert __version__ in last(app)


async def test_quit_triggers_exit(app_pilot):
    app, pilot = app_pilot
    called = {}
    app.exit = lambda *a, **kw: called.setdefault("exited", True)
    await submit(app, pilot, "/quit")
    assert called.get("exited") is True


async def test_exit_is_an_alias_for_quit(app_pilot):
    app, pilot = app_pilot
    called = {}
    app.exit = lambda *a, **kw: called.setdefault("exited", True)
    await submit(app, pilot, "/exit")
    assert called.get("exited") is True


async def test_unknown_command(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/bogus")
    assert "unknown command" in last(app).lower()


# ---------------------------------------------------------------------------
# MODEL & GENERATION SETTINGS
# ---------------------------------------------------------------------------

async def test_model_get(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/model")
    assert app.model in last(app)


async def test_model_set_syncs_llm_and_status_bar(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/model some-other-model")
    assert app.model == "some-other-model"
    assert app.llm.model == "some-other-model"

    from widgets.status_bar import StatusBar

    status_bar = app.query_one(StatusBar)
    assert str(status_bar.query_one("#model").render()) == "some-other-model"


async def test_models_lists_and_marks_current(app_pilot):
    app, pilot = app_pilot
    app.model = "model-b"

    with patch.object(app.llm, "list_models", return_value=["model-a", "model-b"]):
        await submit(app, pilot, "/models")
        await wait_for(app, pilot, lambda a: "" == last(a))

    text = "\n".join(lines(app, 5))
    assert "model-a" in text
    assert "model-b (current)" in text


async def test_models_handles_backend_error(app_pilot):
    app, pilot = app_pilot

    with patch.object(app.llm, "list_models", side_effect=RuntimeError("boom")):
        await submit(app, pilot, "/models")
        await wait_for(app, pilot, lambda a: "error" in last(a).lower())

    assert "boom" in last(app)


async def test_temperature_get_set(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/temperature")
    assert str(app.temperature) in last(app)

    await submit(app, pilot, "/temperature 0.42")
    assert app.temperature == "0.42"
    assert app.llm.temperature == "0.42"


async def test_max_tokens_get_set_and_invalid(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/max_tokens 512")
    assert app.max_tokens == 512

    await submit(app, pilot, "/max_tokens notanumber")
    assert "must be an integer" in last(app)
    assert app.max_tokens == 512


async def test_min_p_get_set_and_invalid(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/min_p")
    assert "not set" in last(app)

    await submit(app, pilot, "/min_p 0.05")
    assert app.min_p == 0.05

    await submit(app, pilot, "/min_p notanumber")
    assert "must be a number" in last(app)


async def test_top_k_get_set_and_invalid(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/top_k 40")
    assert app.top_k == 40

    await submit(app, pilot, "/top_k notanumber")
    assert "must be an integer" in last(app)


async def test_timeout_get_set_and_invalid(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/timeout 60")
    assert app.timeout == 60

    await submit(app, pilot, "/timeout notanumber")
    assert "must be an integer" in last(app)


async def test_system_prompt_get_set_clears_persona(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/persona coder")
    assert app.persona == "coder"

    await submit(app, pilot, "/system_prompt something totally different")
    assert app.system_prompt == "something totally different"
    assert app.persona is None


async def test_persona_switch_yaml_applies_all_fields(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/persona coder")
    assert app.persona == "coder"
    assert "expert coder" in app.system_prompt
    assert app.temperature == 0.1
    assert app.max_tokens == 1024
    assert app.llm.temperature == 0.1


async def test_persona_switch_txt_sets_prompt_only(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/persona concise")
    assert app.persona == "concise"
    assert "terse assistant" in app.system_prompt


async def test_persona_not_found(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/persona does-not-exist")
    assert "not found" in last(app).lower()


async def test_personas_lists_bundled_and_marks_current(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/persona pirate")
    await submit(app, pilot, "/personas")

    text = "\n".join(lines(app, 10))
    assert "coder" in text
    assert "pirate (current)" in text


# ---------------------------------------------------------------------------
# CONNECTION & CONFIG
# ---------------------------------------------------------------------------

async def test_backend(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/backend")
    text = "\n".join(lines(app, 3))
    assert app.backend in text
    assert app.api_base in text


async def test_provider(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/provider")
    assert app.backend in last(app)


async def test_config_no_args_shows_all_keys(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/config")
    text = "\n".join(lines(app, 9))

    from commands import CONFIG_KEYS

    for key in CONFIG_KEYS:
        assert f"{key}:" in text


async def test_config_get_valid_key(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/config model")
    assert last(app).startswith("model:")


async def test_config_get_invalid_key_lists_valid_ones(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/config base")
    text = last(app)
    assert "Unknown config item: base" in text
    assert "api_base" in text


async def test_config_set_valid_key_persists(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/config temperature 0.33")
    assert "temperature updated to: 0.33" in last(app)

    with open(app.config.filename) as f:
        data = yaml.safe_load(f)
    assert data["llm"]["temperature"] == "0.33"


async def test_config_set_invalid_key_does_not_crash(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/config base http://example.com")
    assert "Unknown config item: base" in last(app)


async def test_config_set_readonly_key_does_not_crash(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/config api_key somevalue")
    assert "Unknown config item: api_key" in last(app)


async def test_reload_rereads_config_and_syncs_llm(app_pilot):
    app, pilot = app_pilot

    with open(app.config.filename) as f:
        data = yaml.safe_load(f)
    data["llm"]["model"] = "reloaded-model"
    data["llm"]["temperature"] = 0.77
    with open(app.config.filename, "w") as f:
        yaml.safe_dump(data, f)

    await submit(app, pilot, "/reload")

    assert app.model == "reloaded-model"
    assert app.llm.model == "reloaded-model"
    assert app.temperature == 0.77
    assert app.llm.temperature == 0.77
    assert "reloaded" in last(app).lower()


# ---------------------------------------------------------------------------
# SESSION
# ---------------------------------------------------------------------------

async def test_session_info(app_pilot):
    app, pilot = app_pilot
    app.message_count = 3
    await submit(app, pilot, "/session")
    text = "\n".join(lines(app, 6))
    assert app.model in text
    assert "3" in text


async def test_permissions_empty_by_default(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/permissions")
    text = "\n".join(lines(app, 6))
    assert "No tools are set to always-allow" in text
    assert "edit_file" in text


async def test_permissions_lists_allowed_tools(app_pilot):
    app, pilot = app_pilot
    app.allowed_tools.add("edit_file")
    await submit(app, pilot, "/permissions")
    text = "\n".join(lines(app, 8))
    assert "Always-allowed this session" in text
    assert "edit_file" in text


async def test_permissions_revoke_one(app_pilot):
    app, pilot = app_pilot
    app.allowed_tools.update({"edit_file", "write_file"})
    await submit(app, pilot, "/permissions revoke edit_file")
    assert "Revoked always-allow for edit_file" in last(app)
    assert app.allowed_tools == {"write_file"}


async def test_permissions_revoke_unknown(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/permissions revoke edit_file")
    assert "not currently always-allowed" in last(app)


async def test_permissions_revoke_all(app_pilot):
    app, pilot = app_pilot
    app.allowed_tools.update({"edit_file", "write_file"})
    await submit(app, pilot, "/permissions revoke all")
    assert "Revoked 2 tool permission(s)" in last(app)
    assert app.allowed_tools == set()


async def test_history_empty_and_populated(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/history")
    assert "no messages" in last(app).lower()

    app.chat_log = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    await submit(app, pilot, "/history")
    text = "\n".join(lines(app, 4))
    assert "hello" in text
    assert "hi there" in text


async def test_save_list_show_load_delete_roundtrip(app_pilot):
    app, pilot = app_pilot
    app.chat_log = [
        {"role": "user", "content": "capital of france?"},
        {"role": "assistant", "content": "Paris."},
    ]

    await submit(app, pilot, "/save geo-test")
    assert "saved" in last(app).lower()

    await submit(app, pilot, "/list")
    assert "geo-test" in last(app) or "geo-test" in "\n".join(lines(app, 3))

    # switch to unrelated live state before showing/loading
    app.chat_log = [{"role": "user", "content": "unrelated"}]

    await submit(app, pilot, "/show geo-test")
    text = "\n".join(lines(app, 4))
    assert "Paris" in text
    assert app.chat_log == [{"role": "user", "content": "unrelated"}]  # /show must not mutate live state

    await submit(app, pilot, "/load geo-test")
    assert any(e["content"] == "Paris." for e in app.chat_log)

    await submit(app, pilot, "/delete geo-test")
    assert "deleted" in last(app).lower()

    await submit(app, pilot, "/show geo-test")
    assert "not found" in last(app).lower()


async def test_save_requires_name(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/save")
    assert "usage" in last(app).lower()


async def test_list_when_empty(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/list")
    assert "no saved sessions" in last(app).lower()


async def test_load_nonexistent(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/load does-not-exist")
    assert "not found" in last(app).lower()


async def test_delete_nonexistent(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/delete does-not-exist")
    assert "not found" in last(app).lower()


# ---------------------------------------------------------------------------
# FILES: /ls
# ---------------------------------------------------------------------------

async def test_ls_default_hides_dotfiles(app_pilot, tmp_path):
    app, pilot = app_pilot
    (tmp_path / "visible.txt").write_text("x")
    (tmp_path / ".hidden.txt").write_text("x")
    (tmp_path / "subdir").mkdir()

    await submit(app, pilot, f"/ls {tmp_path}")
    text = "\n".join(lines(app, 4))
    assert "visible.txt" in text
    assert "subdir/" in text
    assert ".hidden.txt" not in text


async def test_ls_dash_a_shows_dotfiles(app_pilot, tmp_path):
    app, pilot = app_pilot
    (tmp_path / ".hidden.txt").write_text("x")

    await submit(app, pilot, f"/ls -a {tmp_path}")
    assert ".hidden.txt" in "\n".join(lines(app, 3))


async def test_ls_dash_l_shows_size(app_pilot, tmp_path):
    app, pilot = app_pilot
    (tmp_path / "sized.txt").write_text("hello world")

    await submit(app, pilot, f"/ls -l {tmp_path}")
    text = "\n".join(lines(app, 3))
    assert "sized.txt" in text
    assert "11" in text  # byte count


async def test_ls_dash_t_and_dash_r(app_pilot, tmp_path):
    app, pilot = app_pilot
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text("x")
    new.write_text("x")
    os.utime(old, (1000000000, 1000000000))
    os.utime(new, (2000000000, 2000000000))

    await submit(app, pilot, f"/ls -t {tmp_path}")
    text = lines(app, 4)
    body = [l for l in text if "new.txt" in l or "old.txt" in l]
    assert body[0].strip() == "new.txt"  # newest first

    await submit(app, pilot, f"/ls -t -r {tmp_path}")
    text = lines(app, 4)
    body = [l for l in text if "new.txt" in l or "old.txt" in l]
    assert body[0].strip() == "old.txt"  # oldest first with -r


async def test_ls_missing_directory(app_pilot, tmp_path):
    app, pilot = app_pilot
    await submit(app, pilot, f"/ls {tmp_path}/nope")
    assert "no such directory" in last(app).lower()


async def test_ls_not_a_directory(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "file.txt"
    f.write_text("x")
    await submit(app, pilot, f"/ls {f}")
    assert "not a directory" in last(app).lower()


async def test_ls_empty_directory(app_pilot, tmp_path):
    app, pilot = app_pilot
    empty = tmp_path / "empty"
    empty.mkdir()
    await submit(app, pilot, f"/ls {empty}")
    assert "is empty" in last(app).lower()


# ---------------------------------------------------------------------------
# FILES: /tree
# ---------------------------------------------------------------------------

async def test_tree_default(app_pilot, tmp_path):
    app, pilot = app_pilot
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("x")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.pyc").write_text("x")

    await submit(app, pilot, f"/tree {tmp_path}")
    text = "\n".join(lines(app, 8))
    assert "a.py" in text
    assert "sub/" in text
    assert "b.py" in text
    assert "__pycache__" not in text


async def test_tree_dash_d_directories_only(app_pilot, tmp_path):
    app, pilot = app_pilot
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "sub").mkdir()

    await submit(app, pilot, f"/tree -d {tmp_path}")
    text = "\n".join(lines(app, 4))
    assert "sub/" in text
    assert "a.py" not in text


async def test_tree_dash_a_shows_hidden(app_pilot, tmp_path):
    app, pilot = app_pilot
    (tmp_path / ".hidden").write_text("x")

    await submit(app, pilot, f"/tree -a {tmp_path}")
    assert ".hidden" in "\n".join(lines(app, 4))


async def test_tree_dash_l_limits_depth(app_pilot, tmp_path):
    app, pilot = app_pilot
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.py").write_text("x")

    await submit(app, pilot, f"/tree -L 1 {tmp_path}")
    text = "\n".join(lines(app, 4))
    assert "sub/" in text
    assert "deep.py" not in text


async def test_tree_dash_l_invalid_value(app_pilot, tmp_path):
    app, pilot = app_pilot
    await submit(app, pilot, f"/tree -L notanumber {tmp_path}")
    assert "invalid value" in last(app).lower()


async def test_tree_missing_directory(app_pilot, tmp_path):
    app, pilot = app_pilot
    await submit(app, pilot, f"/tree {tmp_path}/nope")
    assert "no such directory" in last(app).lower()


# ---------------------------------------------------------------------------
# FILES: /grep
# ---------------------------------------------------------------------------

async def test_grep_finds_matches_with_line_numbers(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "sample.py"
    f.write_text("def hello():\n    print('hi')\n")

    await submit(app, pilot, f"/grep hello {f}")
    text = "\n".join(lines(app, 3))
    assert "sample.py:1" in text


async def test_grep_no_matches(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "sample.py"
    f.write_text("nothing here\n")

    await submit(app, pilot, f"/grep zzz_no_match {f}")
    assert "no matches" in last(app).lower()


async def test_grep_invalid_regex(app_pilot, tmp_path):
    app, pilot = app_pilot
    await submit(app, pilot, f"/grep [unterminated {tmp_path}")
    assert "invalid pattern" in last(app).lower()


async def test_grep_case_insensitive(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "sample.py"
    f.write_text("HELLO world\n")

    await submit(app, pilot, f"/grep -i hello {f}")
    assert "HELLO" in "\n".join(lines(app, 3))


async def test_grep_whole_word(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "sample.py"
    f.write_text("defaults\ndef foo():\n")

    await submit(app, pilot, f"/grep -w def {f}")
    text = "\n".join(lines(app, 3))
    assert "def foo" in text
    assert "defaults" not in text


async def test_grep_invert_match(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "sample.py"
    f.write_text("keep this\nmatch this\n")

    await submit(app, pilot, f"/grep -v match {f}")
    text = "\n".join(lines(app, 3))
    assert "keep this" in text
    assert "match this" not in text


async def test_grep_count_only(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "sample.py"
    f.write_text("x\nx\ny\n")

    await submit(app, pilot, f"/grep -c x {f}")
    assert f"{f}: 2" in "\n".join(lines(app, 3))


async def test_grep_files_with_matches_only(app_pilot, tmp_path):
    app, pilot = app_pilot
    (tmp_path / "a.py").write_text("target\n")
    (tmp_path / "b.py").write_text("nothing\n")

    await submit(app, pilot, f"/grep -l target {tmp_path}")
    text = "\n".join(lines(app, 3))
    assert "a.py" in text
    assert "b.py" not in text


async def test_grep_uses_ripgrep_when_available(app_pilot, tmp_path):
    app, pilot = app_pilot
    fake_result = type("R", (), {"returncode": 0, "stdout": "x.py:1:match\n", "stderr": ""})()

    with patch("shutil.which", return_value="/usr/bin/rg"), \
         patch("subprocess.run", return_value=fake_result) as mock_run:
        await submit(app, pilot, f"/grep -i pattern {tmp_path}")

    called_cmd = mock_run.call_args.args[0]
    assert called_cmd[0] == "rg"
    assert "-i" in called_cmd
    assert "match" in "\n".join(lines(app, 3))


# ---------------------------------------------------------------------------
# FILES: /cat
# ---------------------------------------------------------------------------

async def test_cat_displays_file(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "sample.py"
    f.write_text("print('hello')\n")

    await submit(app, pilot, f"/cat {f}")
    text = "\n".join(lines(app, 3))
    assert "print('hello')" in text
    assert str(f) in text


async def test_cat_preserves_brackets(app_pilot, tmp_path):
    """Regression test: Static() with markup=True silently eats '[...]' text."""
    app, pilot = app_pilot
    f = tmp_path / "typed.py"
    f.write_text("def f(x: List[str]) -> Optional[int]: ...\n")

    await submit(app, pilot, f"/cat {f}")
    text = "\n".join(lines(app, 3))
    assert "List[str]" in text
    assert "Optional[int]" in text


async def test_cat_file_not_found(app_pilot, tmp_path):
    app, pilot = app_pilot
    await submit(app, pilot, f"/cat {tmp_path}/nope.txt")
    assert "not found" in last(app).lower()


async def test_cat_requires_argument(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/cat")
    assert "usage" in last(app).lower()


# ---------------------------------------------------------------------------
# FILES: /read
# ---------------------------------------------------------------------------

async def test_read_no_files_loaded(app_pilot):
    app, pilot = app_pilot
    await submit(app, pilot, "/read")
    assert "no files loaded" in last(app).lower()


async def test_read_multiple_files_accumulate(app_pilot, tmp_path):
    app, pilot = app_pilot
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("content-a")
    b.write_text("content-b")

    await submit(app, pilot, f"/read {a} {b}")
    assert [cf["filename"] for cf in app.context_files] == [str(a), str(b)]

    prompt = app._build_system_prompt()
    assert "content-a" in prompt
    assert "content-b" in prompt


async def test_read_rereading_refreshes_not_duplicates(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "a.py"
    f.write_text("v1")
    await submit(app, pilot, f"/read {f}")

    f.write_text("v2")
    await submit(app, pilot, f"/read {f}")

    assert len(app.context_files) == 1
    assert app.context_files[0]["content"] == "v2"


async def test_read_clear(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "a.py"
    f.write_text("x")
    await submit(app, pilot, f"/read {f}")
    assert len(app.context_files) == 1

    await submit(app, pilot, "/read clear")
    assert app.context_files == []


async def test_read_missing_file(app_pilot, tmp_path):
    app, pilot = app_pilot
    await submit(app, pilot, f"/read {tmp_path}/nope.txt")
    assert "not found" in last(app)
    assert app.context_files == []


# ---------------------------------------------------------------------------
# FILES: /edit
# ---------------------------------------------------------------------------

async def test_edit_replaces_unique_text(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "a.py"
    f.write_text("hello world\n")

    await submit(app, pilot, f"/edit {f} hello -> goodbye")
    assert "Edited" in last(app)
    assert f.read_text() == "goodbye world\n"


async def test_edit_ambiguous_match_refuses(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "a.py"
    f.write_text("dup\ndup\n")

    await submit(app, pilot, f"/edit {f} dup -> single")
    assert "must be unique" in last(app)
    assert f.read_text() == "dup\ndup\n"


async def test_edit_text_not_found(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "a.py"
    f.write_text("hello\n")

    await submit(app, pilot, f"/edit {f} zzz -> yyy")
    assert "not found" in last(app).lower()


async def test_edit_missing_arrow_shows_usage(app_pilot, tmp_path):
    app, pilot = app_pilot
    f = tmp_path / "a.py"
    f.write_text("hello\n")

    await submit(app, pilot, f"/edit {f} just some text")
    assert "usage" in last(app).lower()


async def test_edit_file_not_found(app_pilot, tmp_path):
    app, pilot = app_pilot
    await submit(app, pilot, f"/edit {tmp_path}/nope.py hello -> goodbye")
    assert "file not found" in last(app).lower()


# ---------------------------------------------------------------------------
# FILES: /write and /diff
# ---------------------------------------------------------------------------

RESPONSE_WITH_CODE = (
    "Here's a function:\n\n"
    "```python\n"
    "def hello():\n"
    "    print('hi')\n"
    "```\n"
)


async def test_write_full_response(app_pilot, tmp_path):
    app, pilot = app_pilot
    app.chat_log = [{"role": "assistant", "content": RESPONSE_WITH_CODE}]
    target = tmp_path / "out.txt"

    await submit(app, pilot, f"/write {target}")
    assert target.read_text() == RESPONSE_WITH_CODE


async def test_write_code_only(app_pilot, tmp_path):
    app, pilot = app_pilot
    app.chat_log = [{"role": "assistant", "content": RESPONSE_WITH_CODE}]
    target = tmp_path / "out.py"

    await submit(app, pilot, f"/write code {target}")
    assert target.read_text() == "def hello():\n    print('hi')\n"


async def test_write_no_response_yet(app_pilot, tmp_path):
    app, pilot = app_pilot
    await submit(app, pilot, f"/write {tmp_path}/out.txt")
    assert "no ai response" in last(app).lower()


async def test_write_code_no_code_block(app_pilot, tmp_path):
    app, pilot = app_pilot
    app.chat_log = [{"role": "assistant", "content": "just prose, no code"}]

    await submit(app, pilot, f"/write code {tmp_path}/out.py")
    assert "no code block" in last(app).lower()


async def test_diff_against_existing_file(app_pilot, tmp_path):
    app, pilot = app_pilot
    app.chat_log = [{"role": "assistant", "content": RESPONSE_WITH_CODE}]
    target = tmp_path / "existing.py"
    target.write_text("def hello():\n    print('bye')\n")

    await submit(app, pilot, f"/diff {target}")
    text = "\n".join(lines(app, 8))
    assert "-    print('bye')" in text
    assert "+    print('hi')" in text
    assert target.read_text() == "def hello():\n    print('bye')\n"  # untouched


async def test_diff_against_new_file(app_pilot, tmp_path):
    app, pilot = app_pilot
    app.chat_log = [{"role": "assistant", "content": RESPONSE_WITH_CODE}]
    target = tmp_path / "brand_new.py"

    await submit(app, pilot, f"/diff {target}")
    text = "\n".join(lines(app, 8))
    assert "@@ -0,0" in text
    assert not target.exists()


async def test_diff_no_differences(app_pilot, tmp_path):
    app, pilot = app_pilot
    app.chat_log = [{"role": "assistant", "content": RESPONSE_WITH_CODE}]
    target = tmp_path / "same.py"
    target.write_text("def hello():\n    print('hi')\n")

    await submit(app, pilot, f"/diff {target}")
    assert "no differences" in last(app).lower()


# ---------------------------------------------------------------------------
# SECURITY: path traversal / injection regression tests
#
# /delete, /save, /load, /show (sessions) and /persona are meant to be
# sandboxed to their own directory -- unlike /cat, /read, /edit, /write,
# /ls, /tree, /grep, which are general-purpose file tools by design and
# intentionally operate on any path, same as any local dev tool.
# ---------------------------------------------------------------------------

TRAVERSAL_NAMES = [
    "../../../../../../etc/passwd",
    "../../../secret",
    "/etc/passwd",
]


@pytest.mark.parametrize("traversal", TRAVERSAL_NAMES)
async def test_delete_cannot_escape_sessions_dir(app_pilot, tmp_path, traversal):
    app, pilot = app_pilot
    canary = tmp_path / "canary.txt"
    canary.write_text("do not touch")

    await submit(app, pilot, f"/delete {traversal}")

    assert canary.exists()
    assert canary.read_text() == "do not touch"


async def test_save_load_show_use_basename_only(app_pilot, tmp_path):
    """A traversal-shaped session name must never read/write outside SESSIONS_DIR."""
    app, pilot = app_pilot
    canary = tmp_path / "canary.txt"
    canary.write_text("do not touch")
    traversal_name = f"../../../../../..{canary}"

    app.chat_log = [{"role": "user", "content": "hi"}]
    await submit(app, pilot, f"/save {traversal_name}")
    assert canary.read_text() == "do not touch"  # /save never wrote INTO the canary

    from commands import SESSIONS_DIR

    # the only thing that could have been created lives inside SESSIONS_DIR,
    # named after the basename of the traversal string -- never the real path
    sandboxed_name = os.path.basename(traversal_name) + ".json"
    assert os.path.isfile(os.path.join(SESSIONS_DIR, sandboxed_name))

    await submit(app, pilot, f"/show {traversal_name}")
    assert "hi" in "\n".join(lines(app, 4))  # finds the sandboxed file, not the canary

    await submit(app, pilot, f"/load {traversal_name}")
    assert canary.read_text() == "do not touch"  # still untouched


@pytest.mark.parametrize("traversal", TRAVERSAL_NAMES)
async def test_persona_cannot_escape_personas_dir(app_pilot, traversal):
    app, pilot = app_pilot
    await submit(app, pilot, f"/persona {traversal}")
    assert "not found" in last(app).lower()


async def test_grep_ripgrep_invocation_never_uses_a_shell(app_pilot, tmp_path):
    """subprocess.run must be called with an argv list, never shell=True,
    so pattern/path text can never be interpreted as shell syntax."""
    app, pilot = app_pilot
    fake_result = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with patch("shutil.which", return_value="/usr/bin/rg"), \
         patch("subprocess.run", return_value=fake_result) as mock_run:
        await submit(app, pilot, f"/grep '; rm -rf /' {tmp_path}")

    args, kwargs = mock_run.call_args
    assert isinstance(args[0], list)  # argv list, not a shell string
    assert kwargs.get("shell") is not True


async def test_edit_does_not_treat_old_text_as_regex(app_pilot, tmp_path):
    """cmd_edit uses str.count/str.replace, not re -- regex metacharacters
    in <old text> must be treated as literal text, not a pattern."""
    app, pilot = app_pilot
    f = tmp_path / "a.py"
    f.write_text("price: $5.00 (was .*)\n")

    await submit(app, pilot, f"/edit {f} $5.00 -> $6.00")
    assert f.read_text() == "price: $6.00 (was .*)\n"
