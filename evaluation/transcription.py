"""Immutable transcription caches and resumable segments."""
import hashlib
from pathlib import Path
import tempfile

from shared import media
from shared.storage import encoded, file_lock, read_json, write_json
from shared.transcription import AUDIO_MODELS, DEFAULT_AUDIO_MODEL, has_key
from evaluation.storage import resolve


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
