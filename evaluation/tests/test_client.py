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
    assert config["timeout_seconds"] == 180
    assert "api_key" not in DeepSeekClient(config).settings


def test_request_contract_and_response():
    received = {}
    def transport(request, timeout):
        assert timeout == 180
        received.update(json.loads(request.data))
        return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "Hello."}}]}).encode())
    client = DeepSeekClient({"api_key": "secret", "model": "fake", "base_url": "https://example.com", "temperature": 0}, opener=transport)
    assert client.complete("hello", "Edit") == "Hello."
    assert received == {"model": "fake", "temperature": 0, "stream": False, "max_tokens": 16384,
                        "messages": [{"role": "system", "content": "Edit"}, {"role": "user", "content": "hello"}]}


@pytest.mark.parametrize("body", [
    {"choices": []},
    {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]},
])
def test_invalid_or_empty_response_is_failure(body):
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


def test_revision_payload_order_and_legacy_retry(tmp_path):
    from evaluation.core import Store, create_run, execute_run
    from evaluation.storage import artifact, resolve
    from evaluation.tests.audio_helpers import save_dataset

    store = Store(tmp_path)
    dataset = save_dataset(store, "Test", [{"id": "x", "input": "rough\nsecond line", "output": "SECRET REVIEWED OUTPUT"}])
    setup = store.save_prompt("Edit", "Instructions", "Court rules")
    received = []

    def transport(request, timeout):
        received.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "Revised."}}]}).encode())

    client = DeepSeekClient({"api_key": "fake", "base_url": "https://example.com"}, opener=transport)
    run = create_run(store, dataset, setup, "development", {})
    saved = execute_run(store, run["id"], client)
    result = saved["results"][0]
    assert result["status"] == "success"
    request = resolve(tmp_path, result["request"])
    assert request["user"] == "# AI transcription reference\nAudio reference\n\n# Original transcript\nrough\nsecond line"
    assert request["system"] == setup["system_prompt"]
    assert "omit prefatory notice information" not in request["system"]
    assert received[0]["messages"] == [{"role": "system", "content": request["system"]},
                                        {"role": "user", "content": request["user"]}]
    assert "SECRET REVIEWED OUTPUT" not in json.dumps(received)

    # Simulate a failed historical run with the previous section order.
    legacy = {"system": request["system"], "user": "# Original transcript\nrough\nsecond line\n\n# AI transcription reference\nAudio reference"}
    reference = artifact(tmp_path, "requests", legacy)
    result.update(status="error", request=reference)
    store.write("runs", saved)
    before = (tmp_path / reference["path"]).read_bytes()
    retried = execute_run(store, run["id"], client, retry=True)
    assert retried["results"][0]["status"] == "success"
    assert retried["results"][0]["request"] == reference
    assert retried["results"][0]["transcription"] == result["transcription"]
    assert (tmp_path / reference["path"]).read_bytes() == before
    assert received[1]["messages"] == [{"role": "system", "content": legacy["system"]},
                                        {"role": "user", "content": legacy["user"]}]

@pytest.mark.parametrize('reason', ['length', 'content_filter', None, 'unexpected'])
def test_nonstop_text_is_accepted_and_saved(tmp_path, reason):
    from evaluation.core import Store, create_run, execute_run
    from evaluation.storage import resolve
    from evaluation.tests.audio_helpers import save_dataset
    store = Store(tmp_path)
    dataset = save_dataset(store, 'Test', [{'id': 'x', 'input': 'rough', 'output': 'Partial text'}])
    setup = store.save_prompt('Edit', 'Instructions', 'Rules')
    body = {'choices': [{'finish_reason': reason, 'message': {'content': 'Partial text'}}]}
    client = DeepSeekClient({'api_key': 'fake'}, opener=lambda *a, **k: io.BytesIO(json.dumps(body).encode()))
    run = create_run(store, dataset, setup, 'development', client.settings)
    saved = execute_run(store, run['id'], client)
    result = saved['results'][0]
    assert result['status'] == 'success'
    assert result['response'] == 'Partial text'
    assert result['finish_reason'] == reason
    assert str(reason) in result['response_warning']
    assert resolve(tmp_path, result['attempts'][0]['api_response']) == body


def test_empty_response_preserves_provider_reply(tmp_path):
    from evaluation.core import Store, create_run, execute_run
    from evaluation.storage import resolve
    from evaluation.tests.audio_helpers import save_dataset
    store = Store(tmp_path)
    dataset = save_dataset(store, 'Test', [{'id': 'x', 'input': 'rough', 'output': 'expected'}])
    setup = store.save_prompt('Edit', 'Instructions', 'Rules')
    body = {'choices': [{'finish_reason': 'length', 'message': {'content': '', 'reasoning_content': 'provider detail'}}]}
    client = DeepSeekClient({'api_key': 'fake'}, opener=lambda *a, **k: io.BytesIO(json.dumps(body).encode()))
    run = create_run(store, dataset, setup, 'development', client.settings)
    result = execute_run(store, run['id'], client)['results'][0]
    assert result['status'] == 'error'
    assert 'length' in result['error']
    assert resolve(tmp_path, result['api_response']) == body
