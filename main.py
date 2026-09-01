from app import LLMApp
from paths import user_dir
import logging
import os
import sys

os.makedirs(user_dir(), exist_ok=True)
log_path = os.path.join(user_dir(), "llm-tui.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_path),
    ]
)

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


if __name__ == "__main__":
    session_to_load = sys.argv[1] if len(sys.argv) > 1 else None
    app = LLMApp(session_to_load=session_to_load)
    app.run()

    if app.exit_session_name:
        print(
            f"Session saved as '{app.exit_session_name}'. "
            f"Resume with: ./llm-tui.sh {app.exit_session_name}"
        )