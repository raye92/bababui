"""Immutable model/audio caches, resumable segments, and Gemini transport."""
import hashlib
from pathlib import Path
import tempfile
import time
import uuid

from evaluation import media
from evaluation.storage import encoded, file_lock, read_json, write_json, resolve

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
            raise ValueError("Set GEMINI_API_KEY in evaluation/.env for new transcriptions.")
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


class Transcriptions:
    def __init__(self, store):
        self.root = store.root

    def directory(self, audio, model):
        import re
        if model not in AUDIO_MODELS or not re.fullmatch(r"[0-9a-f]{64}", audio["sha256"]):
            raise ValueError("Invalid transcription model or audio identity.")
        return self.root / "transcriptions" / model / "speakers-v1" / audio["sha256"]

    def cached(self, audio, model):
        path = self.directory(audio, model) / "complete.json"
        if not path.exists():
            return None
        data = path.read_bytes()
        reference = {"path": path.relative_to(self.root).as_posix(), "sha256": hashlib.sha256(data).hexdigest()}
        record = resolve(self.root, reference)
        if not isinstance(record.get("text"), str) or not record["text"].strip():
            raise ValueError("Invalid completed transcription cache.")
        return reference

    def plan(self, audio, model):
        directory = self.directory(audio, model)
        with file_lock(directory / "cache.lock"):
            manifest = directory / "segments.json"
            if manifest.exists():
                return read_json(manifest)
            path = self.root / audio["path"]
            if not path.is_file():
                raise ValueError("Missing managed WAV.")
            segments = media.plan_segments(audio["duration"], lambda start, end: media.silences(path, start, end))
            record = {"segments": segments, "audio_sha256": audio["sha256"], "model": model}
            write_json(manifest, record)
            return record

    def ensure(self, audio, model, client, failures=None):
        cached = self.cached(audio, model)
        if cached:
            self.cleanup_pending(audio, model, client)
            return cached
        key = (model, audio["sha256"])
        if failures is not None and key in failures:
            raise ValueError(failures[key])
        plan = self.plan(audio, model)
        directory = self.directory(audio, model)
        with file_lock(directory / "cache.lock"):
            cached = self.cached(audio, model)
            if cached:
                return cached
            state_path = directory / "state.json"
            state = read_json(state_path) if state_path.exists() else {"remote": None, "warnings": []}
            def remote(name):
                state["remote"] = name
                write_json(state_path, state)
            def warning(message):
                state["warnings"].append(message)
                write_json(state_path, state)
            def cleanup():
                if state.get("remote"):
                    if client is None:
                        warning("Remote cleanup remains pending until a transcription client is available.")
                    else:
                        try:
                            client.delete(state["remote"])
                            remote(None)
                        except Exception:
                            warning("Could not clean up the previous remote upload.")
                            raise ValueError("Remote cleanup must succeed before another segment upload.")
            try:
                # Also clean up when all segment text was saved before a crash.
                # Failure must not prevent using already completed local text.
                if client is not None and state.get("remote"):
                    try:
                        cleanup()
                    except ValueError:
                        pass
                texts = []
                for index, segment in enumerate(plan["segments"]):
                    saved = directory / f"segment-{index:04d}.json"
                    if saved.exists():
                        text = read_json(saved)["text"]
                        if not isinstance(text, str) or not text.strip():
                            raise ValueError("Invalid saved segment transcription.")
                    else:
                        if client is None:
                            raise ValueError("New transcription requires GEMINI_API_KEY.")
                        cleanup()
                        with tempfile.TemporaryDirectory(prefix="evaluation-audio-") as temporary:
                            path = Path(temporary) / "segment.wav"
                            media.prepare(self.root / audio["path"], segment, path)
                            text = client.transcribe(path, model, remote, warning)
                            if not isinstance(text, str) or not text.strip():
                                raise ValueError("Audio transcription returned empty text.")
                            write_json(saved, {"text": text})
                    texts.append(text)
                text, flags = media.join_segments(texts, [s["overlap"] for s in plan["segments"]])
                write_json(directory / "complete.json", {"text": text, "model": model,
                           "audio_sha256": audio["sha256"], "boundary_flags": flags,
                           "warnings": state["warnings"]})
            except Exception as exc:
                if failures is not None:
                    failures[key] = str(exc)
                raise
        return self.cached(audio, model)

    def cleanup_pending(self, audio, model, client):
        if client is None:
            return
        directory = self.directory(audio, model)
        with file_lock(directory / "cache.lock"):
            state_path = directory / "state.json"
            if state_path.exists():
                state = read_json(state_path)
                if state.get("remote"):
                    try:
                        client.delete(state["remote"])
                        state["remote"] = None
                    except Exception:
                        state["warnings"].append("Remote cleanup remains pending.")
                    write_json(state_path, state)


def workload(store, cases, setups):
    if cases:
        store.check_audio(cases)
    service, jobs = Transcriptions(store), {}
    for setup in setups:
        model = setup.get("transcription_model", DEFAULT_AUDIO_MODEL)
        for case in cases:
            jobs[(model, case["audio"]["sha256"])] = case["audio"]
    counts = {"recordings": 0, "requests": 0, "cached": 0, "prompts": len(cases) * len(setups)}
    recordings = set()
    for (model, sha), audio in jobs.items():
        if service.cached(audio, model):
            counts["cached"] += 1
            continue
        plan = service.plan(audio, model)
        missing = sum(not (service.directory(audio, model) / f"segment-{i:04d}.json").exists()
                      for i in range(len(plan["segments"])))
        if missing:
            recordings.add(sha)
            counts["requests"] += missing
    counts["recordings"] = len(recordings)
    if counts["requests"]:
        media.executable("ffmpeg")
    return counts


def retry_workload(store, run):
    pending = [r for r in run["results"] if r["status"] != "success"]
    unresolved = set()
    for result in pending:
        if "transcription" in result:
            resolve(store.root, result["transcription"])
        else:
            unresolved.add(result["case_id"])
        if "request" in result:
            resolve(store.root, result["request"])
    selected = [c for c in run["dataset"]["cases"] if c["id"] in {r["case_id"] for r in pending}]
    if selected:
        store.check_audio(selected)
    counts = workload(store, [c for c in selected if c["id"] in unresolved], [run["prompt"]])
    counts["prompts"] = len(pending)
    return counts


def preflight(counts, config):
    if not has_key(config.get("api_key")):
        raise ValueError("Set DEEPSEEK_API_KEY to run editing prompts.")
    if counts["requests"] > 0 and not has_key(config.get("gemini_api_key")):
        raise ValueError("Set GEMINI_API_KEY for new transcription requests.")
