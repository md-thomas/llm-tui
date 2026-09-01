import asyncio

from widgets.chat_input import ChatInput
from widgets.chat_history import ChatHistory


async def wait_for(app, pilot, predicate, timeout=5):
    """Poll until predicate(app) is true -- for commands that finish on a background worker."""
    elapsed = 0.0
    step = 0.05

    while elapsed < timeout:
        await pilot.pause()

        if predicate(app):
            return

        await asyncio.sleep(step)
        elapsed += step

    raise AssertionError(f"condition not met within {timeout}s")


async def submit(app, pilot, text):
    """Type a line into the input box and submit it, as a user would."""
    input_box = app.query_one("#input", ChatInput)
    input_box.focus()
    input_box.post_message(ChatInput.Submitted(text))
    await pilot.pause()


def lines(app, n=None):
    """Rendered text of the last n history entries (all of them if n is None)."""
    history = app.query_one("#history", ChatHistory)
    children = list(history.children)[-n:] if n else list(history.children)
    return [str(c.render()) for c in children]


def last(app):
    return lines(app, 1)[0]
