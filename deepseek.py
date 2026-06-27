"""DeepSeek integration: config loading + API client.

Loads credentials from `.env` and exposes a thin client over the DeepSeek
chat-completions endpoint. The request logic is intentionally stubbed for now
— the surface is defined so the UI can wire up the DEEPSEEK button, and the
network/parsing code can be filled in later without touching callers.
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Read `.env` from the repo root once on import. Values already present in the
# real environment win over the file, which is the usual dotenv contract.
load_dotenv()

# System prompt sent above the transcript on every DeepSeek call
_PROMPT_FILE = Path(__file__).resolve().parent / "AI Quality Analysis Prompt.md"
SYSTEM_PROMPT = _PROMPT_FILE.read_text(encoding="utf-8")


class DeepSeekError(Exception):
    """Raised when a DeepSeek request fails or the client is misconfigured."""


@dataclass(frozen=True)
class DeepSeekConfig:
    """Resolved settings needed to talk to the DeepSeek API."""

    api_key: str
    base_url: str
    model: str

    def is_configured(self) -> bool:
        """True only when a real (non-placeholder) API key is present."""
        return bool(self.api_key) and self.api_key != "your_deepseek_api_key_here"


def load_deepseek_config() -> DeepSeekConfig:
    """Build a `DeepSeekConfig` from environment variables.

    Falls back to the public defaults for the base URL and model so a missing
    optional value never crashes the app.
    """
    return DeepSeekConfig(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    )


class DeepSeekClient:
    """Sends prompts to DeepSeek and returns the model's text response."""

    def __init__(self, config: DeepSeekConfig | None = None):
        # Allow injecting a config (e.g. in tests); otherwise load from env.
        self._config = config or load_deepseek_config()

    @property
    def config(self) -> DeepSeekConfig:
        return self._config

    def is_ready(self) -> bool:
        """True when the client has enough configuration to make a request."""
        return self._config.is_configured()

    def complete(self, prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
        """Return the model completion for a single prompt.

        Args:
            prompt: The user message / text to send to the model.
            system_prompt: System instruction prepended to the chat. Defaults
                to the module-level SYSTEM_PROMPT.

        Returns:
            The model's text response.

        Raises:
            DeepSeekError: If the client is not configured or the request fails.
        """
        if not self.is_ready():
            raise DeepSeekError(
                "DeepSeek is not configured. Set DEEPSEEK_API_KEY in your .env file.")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self._config.model,
            "messages": messages,
            "stream": False,
        }).encode("utf-8")

        url = self._config.base_url.rstrip("/") + "/chat/completions"
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DeepSeekError(f"DeepSeek API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise DeepSeekError(f"Could not reach DeepSeek: {exc.reason}") from exc

        try:
            data = json.loads(body)
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise DeepSeekError(
                f"Unexpected DeepSeek response: {body[:500]}") from exc
