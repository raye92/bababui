from types import SimpleNamespace as NS
import pytest
from app.src.processing import ProcessingClient, MODELS, load_config


@pytest.mark.parametrize('model', list(MODELS))
def test_processing_sends_only_transcription_and_prompt(model):
    calls = []
    class DeepSeek:
        finish_reason = 'stop'
        def complete(self, text, prompt):
            calls.append((text, prompt))
            return 'Formatted'
    class Interactions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return NS(status='completed', output_text='Formatted')
    client = ProcessingClient({'api_key': 'fake', 'gemini_api_key': 'fake'}, model,
                              sdk=NS(interactions=Interactions()), deepseek=DeepSeek())
    assert client.complete('Speaker 1: Test.', 'Format only.') == 'Formatted'
    assert 'Speaker 1: Test.' in str(calls) and 'Format only.' in str(calls)


def test_truncated_response_is_rejected():
    sdk = NS(interactions=NS(create=lambda **kw: NS(status='incomplete', output_text='Partial')))
    client = ProcessingClient({'gemini_api_key': 'fake'}, 'gemini-3.8-flash', sdk=sdk)
    with pytest.raises(ValueError, match='complete'):
        client.complete('Text', 'Prompt')


def test_config_precedence(tmp_path, monkeypatch):
    (tmp_path / '.env').write_text('GEMINI_API_KEY=file-key\n', encoding='utf-8')
    monkeypatch.setenv('GEMINI_API_KEY', 'env-key')
    assert load_config(tmp_path)['gemini_api_key'] == 'env-key'


def test_gemini_real_sdk_formatting_contract():
    import httpx
    import json
    from google import genai
    requests = []
    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'status': 'completed', 'steps': [
            {'type': 'model_output', 'content': [{'type': 'text', 'text': 'Formatted'}]}]})
    with genai.Client(api_key='fake', http_options={'client_args': {
            'transport': httpx.MockTransport(transport)}}) as sdk:
        client = ProcessingClient({'gemini_api_key': 'fake'}, 'gemini-3.8-flash', sdk=sdk)
        assert client.complete('Speaker 1: Hello', 'Format only') == 'Formatted'
    assert requests[0]['input'] == 'Speaker 1: Hello'
    assert requests[0]['system_instruction'] == 'Format only'
    assert requests[0]['store'] is False
