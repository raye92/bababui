import io
import json
import wave

import pytest

from evaluation.imports import import_files
from evaluation.media import plan_segments, join_segments
from evaluation.core import Store




def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        handle.writeframes(b"\0\0" * 1600)
    return stream.getvalue()


@pytest.mark.parametrize("separator", ["_", "-", ".", " "])
def test_import_scoped_and_audio(tmp_path, separator):
    cases = import_files(Store(tmp_path), {"Case.TXT": b" hello\r\n", f"case{separator}ScOpEd.txt": b"Hello.\n",
                                          "CASE.wav": wav_bytes()})
    assert cases[0]["input"] == " hello\r\n"
    assert cases[0]["output"] == "Hello.\n"
    assert (tmp_path / cases[0]["audio"]["path"]).exists()
    assert cases[0]["audio"]["duration"] > 0


@pytest.mark.parametrize("files", [
    {"case.txt": b"hi", "caseXscoped.txt": b"Hi.", "case.wav": wav_bytes()},
    {"case.txt": b"hi", "case_scoped.txt": b"Hi."},
    {"case.txt": b"hi", "case_scoped.txt": b"Hi.", "case-scoped.txt": b"Hi.", "case.wav": wav_bytes()},
    {"case.txt": b"hi", "case_scoped.txt": b"Hi.", "case.wav": b"not audio"},
    {"case.txt": b"hi", "CASE.txt": b"Hi", "case_scoped.txt": b"Hi.", "case.wav": wav_bytes()},
])
def test_invalid_import_writes_nothing(tmp_path, files):
    with pytest.raises(ValueError):
        import_files(Store(tmp_path), files)
    assert list(tmp_path.iterdir()) == []


def test_boundaries_and_conservative_join():
    segments = plan_segments(3700, lambda start, end: [(start + 10, start + 12)])
    assert segments[0] == {"start": 0, "end": 1781.0, "overlap": False}
    fallback = plan_segments(3700, lambda start, end: [])
    assert fallback[1]["start"] == 1797
    assert all(s["end"] - s["start"] <= 1800 for s in fallback)
    text, flags = join_segments(["I heard one TWO three.", "one two three and four"], [False, True])
    assert text == "I heard one TWO three.\nand four"
    assert not flags
    text, flags = join_segments(["yes yes", "yes yes again"], [False, True])
    assert text == "yes yes\nyes yes again" and flags == [1]


def test_cache_retry_counts_and_references(tmp_path, monkeypatch):
    from evaluation.transcription import Transcriptions, workload
    from evaluation.storage import resolve
    store = Store(tmp_path)
    case = import_files(store, {"x.txt": b"hi", "x_scoped.txt": b"Hi.", "x.wav": wav_bytes()})[0]
    service = Transcriptions(store)
    calls = []
    class Client:
        def transcribe(self, path, model, remote, warning):
            calls.append(model)
            return "AI reference"
    ref = service.ensure(case["audio"], "gemini-3.5-transcribe", Client())
    assert resolve(tmp_path, ref)["text"] == "AI reference"
    assert service.ensure(case["audio"], "gemini-3.5-transcribe", None) == ref
    counts = workload(store, [case], [{"transcription_model": "gemini-3.5-transcribe"}] * 2)
    assert counts == {"recordings": 0, "requests": 0, "cached": 1, "prompts": 2}
    assert len(calls) == 1
    (tmp_path / ref["path"]).unlink()
    with pytest.raises(ValueError, match="Missing referenced"):
        resolve(tmp_path, ref)


