"""Independent per-document jobs and shared in-flight transcription."""
from concurrent.futures import Future
from dataclasses import dataclass
import hashlib
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QObject, QThread, Signal

from app.src.audio_pipeline import AudioPipeline
from app.src.processing import ProcessingClient, APP_DIR


class TranscriptionCoordinator:
    def __init__(self):
        self._lock = Lock()
        self._active = {}

    def run(self, path, model, pipeline, progress):
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != '.wav':
            raise ValueError('Choose an existing .wav file.')
        with path.open('rb') as stream:
            key = (hashlib.file_digest(stream, 'sha256').hexdigest(), model)
        with self._lock:
            future = self._active.get(key)
            leader = future is None
            if leader:
                future = Future()
                self._active[key] = future
        if not leader:
            progress('Waiting for shared transcription...')
            return future.result()
        try:
            result = pipeline.run(path, progress)
            future.set_result(result)
            return result
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._active.pop(key, None)


@dataclass(frozen=True)
class Request:
    document_id: str
    wav_path: str
    model: str
    transcription_model: str
    prompt: str
    config: dict


class ProcessingWorker(QThread):
    succeeded = Signal(str, str, list)
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
            pipeline = self.pipeline_factory(request.config.get('gemini_api_key', ''), APP_DIR/'data'/'transcriptions')
            report = lambda message: self.progress.emit(request.document_id, message)
            report('Checking WAV...')
            text, warnings = self.coordinator.run(request.wav_path, request.transcription_model, pipeline, report)
            report('Formatting transcript...')
            result = processor.complete(text, request.prompt)
            self.succeeded.emit(request.document_id, result, list(warnings))
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, OSError)) else 'API request failed. Check credentials, model access, or quota, then retry.'
            for key in ('api_key', 'gemini_api_key'):
                if request.config.get(key):
                    message = message.replace(request.config[key], '[REDACTED]')
            self.failed.emit(request.document_id, message)


class JobManager(QObject):
    succeeded = Signal(str, str, list)
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
