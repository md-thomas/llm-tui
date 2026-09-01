import os
from platformdirs import user_config_dir

APP_NAME = "llm-tui"


def user_dir():
    return user_config_dir(APP_NAME)


def resolve_file(filename, bundled_path=None):
    """Return the user override path if it exists, else the bundled default."""
    user_path = os.path.join(user_dir(), filename)

    if os.path.isfile(user_path):
        return user_path

    return bundled_path if bundled_path is not None else filename


def search_dirs(subdir):
    """User dir first, then the bundled dir, in priority order."""
    return [os.path.join(user_dir(), subdir), subdir]