def test_gemini_deletes_remote_on_failure(tmp_path):
    from types import SimpleNamespace
    from evaluation.transcription import GeminiTranscriber
    events = []
    class Files:
        def upload(self, **kwargs):
            return SimpleNamespace(name="files/test", uri="remote-uri", mime_type="audio/wav", state="ACTIVE")
        def delete(self, **kwargs):
            events.append(kwargs["name"])
    class Interactions:
        def create(self, **kwargs):
            raise OSError("failed")
    client = GeminiTranscriber("fake", sdk=SimpleNamespace(files=Files(), interactions=Interactions()))
    with pytest.raises(ValueError, match="transcription"):
        client.transcribe(tmp_path / "x.wav", "gemini-3.5-transcribe", lambda name: None, lambda text: None)
    assert events == ["files/test"]




def test_payload_references_and_missing_artifact_do_not_regenerate(tmp_path):
    from evaluation.core import create_run, execute_run
    from evaluation.storage import resolve
    from evaluation.tests.audio_helpers import save_dataset
    store = Store(tmp_path)
    dataset = save_dataset(store, "Test", [{"id": "x", "input": "rough", "output": "SECRET EXPECTED"}])
    setup = store.save_prompt("Edit", "Instructions", "Court rules")
    class Fake:
        def complete(self, text, prompt):
            assert "rough" in text and "Audio reference" in text
            assert "SECRET EXPECTED" not in text + prompt
            raise OSError("failed")
    run = create_run(store, dataset, setup, "development", {})
    saved = execute_run(store, run["id"], Fake())
    result = saved["results"][0]
    assert "model_input" not in result
    assert "Audio reference" not in json.dumps(saved)
    assert resolve(tmp_path, result["request"])["user"] == "# AI transcription reference\nAudio reference\n\n# Original transcript\nrough"
    other = execute_run(store, create_run(store, dataset, setup, "development", {})["id"], Fake())
    assert other["results"][0]["request"] == result["request"]
    (tmp_path / result["transcription"]["path"]).unlink()
    saved = execute_run(store, run["id"], Fake(), retry=True)
    assert "Missing referenced artifact" in saved["results"][0]["error"]


def test_cached_preflight_needs_no_gemini_key():
    from evaluation.transcription import preflight
    preflight({"requests": 0}, {"api_key": "fake"})
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        preflight({"requests": 1}, {"api_key": "fake"})


def test_partial_segments_retry_and_cleanup_pending(tmp_path, monkeypatch):
    from evaluation.transcription import Transcriptions, workload
    from evaluation.storage import write_json, read_json, resolve
    from evaluation.tests.audio_helpers import AUDIO, seed
    store = Store(tmp_path)
    seed(store)
    service = Transcriptions(store)
    model = "gemini-3.5-transcribe"
    directory = service.directory(AUDIO, model)
    (directory / "complete.json").unlink()
    write_json(directory / "segments.json", {"segments": [
        {"start": 0, "end": .05, "overlap": False}, {"start": .05, "end": .1, "overlap": False}]})
    calls, temporary_paths = [], []
    class Client:
        fail = True
        def transcribe(self, path, model, remote, warning):
            temporary_paths.append(path)
            calls.append(model)
            if len(calls) == 2 and self.fail:
                raise ValueError("failed segment")
            return "first" if len(calls) == 1 else "second"
    client = Client()
    with pytest.raises(ValueError, match="failed segment"):
        service.ensure(AUDIO, model, client)
    assert all(not p.exists() for p in temporary_paths)
    counts = workload(store, [{"id": "x", "input": "hi", "output": "Hi", "audio": AUDIO}],
                      [{"transcription_model": model}] * 2)
    assert counts["requests"] == 1 and counts["prompts"] == 2
    client.fail = False
    assert resolve(tmp_path, service.ensure(AUDIO, model, client))["text"] == "first\nsecond"
    assert len(calls) == 3
    write_json(directory / "state.json", {"remote": "files/orphan", "warnings": []})
    deleted = []
    client.delete = deleted.append
    service.ensure(AUDIO, model, client)
    assert deleted == ["files/orphan"]
    assert read_json(directory / "state.json")["remote"] is None


@pytest.mark.parametrize("status,text,success", [("completed", "speech", True), ("incomplete", "partial", False),
                                                ("completed", "", False)])
