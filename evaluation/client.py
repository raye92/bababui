"""Evaluation-owned DeepSeek transport; no editor imports or environment mutation."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urlparse

from dotenv import dotenv_values


def load_config(root):
    values = dotenv_values(Path(root) / ".env")
    def value(key, default=""):
        return os.environ.get(key, values.get(key) or default)
    return {"api_key": value("DEEPSEEK_API_KEY"),
            "base_url": value("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "model": value("DEEPSEEK_MODEL", "deepseek-chat"),
            "temperature": 0, "timeout_seconds": 180}


class DeepSeekClient:
    def __init__(self, config, opener=None):
        self.api_key = config.get("api_key", "")
        self.settings = {"base_url": config.get("base_url", "https://api.deepseek.com"),
                         "model": config.get("model", "deepseek-chat"),
                         "temperature": 0, "timeout_seconds": config.get("timeout_seconds", 180)}
        self.opener = opener or urllib.request.urlopen

    @property
    def ready(self):
        return bool(self.api_key.strip()) and self.api_key != "your_deepseek_api_key_here"

    def complete(self, text, system_prompt):
        if not self.ready:
            raise ValueError("Set DEEPSEEK_API_KEY in evaluation/.env.")
        endpoint = self.settings["base_url"].rstrip("/") + "/chat/completions"
        url = urlparse(endpoint)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("DEEPSEEK_BASE_URL must be an HTTPS URL without credentials, query, or fragment.")
        payload = {"model": self.settings["model"], "temperature": 0, "stream": False,
                   "messages": [{"role": "system", "content": system_prompt},
                                {"role": "user", "content": text}]}
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Authorization": f"Bearer {self.api_key}",
                                                  "Content-Type": "application/json"}, method="POST")
        try:
            with self.opener(request, timeout=self.settings["timeout_seconds"]) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ValueError(f"DeepSeek returned HTTP {exc.code}. Check credentials, quota, or service status.") from None
        except (urllib.error.URLError, OSError):
            raise ValueError("Could not reach DeepSeek or the request timed out. Retry explicitly when ready.") from None
        except (ValueError, UnicodeError):
            raise ValueError("DeepSeek returned invalid JSON.") from None
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("DeepSeek did not finish normally; the response may be truncated.")
            text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("DeepSeek returned an empty response.")
            return text
        except (KeyError, IndexError, TypeError):
            raise ValueError("DeepSeek returned an unexpected response structure.") from None
