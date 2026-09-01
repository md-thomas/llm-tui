import os
import yaml
from dotenv import load_dotenv

from paths import user_dir, resolve_file

load_dotenv()


class Config:

    def __init__(self, filename="config.yaml"):
        self.user_path = os.path.join(user_dir(), filename)
        self.filename = resolve_file(filename, bundled_path=filename)

        with open(self.filename) as f:
            self.data = yaml.safe_load(f)

    @property
    def api_base(self):
        return self.data["connection"]["api_base"]

    @api_base.setter
    def api_base(self, value):
        self.data["connection"]["api_base"] = value

    @property
    def timeout(self):
        return self.data["connection"]["timeout"]

    @timeout.setter
    def timeout(self, value):
        self.data["connection"]["timeout"] = int(value)

    @property
    def backend(self):
        return self.data["llm"]["provider"]

    @backend.setter
    def backend(self, value):
        self.data["llm"]["provider"] = value

    @property
    def model(self):
        return self.data["llm"]["model"]

    @model.setter
    def model(self, value):
        self.data["llm"]["model"] = value

    @property
    def temperature(self):
        return self.data["llm"]["temperature"]

    @temperature.setter
    def temperature(self, value):
        self.data["llm"]["temperature"] = value

    @property
    def max_tokens(self):
        return self.data["llm"]["max_tokens"]

    @max_tokens.setter
    def max_tokens(self, value):
        self.data["llm"]["max_tokens"] = int(value)

    @property
    def context_window(self):
        return self.data["llm"].get("context_window", 8192)

    @context_window.setter
    def context_window(self, value):
        self.data["llm"]["context_window"] = int(value)

    @property
    def tools_enabled(self):
        return self.data["llm"].get("tools_enabled", True)

    @tools_enabled.setter
    def tools_enabled(self, value):
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "yes", "on")

        self.data["llm"]["tools_enabled"] = bool(value)


    # only the key comes from environment variable
    @property
    def api_key(self):
        return os.getenv("OPENAI_API_KEY")

    def get(self, key):
        if not hasattr(self, key):
            raise KeyError(key)

        return getattr(self, key)

    def set(self, key, value):
        if not hasattr(self, key):
            raise KeyError(key)

        setattr(self, key, value)

        self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.user_path), exist_ok=True)

        with open(self.user_path, "w") as f:
            yaml.safe_dump(self.data, f, sort_keys=False)

        self.filename = self.user_path