def test_gemini_contract_and_cleanup(tmp_path, status, text, success):
    from types import SimpleNamespace
    from evaluation.transcription import GeminiTranscriber, AUDIO_MODELS
    for model in AUDIO_MODELS:
        events, payloads = [], []
        class Files:
            def upload(self, **kwargs):
                return SimpleNamespace(name="files/upload", uri="uri", state="ACTIVE")
            def delete(self, **kwargs):
                events.append(kwargs["name"])
        class Interactions:
            def create(self, **kwargs):
                payloads.append(kwargs)
                return SimpleNamespace(status=status, output_text=text)
        client = GeminiTranscriber("fake", sdk=SimpleNamespace(files=Files(), interactions=Interactions()))
        if success:
            assert client.transcribe(tmp_path / "x.wav", model, lambda _: None, lambda _: None) == text
        else:
            with pytest.raises(ValueError):
                client.transcribe(tmp_path / "x.wav", model, lambda _: None, lambda _: None)
        assert events == ["files/upload"]
        assert payloads[0]["model"] == model and payloads[0]["store"] is False
        if model == AUDIO_MODELS[0]:
            assert payloads[0]["generation_config"] == {"transcription_config": {"mode": {"type": "verbatim", "diarization_mode": "speaker"}}}
        else:
            assert "Speaker 1" in payloads[0]["input"][0]["text"]


def test_unlabeled_cache_is_preserved_but_not_reused(tmp_path):
    from evaluation.core import Store
    from evaluation.transcription import Transcriptions, DEFAULT_AUDIO_MODEL
    from evaluation.tests.audio_helpers import AUDIO
    from evaluation.storage import write_json
    old = tmp_path / "transcriptions" / DEFAULT_AUDIO_MODEL / AUDIO["sha256"] / "complete.json"
    write_json(old, {"text": "Old unlabeled speech"})
    assert Transcriptions(Store(tmp_path)).cached(AUDIO, DEFAULT_AUDIO_MODEL) is None
    assert old.exists()


