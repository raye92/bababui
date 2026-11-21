"""Independent per-document jobs and shared in-flight transcription."""
from collections import Counter
from concurrent.futures import Future
from dataclasses import dataclass, replace
import hashlib
from itertools import count
import json
from pathlib import Path
import tempfile
from threading import Lock
from types import SimpleNamespace
from uuid import uuid4
import wave

from PySide6.QtCore import QObject, QThread, Signal

from app.src import addressees
from app.src.audio_pipeline import AudioPipeline, check_wav_digest
from app.src.vocabulary_reconciliation import normalized_vocabulary
from app.src.ai_review import AssistedReview, review_edits
from app.src.casecat.timing import AudioMap
from app.src.processing import DEFAULT_MODEL, ProcessingClient, APP_DIR
from app.src.speech_alignment import NO_TIMESTAMPS, UNAVAILABLE, align_speech
from app.src.suggestion_filter import auto_accept, begin_review
from app.src.speaker_audio import AudioSpeakerCheck, VoiceComparison
from app.src.speaker_identity import UNRESOLVED, identifying_clips, link_voices, linked, verify_members
from app.src.speaker_identity import turns as _runs
# A voice with at most this many turns has its turns checked against its clearest clip.
MINOR_TURNS = 24
from shared.speaker_review import review_speakers
from shared.spelling_review import review_spelling
from shared.transcription import has_key
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
    # Confirmed notice spellings, each a ('person' or 'organization', name) pair.
    sources: tuple[tuple[str, str], ...] = ()


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
            # The reporter's house spellings, after the speaker review and before formatting.
            text = self._house_spelling(text, report, warnings)
            report('Formatting transcript...')
            result = processor.complete(text, request.prompt)
            result, addressed = self._addressees(result, text, report, warnings)
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
                reviewed = self._review(result, report, alignment, speakers, addressed)
                self.reviewed.emit(request.document_id, reviewed, warnings, alignment)
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, OSError)) else 'API request failed. Check credentials, model access, or quota, then retry.'
            for key in ('api_key', 'gemini_api_key'):
                if request.config.get(key):
                    message = message.replace(request.config[key], '[REDACTED]')
            self.failed.emit(request.document_id, message)

    def _house_spelling(self, text, report, warnings):
        """Apply app/assets/Spelling and Terminology.csv to the turns before formatting."""
        from app.src import house_spelling
        request = self.request
        self.house = self.house_summary = None
        try:
            reference = house_spelling.load()
        except (OSError, ValueError, UnicodeError) as exc:
            warnings.append(f'The house spelling reference could not be read, so it was skipped: {exc}')
            return text
        report('Applying house spellings...')
        model = request.review_model or request.model
        testing = request.config.get('testing', False)
        folder = Path(tempfile.gettempdir())/'bababui-transcriptions'
        name = f'house-spelling-{uuid4().hex}'
        saved = count(1)

        def save(entry):
            atomic_bytes(folder/f'{name}-{entry["kind"]}-{next(saved)}.json',
                         json.dumps(entry, ensure_ascii=False, indent=2).encode('utf-8'))

        def complete(payload, prompt):
            return self.processor_factory(request.config, model).complete(payload, prompt)
        ask = house_spelling.model_decisions(complete, save if testing else None)
        unsure = []

        def decide(items):
            try:
                return ask(items)
            except Exception:  # noqa: BLE001 - any model or network failure
                unsure.append(len(items))
                return [house_spelling.KEEP] * len(items)
        result = reference.apply(text, decide)
        notes = [result.summary] if result.changes else []
        if unsure:
            notes.append(f'{unsure[0]} context entr{"y" if unsure[0] == 1 else "ies"} kept: the model could not decide.')
        self.house, self.house_summary = reference, ' '.join(notes) or None
        return result.text

    def _review_speakers(self, transcription, report):
        request = self.request

        def complete(payload, prompt):
            return self.processor_factory(request.config, request.review_model).complete(payload, prompt)

        testing = request.config.get('testing', False)
        folder = Path(tempfile.gettempdir())/'bababui-transcriptions'
        name = f'speaker-review-{uuid4().hex}'
        saved = count(1)

        def save(entry):
            atomic_bytes(folder/f'{name}-{entry["kind"]}-{next(saved)}.json',
                         json.dumps(entry, ensure_ascii=False, indent=2).encode('utf-8'))
        # Conflicting proposals and renumbered voices are checked against the recording with Gemini.
        key = request.config.get('gemini_api_key', '')
        model = request.review_model if request.review_model.startswith('gemini-') else DEFAULT_MODEL
        verify = AudioSpeakerCheck(request.wav_path, key, model) if has_key(key) else None
        compare = VoiceComparison(request.wav_path, key, model) if has_key(key) else None
        log = save if testing else None
        # A voice a later chunk numbered afresh is linked to an earlier one by its voice first.
        words, identities, identity_notes = link_voices(transcription.words, transcription.identities, compare,
                                                        progress=report, log=log)
        # Stitching notes say where a speaker number may have changed at a chunk join.
        notes = [w for w in transcription.warnings if 'speaker' in w.casefold()] + identity_notes
        result = review_speakers(words, complete, context=request.context, notes=notes,
                                 rough=self._rough(), verify=verify, progress=report, log=log,
                                 identities=identities)
        result = replace(result, voices=self._voices(result, compare, report, log))
        if testing:
            atomic_bytes(folder/f'{name}-result.json',
                         json.dumps(result.to_json(), ensure_ascii=False, indent=2).encode('utf-8'))
        return result

    @staticmethod
    def _voices(result, compare, report, log):
        """Which turns share one voice, for each voice the reporter may be asked about: a
        voice still unresolved after the review, and any voice with few turns, such as a
        second attorney or the reporter, that the rough may not name."""
        final = list(result.words)
        for segment in result.segments:
            label = result.display(segment.speaker) if segment.speaker else None
            for i in range(segment.start, segment.end):
                final[i] = replace(final[i], speaker=label)
        sizes = Counter(owner for owner, _, _ in _runs(final))
        voices = []
        for label in sizes:
            info = result.identities.get(label, {})
            if label is None or (info.get('status') != UNRESOLVED and sizes[label] > MINOR_TURNS):
                continue
            clips = identifying_clips(final, label, 1)
            clip = clips[0] if clips else None
            verdicts = verify_members(final, label, clip, compare, progress=report, log=log)
            spans = {first: end for owner, first, end in _runs(final) if owner == label}
            voices.append({'label': label, 'status': info.get('status', ''), 'chunk': info.get('chunk'),
                           'evidence': info.get('evidence', ''), 'clip': clip,
                           'turns': [{'first': first, 'last': spans[first], 'start': final[first].start,
                                      'end': final[spans[first] - 1].end, 'verdict': verdict,
                                      'linked': linked(verdict, spans[first] - first)}
                                     for first, verdict in sorted(verdicts.items())]})
        return tuple(voices)

    def _rough(self):
        """The reporter's rough testimony, an additional check on proposed speakers."""
        request = self.request
        if request.original is None:
            return None
        original = request.original
        if request.body_start:
            from app.src.notice_review import split_revision
            _, original = split_revision(original, request.body_start)
        return original.text

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

    @staticmethod
    def _addressees(draft, source, report, warnings):
        """Q/A or colloquy from whom each turn addressed, where a later reply settles it."""
        report('Checking whom each turn addressed...')
        try:
            return addressees.revise(draft, source)
        except Exception:  # noqa: BLE001 - the formatter's draft is still usable
            warnings.append("The addressee check could not run. The formatter's Q/A and colloquy labels were kept.")
            return draft, []

    def _review(self, text, report, alignment=None, speakers=None, addressed=()):
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
        if addressed:
            # Why a label changed travels with every review snapshot, as the speaker review does.
            state.review['addressees'] = list(addressed)
            if off_record_undo is not None:
                off_record_undo = (*off_record_undo[:2], {**off_record_undo[2], 'addressees': list(addressed)})
        # Spelling covers the reporter's rough and every AI edit, before any is accepted.
        spelling, spelling_summary = self._review_spelling(state.original.text, state.incoming.text, report)
        before_rules = state.original, state.incoming, state.review
        # A change to a house spelling stays pending and green for the reporter.
        keep = getattr(self, 'house', None) and self.house.protects
        auto_accept(state, disabled_rules=request.disabled_rules, keep=keep)
        after_rules = state.original, state.incoming, state.review
        report('Reviewing small wording edits...')

        def complete(payload, prompt):
            client = self.processor_factory(request.config, request.review_model)
            return client.complete(payload, prompt)

        try:
            original, incoming, review, summary = review_edits(
                *after_rules, request.review_model, complete, request.document_id,
                testing=request.config.get('testing', False), keep=keep)
            after_ai = original, incoming, review
        except (OSError, ValueError):
            after_ai = after_rules
            summary = 'AI-assisted review could not be applied and recorded. Edits remain pending.'
        summary = f'{spelling_summary} {summary}'
        if getattr(self, 'house_summary', None):
            summary = f'{self.house_summary} {summary}'
        if addressed:
            summary = f'{addressees.summary(addressed)} {summary}'
        if speakers is not None:
            summary = f'{speakers.summary} {summary}'
        if head is not None:
            off_record_undo, before_rules, after_rules, after_ai = (
                joined_snapshot(head, head, snapshot) for snapshot in (off_record_undo, before_rules, after_rules, after_ai))
        return AssistedReview(request.original, off_record_undo, before_rules, after_rules, after_ai, summary,
                              spelling)

    def _spelling_sources(self):
        """Confirmed notice spellings, the job vocabulary and the rough's named speakers."""
        request = self.request
        sources = {name.casefold(): (kind, name) for kind, name in request.sources}
        for name in request.vocabulary:
            sources.setdefault(name.casefold(), ('name', name))
        # The reporter's house spellings are settled; the spelling review leaves them unmarked.
        if getattr(self, 'house', None) is not None:
            for form in self.house.forms():
                sources.setdefault(form.casefold(), ('house', form))
        if request.original is not None:
            from app.src.casecat.fields import field_values
            from app.src.casecat.elements import speaker_number
            try:
                values = field_values(request.original)
            except ValueError:
                values = {}  # Linked speaker fields that disagree confirm nothing.
            for field, value in values.items():
                number = speaker_number(field)
                # EZ speakers 300 and up are standard titles such as THE WITNESS.
                if number and int(number) < 300 and value.strip() and not value.startswith('['):
                    sources.setdefault(value.casefold(), ('person', value))
        return tuple(sources.values())

    def _review_spelling(self, rough, draft, report):
        """Words whose exact spelling needs the reporter's judgment, and a summary line."""
        request = self.request
        report('Checking spellings...')

        def complete(payload, prompt):
            return self.processor_factory(request.config, request.review_model).complete(payload, prompt)

        testing = request.config.get('testing', False)
        folder = Path(tempfile.gettempdir())/'bababui-transcriptions'
        name = f'spelling-review-{uuid4().hex}'
        saved = count(1)

        def save(entry):
            atomic_bytes(folder/f'{name}-{entry["kind"]}-{next(saved)}.json',
                         json.dumps(entry, ensure_ascii=False, indent=2).encode('utf-8'))
        try:
            result = review_spelling(rough, draft, complete, sources=self._spelling_sources(),
                                     context=request.context, progress=report, log=save if testing else None)
        except Exception:  # noqa: BLE001 - any model or network failure
            # The draft is still useful without spelling marks.
            return None, 'Spelling review could not run.'
        if testing:
            atomic_bytes(folder/f'{name}-result.json',
                         json.dumps(result.record(), ensure_ascii=False, indent=2).encode('utf-8'))
        return result.record(), result.summary


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
