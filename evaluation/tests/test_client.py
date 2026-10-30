import io
import json
from urllib.error import HTTPError

import pytest

from evaluation.client import DeepSeekClient, load_config


def test_config_uses_own_env_file(tmp_path, monkeypatch):
    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=test-secret\nDEEPSEEK_MODEL=chosen\n")
    config = load_config(tmp_path)
    assert config["api_key"] == "test-secret"
    assert config["model"] == "chosen"
    assert config["temperature"] == 0
    assert "api_key" not in DeepSeekClient(config).settings


def test_request_contract_and_response():
    received = {}
    def transport(request, timeout):
        received.update(json.loads(request.data))
        return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "Hello."}}]}).encode())
    client = DeepSeekClient({"api_key": "secret", "model": "fake", "base_url": "https://example.com", "temperature": 0}, opener=transport)
    assert client.complete("hello", "Edit") == "Hello."
    assert received == {"model": "fake", "temperature": 0, "stream": False,
                        "messages": [{"role": "system", "content": "Edit"}, {"role": "user", "content": "hello"}]}


@pytest.mark.parametrize("body", [
    {"choices": []},
    {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]},
])
def test_invalid_or_truncated_response_is_failure(body):
    client = DeepSeekClient({"api_key": "secret", "model": "fake", "base_url": "https://example.com"},
                            opener=lambda *a, **k: io.BytesIO(json.dumps(body).encode()))
    with pytest.raises(ValueError):
        client.complete("rough", "Edit")


def test_error_does_not_expose_provider_body_or_key():
    def transport(*args, **kwargs):
        raise HTTPError("https://example.com", 401, "secret", {}, io.BytesIO(b"secret transcript"))
    client = DeepSeekClient({"api_key": "secret", "model": "fake", "base_url": "https://example.com"}, opener=transport)
    with pytest.raises(ValueError) as error:
        client.complete("rough", "Edit")
    assert "401" in str(error.value) and "secret" not in str(error.value)
