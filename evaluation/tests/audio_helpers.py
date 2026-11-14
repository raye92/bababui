"""Synthetic audio and precomputed references for non-network regression tests."""
import hashlib
import io
import wave

from shared.storage import write_json
from shared.transcription import AUDIO_MODELS
from evaluation.transcription import Transcriptions

stream = io.BytesIO()
with wave.open(stream, "wb") as handle:
    handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
    handle.writeframes(b"\0\0" * 1600)
WAV = stream.getvalue()
SHA = hashlib.sha256(WAV).hexdigest()
AUDIO = {"sha256": SHA, "path": f"audio/{SHA}.wav", "filename": "synthetic.wav", "duration": .1}


def seed(store):
    path = store.root / AUDIO["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(WAV)
    for model in AUDIO_MODELS:
        write_json(Transcriptions(store).directory(AUDIO, model) / "complete.json",
                   {"text": "Audio reference", "model": model, "audio_sha256": SHA,
                    "boundary_flags": [], "warnings": []})


def save_dataset(store, name, cases):
    seed(store)
    return store.save_dataset(name, [{**c, "audio": c.get("audio", AUDIO)} for c in cases])


def update_dataset(store, identifier, cases):
    return store.update_dataset(identifier, [{**c, "audio": c.get("audio", AUDIO)} for c in cases])


def original(text):
    return text.split("\n\n# Original transcript\n", 1)[1]
