"""Provider-neutral formatting, with one editable prompt."""
from pathlib import Path

from evaluation.client import DeepSeekClient, load_config as read_config
from evaluation.transcription import has_key

MODELS = {
    'deepseek-flash': 'DeepSeek V4',
    'deepseek-v4-pro': 'DeepSeek V4 Pro',
    'gemini-3.8-flash': 'Gemini 3.8 Flash',
    'gemini-4-argon': 'Gemini 4 Argon',
}
DEFAULT_MODEL = 'gemini-3.8-flash'
APP_DIR = Path(__file__).resolve().parents[1]
PROMPT_FILE = Path(__file__).with_name('bababui_prompt.md')


def load_config(root=APP_DIR):
    return read_config(root)


class ProcessingClient:
    def __init__(self, config, model, sdk=None, deepseek=None):
        if model not in MODELS:
            raise ValueError('Select a supported processing model.')
        self.config, self.model, self.sdk = config, model, sdk
        self.deepseek = deepseek

    def check_ready(self):
        key = 'gemini_api_key' if self.model.startswith('gemini-') else 'api_key'
        if not has_key(self.config.get(key)):
            name = 'GEMINI_API_KEY' if key == 'gemini_api_key' else 'DEEPSEEK_API_KEY'
            raise ValueError(f'Set {name} in app/.env.')

    def complete(self, text, prompt):
        self.check_ready()
        if not text.strip() or not prompt.strip():
            raise ValueError('Transcription and formatting prompt must not be empty.')
        if self.model.startswith('deepseek-'):
            client = self.deepseek or DeepSeekClient({**self.config, 'model': self.model,
                                                     'max_tokens': 65536, 'timeout_seconds': 1800})
            output = client.complete(text, prompt)
            if client.finish_reason != 'stop':
                raise ValueError('Formatting did not complete. Retry or select another model.')
        else:
            if self.sdk is None:
                from google import genai
                self.sdk = genai.Client(api_key=self.config['gemini_api_key'],
                    http_options={'timeout': 1800000, 'retry_options': {'attempts': 1}})
            response = self.sdk.interactions.create(model=self.model, input=text,
                system_instruction=prompt, store=False, automatic_continuation=False,
                generation_config={'max_output_tokens': 65536}, timeout=1800)
            if getattr(response.status, 'value', response.status) != 'completed':
                raise ValueError('Formatting did not complete. Retry or select another model.')
            output = response.output_text
        if not isinstance(output, str) or not output.strip():
            raise ValueError('Formatting returned empty text. Existing text was preserved.')
        return output