def test_advisory_lock_released_when_worker_is_killed(tmp_path):
    import os
    import subprocess
    import sys
    import time
    from evaluation.storage import file_lock
    lock = tmp_path / "cache.lock"
    marker = tmp_path / "ready"
    script = ("from evaluation.storage import file_lock; from pathlib import Path; import sys,time; "
              "\nwith file_lock(sys.argv[1]):\n Path(sys.argv[2]).touch()\n time.sleep(60)\n")
    # Windows venv python.exe can be a launcher for a second process. Kill the
    # interpreter that owns the lock, rather than only its launcher process.
    interpreter = sys._base_executable if os.name == "nt" else sys.executable
    worker = subprocess.Popen([interpreter, "-c", script, str(lock), str(marker)],
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert marker.exists()
        with pytest.raises(ValueError, match="already executing"):
            with file_lock(lock):
                pass
    finally:
        worker.kill()
        worker.wait(timeout=10)
    with file_lock(lock):
        assert lock.exists()


def test_folder_and_jsonl_import_preserve_copies(tmp_path):
    from evaluation.imports import folder_files
    source, destination = tmp_path / "source", tmp_path / "data"
    source.mkdir()
    (source / "x.txt").write_bytes(b"hello\r\n")
    (source / "x_scoped.txt").write_bytes(b"Hello.\r\n")
    (source / "x.wav").write_bytes(wav_bytes())
    (source / "unrelated.pdf").write_bytes(b"ignored")
    (source / "nested").mkdir()
    store = Store(destination)
    folder_cases = import_files(store, folder_files(source))
    json_cases = import_files(store, {"x.wav": source / "x.wav"}, [{"id": "x", "input": "hello\r\n", "output": "Hello.\r\n"}])
    assert folder_cases == json_cases
    (source / "x.wav").unlink()
    assert store.save_dataset("Copied", folder_cases)["cases"] == folder_cases


def test_store_rejects_cases_without_audio(tmp_path):
    with pytest.raises(ValueError, match="WAV"):
        Store(tmp_path).save_dataset("Invalid", [{"id": "x", "input": "hi", "output": "Hi"}])


def test_upload_timeout_has_persisted_remote_identity(tmp_path):
    from types import SimpleNamespace
    from evaluation.transcription import GeminiTranscriber
    pending, deleted = [], []
    class Files:
        def upload(self, **kwargs):
            assert pending[-1] == kwargs["config"]["name"]
            raise TimeoutError("response lost")
        def delete(self, **kwargs):
            deleted.append(kwargs["name"])
    client = GeminiTranscriber("fake", sdk=SimpleNamespace(files=Files()))
    with pytest.raises(ValueError):
        client.transcribe(tmp_path / "audio.wav", "gemini-3.5-transcribe", pending.append, lambda _: None)
    assert len(deleted) == 1 and deleted[0].startswith("files/")
    assert pending[-1] is None


def test_saved_segments_cleanup_without_new_upload(tmp_path):
    from evaluation.transcription import Transcriptions
    from evaluation.storage import write_json, read_json
    from evaluation.tests.audio_helpers import AUDIO, seed
    store = Store(tmp_path)
    seed(store)
    service = Transcriptions(store)
    directory = service.directory(AUDIO, "gemini-3.5-transcribe")
    (directory / "complete.json").unlink()
    write_json(directory / "segments.json", {"segments": [{"start": 0, "end": .1, "overlap": False}]})
    write_json(directory / "segment-0000.json", {"text": "complete segment"})
    write_json(directory / "state.json", {"remote": "files/pending", "warnings": []})
    deleted = []
    class Client:
        def delete(self, name):
            deleted.append(name)
    service.ensure(AUDIO, "gemini-3.5-transcribe", Client())
    assert deleted == ["files/pending"]
    assert read_json(directory / "state.json")["remote"] is None


def test_folder_wavs_are_not_read_all_at_once(tmp_path, monkeypatch):
    from pathlib import Path
    from evaluation.imports import folder_files
    source = tmp_path / "source"
    source.mkdir()
    (source / "x.txt").write_bytes(b"hello")
    (source / "x_scoped.txt").write_bytes(b"Hello")
    (source / "x.wav").write_bytes(wav_bytes())
    read_bytes = Path.read_bytes
    def guarded(path):
        assert path.suffix != ".wav", "WAVs must stream to disk instead of accumulating in memory"
        return read_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    assert import_files(Store(tmp_path / "data"), folder_files(source))[0]["audio"]["duration"] > 0


def test_original_name_can_end_in_scoped(tmp_path):
    assert import_files(Store(tmp_path), {"trial_scoped.txt": b"hi", "trial_scoped_scoped.txt": b"Hi",
                                          "trial_scoped.wav": wav_bytes()})[0]["id"] == "trial_scoped"


def test_repeated_words_at_overlap_are_flagged():
    text, flags = join_segments(["He said yes yes yes", "yes yes yes again"], [False, True])
    assert text == "He said yes yes yes\nyes yes yes again" and flags == [1]


def test_retry_checks_pinned_references_before_credentials(tmp_path):
    from evaluation.transcription import retry_workload
    from evaluation.core import create_run, execute_run
    from evaluation.tests.audio_helpers import save_dataset
    store = Store(tmp_path)
    data = save_dataset(store, "Test", [{"id": "x", "input": "hi", "output": "Hi"}])
    setup = store.save_prompt("Edit", "Edit", "Rules")
    class Fail:
        def complete(self, *args):
            raise ValueError("edit failed")
    run = execute_run(store, create_run(store, data, setup, "development", {})["id"], Fail())
    assert retry_workload(store, run)["requests"] == 0
    from evaluation.storage import write_json
    state = (tmp_path / run["results"][0]["transcription"]["path"]).with_name("state.json")
    write_json(state, {"remote": "files/pending", "warnings": []})
    deleted = []
    class Cleanup:
        def delete(self, name):
            deleted.append(name)
    execute_run(store, run["id"], Fail(), retry=True, transcriber=Cleanup())
    assert deleted == ["files/pending"]
    (tmp_path / run["results"][0]["transcription"]["path"]).unlink()
    with pytest.raises(ValueError, match="Missing referenced artifact"):
        retry_workload(store, run)




def test_real_google_sdk_serializes_transcription_with_fake_http(tmp_path):
    import httpx
    from google import genai
    from types import SimpleNamespace
    from evaluation.transcription import GeminiTranscriber, AUDIO_MODELS
    requests = []
    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "test", "status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": "Spoken words."}]}]})
    with genai.Client(api_key="fake", http_options={"client_args": {"transport": httpx.MockTransport(transport)},
                                                  "retry_options": {"attempts": 1}}) as sdk:
        class Files:
            def upload(self, **kwargs):
                return SimpleNamespace(name=kwargs["config"]["name"], uri="https://example.com/audio", state="ACTIVE")
            def delete(self, **kwargs):
                pass
        client = GeminiTranscriber("fake", sdk=SimpleNamespace(files=Files(), interactions=sdk.interactions))
        for model in AUDIO_MODELS:
            assert client.transcribe(tmp_path / "x.wav", model, lambda _: None, lambda _: None) == "Spoken words."
    assert len(requests) == 2
    assert requests[0]["generation_config"]["transcription_config"]["mode"]["type"] == "verbatim"


