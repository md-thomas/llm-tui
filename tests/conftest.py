"""
Shared pytest fixtures for the llm-tui command test suite.

IMPORTANT: XDG_CONFIG_HOME is redirected to an isolated temp directory
*before* anything under the project is imported. Several modules (notably
commands.SESSIONS_DIR) resolve the user config directory once at import
time, so setting the env var inside a fixture would be too late and would
leak test data into the real ~/.config/llm-tui/. This also means the real
user config/sessions/log are never touched by running the test suite.
"""

import os
import sys
import tempfile

_TEST_CONFIG_HOME = tempfile.mkdtemp(prefix="llm-tui-test-config-")
os.environ["XDG_CONFIG_HOME"] = _TEST_CONFIG_HOME

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shutil
import pytest

from app import LLMApp
from paths import user_dir
from widgets.chat_history import ChatHistory


@pytest.fixture(autouse=True)
def isolated_user_state():
    """
    Every test starts from a clean slate: no leftover sessions, and no
    user-level config.yaml override (so Config() always falls back to the
    bundled repo config.yaml, making tests independent of run order and of
    each other's /config or /reload writes).
    """
    from commands import SESSIONS_DIR

    user_config = os.path.join(user_dir(), "config.yaml")

    def _clean():
        shutil.rmtree(SESSIONS_DIR, ignore_errors=True)
        if os.path.exists(user_config):
            os.remove(user_config)

    _clean()
    yield
    _clean()


@pytest.fixture
async def app_pilot():
    app = LLMApp()

    async with app.run_test() as pilot:
        yield app, pilot


@pytest.fixture
def history(app_pilot):
    app, _ = app_pilot
    return app.query_one("#history", ChatHistory)
