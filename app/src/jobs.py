"""Independent per-document jobs and shared in-flight transcription."""
from concurrent.futures import Future
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from threading import Lock
from types import SimpleNamespace
from uuid import uuid4
import wave

from PySide6.QtCore import QObject, QThread, Signal

from app.src.audio_pipeline import AudioPipeline, check_wav_digest
from app.src.vocabulary_reconciliation import normalized_vocabulary
from app.src.ai_review import AssistedReview, review_edits
from app.src.casecat.timing import AudioMap
from app.src.processing import ProcessingClient, APP_DIR
from app.src.speech_alignment import NO_TIMESTAMPS, UNAVAILABLE, align_speech
from app.src.suggestion_filter import auto_accept, begin_review
from shared.speaker_review import review_speakers
from shared.storage import atomic_bytes


_raw_export_lock = Lock()


def save_raw_transcription(wav_path, text):
    path = Path(wav_path).with_suffix('.raw.txt')
    data = text.encode('utf-8')
    with _raw_export_lock:
        # Shared transcription jobs can finish together for the same WAV.
        if not path.exists() or path.read_bytes() != data:
            atomic_bytes(path, data)
    return path


class TranscriptionCoordinator:
    def __init__(self):
        self._lock = Lock()
        self._active = {}

    def run(self, path, model, pipeline, progress, *, vocabulary=()):
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != '.wav':
            raise ValueError('Choose an existing .wav file.')
        with path.open('rb') as stream:
            key = (hashlib.file_digest(stream, 'sha256').hexdigest(), model)
        vocabulary = normalized_vocabulary(vocabulary)
        with self._lock:
            if key not in self._active:
                self._active[key] = Lock(), {}
            recording_lock, contexts = self._active[key]
            sharing = bool(contexts)
            future = contexts.get(vocabulary)
            leader = future is None
            if leader:
                contexts[vocabulary] = future = Future()
        if sharing:
            progress('Waiting for shared transcription...')
        if not leader:
            result = future.result()
            check_wav_digest(path, key[0])
            return result
        try:
            # Another tab may use the same base cache with different names.
            with recording_lock:
                if sharing:
                    check_wav_digest(path, key[0])
                kwargs = {'vocabulary': vocabulary} if vocabulary else {}
                result = pipeline.run(path, progress, **kwargs)
                if result.wav_sha256 != key[0]:
                    raise ValueError('The WAV changed during transcription. Run BABABUI again.')
            future.set_result(result)
            return result
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                del contexts[vocabulary]
                if not contexts:
                    del self._active[key]


@dataclass(frozen=True)
class Request:
    document_id: str
    wav_path: str
    model: str
    transcription_model: str
    prompt: str
    config: dict
    original: object = None
    review_model: str | None = None
    disabled_rules: frozenset[str] = frozenset()
    bundle: object = None
    job: object = None
    vocabulary: tuple[str, ...] = ()
    body_start: int = 0
    context: str = ''


