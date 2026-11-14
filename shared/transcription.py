"""Gemini transport and speaker annotation rendering."""
import time
import uuid

AUDIO_MODELS = ("gemini-3.5-transcribe", "gemini-3.8-flash")
DEFAULT_AUDIO_MODEL = AUDIO_MODELS[0]


def has_key(key):
    return bool(key and key.strip() and not key.startswith("your_"))


def speaker_text(response):
    """Render ASR annotations as turns without reconstructing the spoken words."""
    labels, blocks = {}, []
    for step in getattr(response, "steps", None) or []:
        if getattr(step, "type", None) != "model_output":
            continue
        for block in getattr(step, "content", None) or []:
            if getattr(block, "type", None) != "text":
                continue
            raw = block.text.encode("utf-8")
            turns, previous = [], None
            for annotation in getattr(block, "annotations", None) or []:
                speaker = getattr(annotation, "speaker", None)
                if getattr(annotation, "type", None) != "word_info" or not speaker:
                    continue
                start = annotation.start_index
                if not isinstance(start, int) or not 0 <= start < len(raw):
                    raise ValueError("Invalid speaker annotation offset.")
                if turns and start < turns[-1][0]:
                    raise ValueError("Speaker annotations are out of order.")
                if speaker != previous:
                    label = labels.setdefault(speaker, f"Speaker {len(labels) + 1}")
                    turns.append((start, label))
                    previous = speaker
            if not turns:
                blocks.append(block.text)
                continue
            parts = []
            if turns[0][0]:
                parts.append(raw[:turns[0][0]].decode("utf-8").strip())
            for index, (start, label) in enumerate(turns):
                end = turns[index + 1][0] if index + 1 < len(turns) else len(raw)
                parts.append(f"{label}: {raw[start:end].decode('utf-8').strip()}")
            blocks.append("\n".join(part for part in parts if part))
    return "\n".join(blocks) if blocks else response.output_text


class GeminiTranscriber:
    def __init__(self, key, sdk=None):
        self.key, self.sdk = key, sdk
        self.api_seconds = 0.0

    def client(self):
        if not has_key(self.key):
            raise ValueError("Set GEMINI_API_KEY in the environment or the app .env file for new transcriptions.")
        if self.sdk is None:
            from google import genai
            self.sdk = genai.Client(api_key=self.key, http_options={"timeout": 1800000,
                                       "retry_options": {"attempts": 1}})
        return self.sdk

    def delete(self, name):
        try:
            self.client().files.delete(name=name)
        except Exception as exc:
            if getattr(exc, "code", None) != 404:
                raise ValueError("Could not delete a remote audio segment.") from None

    def transcribe(self, path, model, remote, warning):
        sdk, uploaded = self.client(), None
        remote_name = "files/" + uuid.uuid4().hex
        remote(remote_name)
        try:
            uploaded = sdk.files.upload(file=str(path), config={"mime_type": "audio/wav", "name": remote_name})
            remote_name = uploaded.name
            remote(uploaded.name)
            deadline = time.monotonic() + 300
            while str(getattr(uploaded.state, "value", uploaded.state)).upper() == "PROCESSING":
                if time.monotonic() > deadline:
                    raise ValueError("Audio upload processing timed out.")
                time.sleep(1)
                uploaded = sdk.files.get(name=uploaded.name)
            if str(getattr(uploaded.state, "value", uploaded.state)).upper() not in ("ACTIVE", "NONE"):
                raise ValueError("Audio upload processing failed.")
            audio = {"type": "audio", "uri": uploaded.uri, "mime_type": "audio/wav"}
            kwargs = {"model": model, "input": [audio], "store": False}
            if model == DEFAULT_AUDIO_MODEL:
                kwargs["generation_config"] = {"transcription_config": {
                    "mode": {"type": "verbatim", "diarization_mode": "speaker"}}}
            else:
                kwargs["input"].insert(0, {"type": "text", "text":
                    "Transcribe all spoken words verbatim, including repetitions and false starts. "
                    "Label each speaker turn as Speaker 1, Speaker 2, etc., using consistent labels within this recording. "
                    "Do not guess speaker names. Return only the complete transcript with speaker labels. No summary or timestamps."})
            started = time.perf_counter()
            try:
                response = sdk.interactions.create(**kwargs, automatic_continuation=False, timeout=1800)
            finally:
                self.api_seconds += time.perf_counter() - started
            status = getattr(response, "status", None)
            if getattr(status, "value", status) != "completed":
                raise ValueError("Audio transcription did not complete; it may be truncated.")
            text = speaker_text(response)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Audio transcription returned empty text.")
            return text
        except Exception:
            raise ValueError("Gemini transcription failed or returned an incomplete response. Retry explicitly.") from None
        finally:
            if remote_name:
                try:
                    self.delete(remote_name)
                    remote(None)
                except Exception:
                    warning("Remote audio cleanup failed; it will be retried on the next explicit transcription action.")