def test_speaker_annotations_survive_sdk(tmp_path):
    import httpx
    from google import genai
    from types import SimpleNamespace
    from evaluation.transcription import GeminiTranscriber
    # Offsets are UTF-8 bytes, not Python character indices. Preserve punctuation.
    text = "Café? Yes, indeed. Again?"
    annotations = [
        {"type": "word_info", "speaker": speaker, "start_index": start,
         "end_index": end}
        for speaker, start, end in [("spk:0", 0, 6), ("spk:1", 7, 11),
                                    ("spk:1", 12, 19), ("spk:0", 20, 26)]
    ]
    def transport(request):
        return httpx.Response(200, json={"status": "completed", "steps": [
            {"type": "model_output", "content": [
                {"type": "text", "text": text, "annotations": annotations}]}]})
    class Files:
        def upload(self, **kwargs):
            return SimpleNamespace(name="files/test", uri="uri", state="ACTIVE")
        def delete(self, **kwargs):
            pass
    with genai.Client(api_key="fake", http_options={"client_args": {
            "transport": httpx.MockTransport(transport)}}) as sdk:
        client = GeminiTranscriber("fake", sdk=SimpleNamespace(files=Files(), interactions=sdk.interactions))
        result = client.transcribe(tmp_path / "x.wav", "gemini-3.5-transcribe", lambda _: None, lambda _: None)
    assert result == "Speaker 1: Café?\nSpeaker 2: Yes, indeed.\nSpeaker 1: Again?"

def test_gemini_response_time_excludes_upload_and_cleanup(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from evaluation.transcription import GeminiTranscriber
    clock = [0.0]
    monkeypatch.setattr('evaluation.transcription.time.perf_counter', lambda: clock[0])
    class Files:
        def upload(self, **kwargs):
            clock[0] += 30
            return SimpleNamespace(name='files/test', uri='uri', state='ACTIVE')
        def delete(self, **kwargs):
            clock[0] += 20
    class Interactions:
        def create(self, **kwargs):
            clock[0] += 7.25
            return SimpleNamespace(status='completed', output_text='speech')
    client = GeminiTranscriber('fake', sdk=SimpleNamespace(files=Files(), interactions=Interactions()))
    client.transcribe(tmp_path / 'x.wav', 'gemini-3.5-transcribe', lambda _: None, lambda _: None)
    assert client.api_seconds == 7.25
