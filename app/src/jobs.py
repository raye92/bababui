"""Independent per-document jobs and shared in-flight transcription."""
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Literal
import wave

from PySide6.QtCore import QObject, QThread, Signal

from app.src.audio_pipeline import AudioPipeline, check_wav_digest, wav_sha256
from app.src.vocabulary_reconciliation import normalized_vocabulary, preserve_notice_spellings
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

    def run(self, path, model, pipeline, progress, *, vocabulary=(), output=None, fresh=False):
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != '.wav':
            raise ValueError('Choose an existing .wav file.')
        key = (wav_sha256(path), model)
        vocabulary = normalized_vocabulary(vocabulary)
        # A confirmed rerun must acquire the recording lock and make its own requests.
        context = object() if fresh else vocabulary
        with self._lock:
            if key not in self._active:
                self._active[key] = Lock(), {}
            recording_lock, contexts = self._active[key]
            sharing = bool(contexts)
            leader = context not in contexts
            if leader:
                contexts[context] = Future(), output
            future, source_output = contexts[context]
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
                if fresh:
                    kwargs['expected_digest'] = key[0]
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
                del contexts[context]
                if not contexts:
                    del self._active[key]


@dataclass(frozen=True)
class RunSteps:
    transcribe: bool = True
    format: bool = True
    review: bool = True
    audio_cache: Literal['reuse', 'refresh', 'clean'] = 'reuse'

    def __post_init__(self):
        if self.format and not self.review:
            object.__setattr__(self, 'review', True)


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
    steps: RunSteps = RunSteps()
    raw_transcript: str = ''
    raw_wav_sha256: str = ''
    incoming: object = None
    incoming_body_start: int = 0


class ProcessingWorker(QThread):
    transcribed = Signal(str, str, str)
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
        steps = request.steps
        report = lambda message: self.progress.emit(request.document_id, message)
        try:
            if steps.format:
                processor = self.processor_factory(request.config, request.model)
                processor.check_ready()
                if not request.prompt.strip():
                    raise ValueError('Fill in app/src/bababui_prompt.md before processing.')
            transcription = self._transcribe(report) if steps.transcribe else None
            result = ''
            if steps.format:
                raw = transcription.text if transcription else self._saved_text(report)
                report('Formatting transcript...')
                result = processor.complete(raw, request.prompt)
                if request.vocabulary and request.original is not None:
                    testimony = request.original.text[request.body_start:]
                    result = preserve_notice_spellings(testimony, result, request.vocabulary)
            warnings = list(transcription.warnings) if transcription else []
            alignment = None
            if transcription and request.job is not None:
                report('Aligning transcript with audio...')
                if any(w.start is not None for w in transcription.words):
                    alignment = self._align(transcription)
                    if alignment is None:
                        warnings.append(UNAVAILABLE)
                else:
                    warnings.append(NO_TIMESTAMPS)
            if steps.review and (request.review_model is not None or not steps.format):
                report('Applying automated review...')
                reviewed = self._review(result, report, current=request.incoming,
                                        incoming_body_start=request.incoming_body_start)
                self.reviewed.emit(request.document_id, reviewed, warnings, alignment)
            else:
                self.succeeded.emit(request.document_id, result, warnings, alignment)
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, OSError)) else 'API request failed. Check credentials, model access, or quota, then retry.'
            for key in ('api_key', 'gemini_api_key'):
                if request.config.get(key):
                    message = message.replace(request.config[key], '[REDACTED]')
            self.failed.emit(request.document_id, message)

    def _pipeline(self, mode):
        directory = APP_DIR / 'data'
        options = {'cache_mode': mode} if mode != 'reuse' else {}
        return self.pipeline_factory(self.request.config.get('gemini_api_key', ''), directory / 'transcription-cache',
                                     output=self.output, legacy_cache=directory / 'transcriptions', **options)

    def _transcribe(self, report):
        request = self.request
        name = Path(request.bundle.name if request.bundle else request.wav_path).stem
        if request.bundle and len(request.bundle.jobs) > 1:
            key = request.job.key
            job_name = Path(key).name
            if sum(Path(other).name.casefold() == job_name.casefold() for other in request.bundle.jobs) > 1:
                job_name = key.replace('/', ' - ')
            name = f'{name[:40]} - {job_name[-36:]}'
        self.output = RunOutput.create(APP_DIR / 'data' / 'transcriptions', name)
        report('Checking WAV...')
        mode = request.steps.audio_cache
        transcription = self.coordinator.run(request.wav_path, request.transcription_model, self._pipeline(mode), report,
                                             vocabulary=request.vocabulary, output=self.output, fresh=mode != 'reuse')
        report('Saving raw transcription...')
        self.output.save_text(transcription.text)
        self.transcribed.emit(request.document_id, transcription.text, transcription.wav_sha256)
        return transcription

    def _saved_text(self, report):
        request = self.request
        report('Loading saved transcription...')
        if request.raw_transcript:
            path = Path(request.wav_path)
            if path.is_file():
                check_wav_digest(path, request.raw_wav_sha256,
                                 'This WAV has changed. Select Transcription to generate a new raw transcript.')
            return request.raw_transcript
        # Projects saved by older releases may only have cached words on disk.
        return self._pipeline('saved').run(request.wav_path, vocabulary=request.vocabulary).text

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

    def _review(self, text, report, *, current=None, incoming_body_start=0):
        request = self.request
        from app.src.notice_review import begin_body_review, split_revision, joined_snapshot, response_body
        head = incoming_head = None
        original = request.original
        if request.body_start or incoming_body_start:
            head, original = split_revision(original, request.body_start)
            if current is not None:
                incoming_head, current = split_revision(current, incoming_body_start)
            else:
                incoming_head = head
                text = response_body(head.text, text)
        if current is not None:
            text = current.text
        state = SimpleNamespace(original=original)
        off_record_undo = begin_body_review(state, text, request.bundle, request.job, head=head,
                                            exclude_off_record='off_record' not in request.disabled_rules)
        if current is not None:
            # Keep native fields and anchors already present in the working Incoming revision.
            state.incoming = current.revise(state.incoming.text)
            if off_record_undo:
                before, incoming, metadata = off_record_undo
                off_record_undo = before, current.revise(incoming.text), metadata
        before_rules = state.original, state.incoming, state.review
        auto_accept(state, disabled_rules=request.disabled_rules)
        after_rules = state.original, state.incoming, state.review

        def complete(payload, prompt):
            client = self.processor_factory(request.config, request.review_model)
            return client.complete(payload, prompt)

        after_ai, summary = after_rules, ''
        if request.review_model is not None:
            report('Reviewing small wording edits...')
            try:
                original, incoming, review, summary = review_edits(*after_rules, complete)
                after_ai = original, incoming, review
            except (OSError, ValueError):
                summary = 'AI-assisted review could not be applied. Edits remain pending.'
        if head is not None:
            off_record_undo, before_rules, after_rules, after_ai = (
                joined_snapshot(head, incoming_head, snapshot)
                for snapshot in (off_record_undo, before_rules, after_rules, after_ai))
        return AssistedReview(request.original, off_record_undo, before_rules, after_rules, after_ai, summary)


class JobManager(QObject):
    transcribed = Signal(str, str, str)
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
        worker.transcribed.connect(self.transcribed)
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