class ProcessingWorker(QThread):
    succeeded = Signal(str, str, list, object)
    reviewed = Signal(str, object, list, object)
    failed = Signal(str, str)
    progress = Signal(str, str)

    def __init__(self, request, coordinator, pipeline_factory=AudioPipeline,
                 processor_factory=ProcessingClient):
        super().__init__()
        self.request, self.coordinator = request, coordinator
        self.pipeline_factory, self.processor_factory = pipeline_factory, processor_factory

    def run(self):
        request = self.request
        try:
            processor = self.processor_factory(request.config, request.model)
            processor.check_ready()
            if not request.prompt.strip():
                raise ValueError('Fill in app/src/bababui_prompt.md before processing.')
            pipeline = self.pipeline_factory(request.config.get('gemini_api_key', ''),
                                             APP_DIR/'data'/'transcriptions',
                                             testing=request.config.get('testing', False))
            report = lambda message: self.progress.emit(request.document_id, message)
            report('Checking WAV...')
            transcription = self.coordinator.run(request.wav_path, request.transcription_model, pipeline, report,
                                                 vocabulary=request.vocabulary)
            text, warnings = transcription.text, list(transcription.warnings)
            report('Saving raw transcription...')
            save_raw_transcription(request.wav_path, text)
            speakers = None
            if request.review_model is not None and transcription.words:
                # The raw export stays Gemini's stitched transcript, the baseline for these changes.
                speakers = self._review_speakers(transcription, report)
                text = speakers.text
                warnings.extend(speakers.warnings)
            report('Formatting transcript...')
            result = processor.complete(text, request.prompt)
            alignment = None
            if request.job is not None:
                report('Aligning transcript with audio...')
                if any(w.start is not None for w in transcription.words):
                    alignment = self._align(transcription)
                    if alignment is None:
                        warnings.append(UNAVAILABLE)
                else:
                    warnings.append(NO_TIMESTAMPS)
            report('Applying transcript standards...')
            if request.review_model is None:
                self.succeeded.emit(request.document_id, result, warnings, alignment)
            else:
                reviewed = self._review(result, report, alignment, speakers)
                self.reviewed.emit(request.document_id, reviewed, warnings, alignment)
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, OSError)) else 'API request failed. Check credentials, model access, or quota, then retry.'
            for key in ('api_key', 'gemini_api_key'):
                if request.config.get(key):
                    message = message.replace(request.config[key], '[REDACTED]')
            self.failed.emit(request.document_id, message)

    def _review_speakers(self, transcription, report):
        request = self.request

        def complete(payload, prompt):
            return self.processor_factory(request.config, request.review_model).complete(payload, prompt)

        testing = request.config.get('testing', False)
        folder = Path(tempfile.gettempdir())/'bababui-transcriptions'
        name = f'speaker-review-{uuid4().hex}'

        def save(entry):
            atomic_bytes(folder/f'{name}-{entry["batch"]}.json',
                         json.dumps(entry, ensure_ascii=False, indent=2).encode('utf-8'))
        # Stitching notes say where a speaker number may have changed at a chunk join.
        notes = [w for w in transcription.warnings if 'speaker' in w.casefold()]
        result = review_speakers(transcription.words, complete, context=request.context, notes=notes,
                                 progress=report, log=save if testing else None)
        if testing:
            atomic_bytes(folder/f'{name}-result.json',
                         json.dumps(result.to_json(), ensure_ascii=False, indent=2).encode('utf-8'))
        return result

    def _align(self, transcription):
        request = self.request
        try:
            timing = AudioMap.from_job(request.bundle, request.job, request.wav_path)
            times = timing.stroke_ms
        except (ValueError, OSError, wave.Error, EOFError):
            times = (None,) * len(request.job.stroke_clocks)
        original = request.original or request.job.baseline
        if request.body_start:
            from app.src.notice_review import split_revision
            _, original = split_revision(original, request.body_start)
        return align_speech(original, times, transcription.words,
                            transcription.duration_ms, transcription.wav_sha256)

    def _review(self, text, report, alignment=None, speakers=None):
        request = self.request
        from app.src.notice_review import split_revision, joined_snapshot, response_body
        from app.src.speaker_votes import VoiceCheck
        from app.src.suggestion_filter import index_speaker_fields
        head = None
        original = request.original
        if request.body_start:
            head, original = split_revision(original, request.body_start)
            text = response_body(head.text, text)
        state = SimpleNamespace(original=original)
        report('Checking disputed speaker labels...')
        off_record_undo = begin_review(state, text, exclude_off_record='off_record' not in request.disabled_rules,
                                       index_fields=index_speaker_fields(head) if head is not None else None,
                                       voice=VoiceCheck.create(original, alignment, request.wav_path)
                                       if alignment is not None else None)
        if speakers is not None:
            # Corrected-label highlights travel with every review snapshot, including Undo.
            record = speakers.record()
            state.review['speaker_review'] = record
            if off_record_undo is not None:
                off_record_undo = (*off_record_undo[:2], {**off_record_undo[2], 'speaker_review': record})
        before_rules = state.original, state.incoming, state.review
        auto_accept(state, disabled_rules=request.disabled_rules)
        after_rules = state.original, state.incoming, state.review
        report('Reviewing small wording edits...')

        def complete(payload, prompt):
            client = self.processor_factory(request.config, request.review_model)
            return client.complete(payload, prompt)

        try:
            original, incoming, review, summary = review_edits(
                *after_rules, request.review_model, complete, request.document_id,
                testing=request.config.get('testing', False))
            after_ai = original, incoming, review
        except (OSError, ValueError):
            after_ai = after_rules
            summary = 'AI-assisted review could not be applied and recorded. Edits remain pending.'
        if speakers is not None:
            summary = f'{speakers.summary} {summary}'
        if head is not None:
            off_record_undo, before_rules, after_rules, after_ai = (
                joined_snapshot(head, head, snapshot) for snapshot in (off_record_undo, before_rules, after_rules, after_ai))
        return AssistedReview(request.original, off_record_undo, before_rules, after_rules, after_ai, summary)


class JobManager(QObject):
    succeeded = Signal(str, str, list, object)
    reviewed = Signal(str, object, list, object)
    failed = Signal(str, str)
    progress = Signal(str, str)
    completed = Signal(str)

    def __init__(self, parent=None, worker_factory=ProcessingWorker):
        super().__init__(parent)
        self.coordinator = TranscriptionCoordinator()
        self.workers = {}
        self.worker_factory = worker_factory

    def start(self, request):
        if request.document_id in self.workers:
            raise ValueError('This tab is already processing.')
        worker = self.worker_factory(request, self.coordinator)
        self.workers[request.document_id] = worker
        worker.succeeded.connect(self.succeeded)
        worker.reviewed.connect(self.reviewed)
        worker.failed.connect(self.failed)
        worker.progress.connect(self.progress)
        worker.finished.connect(self._finished)
        worker.start()

    def _finished(self):
        worker = self.sender()
        identifier = worker.request.document_id
        self.workers.pop(identifier, None)
        worker.deleteLater()
        self.completed.emit(identifier)
