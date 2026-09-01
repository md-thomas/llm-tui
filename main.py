from app import LLMApp
from paths import user_dir
import logging
import os

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
    LLMApp().run()