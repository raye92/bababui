"""Independent per-document jobs and shared in-flight transcription."""
from concurrent.futures import Future
from dataclasses import dataclass
import hashlib
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
import wave

from PySide6.QtCore import QObject, QThread, Signal

from app.src.audio_pipeline import AudioPipeline, check_wav_digest
from app.src.vocabulary_reconciliation import normalized_vocabulary
from app.src.ai_review import AssistedReview, review_edits
from app.src.casecat.timing import AudioMap
from app.src.processing import ProcessingClient, APP_DIR
from app.src.speech_alignment import NO_TIMESTAMPS, UNAVAILABLE, align_speech
from app.src.suggestion_filter import auto_accept
from app.src.transcription_output import RunOutput


class TranscriptionCoordinator:
    def __init__(self):
        self._lock = Lock()
        self._active = {}

    def run(self, path, model, pipeline, progress, *, vocabulary=(), output=None):
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
            leader = vocabulary not in contexts
            if leader:
                contexts[vocabulary] = Future(), output
            future, source_output = contexts[vocabulary]
        if sharing:
            progress('Waiting for shared transcription...')
        if not leader:
            try:
                return future.result()
            finally:
                check_wav_digest(path, key[0])
                if output and source_output:
                    for suffix, source in source_output.files.items():
                        output.copy(suffix, source)
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


class ProcessingWorker(QThread):
    succeeded = Signal(str, str, list, object)
    reviewed = Signal(str, object, list, object)
    failed = Signal(str, str)
    progress = Signal(str, str)

    def __init__(self, request, coordinator, pipeline_factory=AudioPipeline,
                 processor_factory=ProcessingClient):
        super().__init__()
        self.request, self.coordinator = request, coordinator
        self.output = None
        self.pipeline_factory, self.processor_factory = pipeline_factory, processor_factory

    def run(self):
        request = self.request
        try:
            processor = self.processor_factory(request.config, request.model)
            processor.check_ready()
            if not request.prompt.strip():
                raise ValueError('Fill in app/src/bababui_prompt.md before processing.')
            directory = APP_DIR / 'data' / 'transcriptions'
            name = Path(request.bundle.name if request.bundle else request.wav_path).stem
            if request.bundle and len(request.bundle.jobs) > 1:
                key = request.job.key
                job_name = Path(key).name
                if sum(Path(other).name.casefold() == job_name.casefold() for other in request.bundle.jobs) > 1:
                    job_name = key.replace('/', ' - ')
                name = f'{name[:40]} - {job_name[-36:]}'
            cache = APP_DIR / 'data' / 'transcription-cache'
            self.output = RunOutput.create(directory, name)
            pipeline = self.pipeline_factory(request.config.get('gemini_api_key', ''), cache,
                                             output=self.output, legacy_cache=directory)
            report = lambda message: self.progress.emit(request.document_id, message)
            report('Checking WAV...')
            transcription = self.coordinator.run(request.wav_path, request.transcription_model, pipeline, report,
                                                 vocabulary=request.vocabulary, output=self.output)
            text, warnings = transcription.text, list(transcription.warnings)
            report('Saving raw transcription...')
            self.output.save_text(text)
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
                reviewed = self._review(result, report)
                self.reviewed.emit(request.document_id, reviewed, warnings, alignment)
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, OSError)) else 'API request failed. Check credentials, model access, or quota, then retry.'
            for key in ('api_key', 'gemini_api_key'):
                if request.config.get(key):
                    message = message.replace(request.config[key], '[REDACTED]')
            self.failed.emit(request.document_id, message)

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

    def _review(self, text, report):
        request = self.request
        from app.src.notice_review import begin_body_review, split_revision, joined_snapshot, response_body
        head = None
        original = request.original
        if request.body_start:
            head, original = split_revision(original, request.body_start)
            text = response_body(head.text, text)
        state = SimpleNamespace(original=original)
        off_record_undo = begin_body_review(state, text, request.bundle, request.job, head=head,
                                            exclude_off_record='off_record' not in request.disabled_rules)
        before_rules = state.original, state.incoming, state.review
        auto_accept(state, disabled_rules=request.disabled_rules)
        after_rules = state.original, state.incoming, state.review
        report('Reviewing small wording edits...')

        def complete(payload, prompt):
            client = self.processor_factory(request.config, request.review_model)
            return client.complete(payload, prompt)

        try:
            original, incoming, review, summary = review_edits(
                *after_rules, complete)
            after_ai = original, incoming, review
        except (OSError, ValueError):
            after_ai = after_rules
            summary = 'AI-assisted review could not be applied. Edits remain pending.'
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
    output_folder = Signal(str, str)

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
        if worker.output:
            self.output_folder.emit(identifier, str(worker.output.directory))
        worker.deleteLater()
        self.completed.emit(identifier)
