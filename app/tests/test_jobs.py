from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event
import pytest
from app.src.audio_pipeline import Transcription, Word
from app.src.jobs import TranscriptionCoordinator
from shared.transcript_formatting import TranscriptFormatter


@pytest.mark.parametrize('fails', [False, True])
def test_shared_transcription_one_call_and_same_outcome(tmp_path, fails):
    wav = tmp_path/'one.wav'
    wav.write_bytes(b'same audio')
    copy = tmp_path/'copy.wav'
    copy.write_bytes(wav.read_bytes())
    started, release, waiting = Event(), Event(), Event()
    calls = []
    from app.src.transcription_output import RunOutput
    outputs = [RunOutput.create(tmp_path / 'runs', name) for name in ('First', 'Second')]
    class Pipeline:
        def run(self, path, progress):
            calls.append(path)
            started.set()
            assert release.wait(5)
            outputs[0].save(' - chunk 1 - response.json', b'{"status":"incomplete"}')
            if fails:
                raise ValueError('Transcription failed')
            return Transcription('Speaker 1: Hello', (), (), 1000, sha256(path.read_bytes()).hexdigest())
    coordinator = TranscriptionCoordinator()
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(coordinator.run, wav, 'gemini-3.5-transcribe', Pipeline(), lambda _: None, output=outputs[0])
        assert started.wait(5)
        b = pool.submit(coordinator.run, copy, 'gemini-3.5-transcribe', Pipeline(), lambda _: waiting.set(), output=outputs[1])
        assert waiting.wait(5)
        release.set()
        for result in (a, b):
            if fails:
                with pytest.raises(ValueError, match='Transcription failed'):
                    result.result(5)
            else:
                assert result.result(5).text == 'Speaker 1: Hello'
    assert len(calls) == 1
    for output in outputs:
        assert output.path(' - chunk 1 - response.json').read_bytes() == b'{"status":"incomplete"}'


@pytest.mark.parametrize('other_names', [(), ('Other',)])
def test_changed_waiting_tab_does_not_receive_or_upload_a_different_recording(tmp_path, other_names):
    first_wav, other_wav = (tmp_path / name for name in ('first.wav', 'other.wav'))
    for wav in (first_wav, other_wav):
        wav.write_bytes(b'first recording')
    started, release, waiting = Event(), Event(), Event()
    paths = []

    class Pipeline:
        def run(self, path, progress, **kwargs):
            paths.append(path)
            started.set()
            assert release.wait(5)
            return Transcription('Speech', (), (), 5000, sha256(path.read_bytes()).hexdigest())

    coordinator = TranscriptionCoordinator()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(coordinator.run, first_wav, 'model', Pipeline(), lambda _: None)
        assert started.wait(5)
        other = pool.submit(coordinator.run, other_wav, 'model', Pipeline(), lambda _: waiting.set(),
                            vocabulary=other_names)
        try:
            assert waiting.wait(5)
            other_wav.write_bytes(b'replacement')
        finally:
            release.set()
        assert first.result(5).text == 'Speech'
        with pytest.raises(ValueError, match='WAV changed'):
            other.result(5)
    assert paths == [first_wav]


def test_fresh_transcription_waits_and_runs_again_after_an_identical_request(tmp_path):
    wav = tmp_path / 'hearing.wav'
    wav.write_bytes(b'audio')
    digest = sha256(wav.read_bytes()).hexdigest()
    entered, release, waiting = Event(), Event(), Event()
    calls = []

    class Pipeline:
        def run(self, path, progress, *, expected_digest=None):
            calls.append(expected_digest)
            entered.set()
            assert release.wait(5)
            return Transcription(str(len(calls)), (), (), 1000, digest)

    coordinator = TranscriptionCoordinator()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(coordinator.run, wav, 'model', Pipeline(), lambda _: None)
        assert entered.wait(5)
        fresh = pool.submit(coordinator.run, wav, 'model', Pipeline(), lambda _: waiting.set(), fresh=True)
        try:
            assert waiting.wait(5)
            assert calls == [None]
        finally:
            release.set()
        assert first.result().text == '1' and fresh.result().text == '2'
    assert calls == [None, digest]


def test_real_threads_route_results_and_failures_with_frozen_requests(tmp_path):
    import os
    import time
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.src.jobs import JobManager, ProcessingWorker, Request
    app = QApplication.instance() or QApplication([])
    wav = tmp_path/'one.wav'
    wav.write_bytes(b'audio')
    entered, release = Event(), Event()
    calls = []
    class Pipeline:
        def __init__(self, *args, output, legacy_cache=None):
            self.output = output
        def run(self, path, progress):
            calls.append('transcribe')
            entered.set()
            assert release.wait(5)
            self.output.save(' - chunk 1 - response.json', b'{"status":"completed"}')
            return Transcription('Audio transcript', (), (), 1000, sha256(path.read_bytes()).hexdigest())
    class Processor:
        def __init__(self, config, model):
            self.model = model
        def check_ready(self):
            pass
        def complete(self, text, prompt):
            assert any(f.read_text(encoding='utf-8') == text for f in (tmp_path / 'data/transcriptions').glob('*/*.txt'))
            calls.append((self.model, text, prompt))
            if self.model == 'fail':
                raise ValueError('Formatting failed')
            return self.model
    def factory(request, coordinator):
        return ProcessingWorker(request, coordinator, Pipeline, Processor)
    manager = JobManager(worker_factory=factory)
    results, failures, finished, progress = [], [], [], []
    manager.succeeded.connect(lambda *args: results.append(args))
    manager.failed.connect(lambda *args: failures.append(args))
    folders = {}
    manager.output_folder.connect(lambda doc, folder: folders.update({doc: Path(folder)}))
    manager.completed.connect(finished.append)
    manager.progress.connect(lambda *args: progress.append(args))
    manager.start(Request('first', str(wav), 'success', 'gemini-3.5-transcribe', 'Captured prompt', {}))
    assert entered.wait(5)
    manager.start(Request('second', str(wav), 'fail', 'gemini-3.5-transcribe', 'Other prompt', {}))
    with pytest.raises(ValueError, match='already processing'):
        manager.start(Request('second', str(wav), 'fail', 'gemini-3.5-transcribe', 'Other', {}))
    deadline = time.monotonic()+5
    try:
        while not any('shared' in message for _, message in progress) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert any('shared' in message for _, message in progress)
    finally:
        release.set()
        while manager.workers and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        for worker in list(manager.workers.values()):
            worker.wait(5000)
        app.processEvents()
    assert results == [('first', 'success', [], None)]
    assert failures == [('second', 'Formatting failed')]
    assert set(finished) == {'first', 'second'} and not manager.workers
    assert {path.name for path in folders.values()} == {'one', 'one (2)'}
    for folder in folders.values():
        assert (folder / f'{folder.name}.txt').read_text() == 'Audio transcript'
        assert (folder / f'{folder.name} - chunk 1 - response.json').read_bytes() == b'{"status":"completed"}'
    assert calls.count('transcribe') == 1
    assert ('success', 'Audio transcript', 'Captured prompt') in calls


def test_worker_leaves_page_layout_to_casecat(tmp_path):
    from app.src.jobs import ProcessingWorker, Request

    wav = tmp_path / 'sample.wav'
    wav.write_bytes(b'audio')
    output = (
        'EXAMINATION\nBY SPEAKER 2:\n'
        '     Q    Please describe the records you reviewed before the examination.\n'
        + '\n'.join(f'     Q    Question {i}?' for i in range(23)))

    class Pipeline:
        def __init__(self, *args, output=None, legacy_cache=None):
            pass

        def run(self, path, progress):
            return Transcription('Speaker 2: Question?', (), ('Transcription warning',), 1000,
                                 sha256(path.read_bytes()).hexdigest())

    class Processor:
        def __init__(self, *args):
            pass

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            assert text == 'Speaker 2: Question?'
            assert any(f.read_text(encoding='utf-8') == text for f in (tmp_path / 'data/transcriptions').glob('*/*.txt'))
            return output

    worker = ProcessingWorker(
        Request('document', str(wav), 'model', 'transcribe', 'rules', {}),
        TranscriptionCoordinator(), Pipeline, Processor)
    results, failures = [], []
    worker.succeeded.connect(lambda *args: results.append(args))
    worker.failed.connect(lambda *args: failures.append(args))
    worker.run()

    assert not failures
    identifier, incoming, warnings, alignment = results[0]
    assert identifier == 'document'
    assert warnings == ['Transcription warning']
    assert incoming == output
    assert alignment is None


@pytest.mark.parametrize('transcribe,format_text,review', [
    (True, False, False), (False, True, False), (False, False, True),
    (True, True, False), (True, False, True), (False, True, True), (True, True, True),
])
def test_selected_stages_use_their_own_inputs(tmp_path, transcribe, format_text, review):
    from app.src import jobs
    from app.tests.test_ai_review import revision

    wav = tmp_path / 'source.wav'
    wav.write_bytes(b'speech')
    digest = sha256(wav.read_bytes()).hexdigest()
    calls, saved, graded, plain, errors = [], [], [], [], []

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            calls.append('transcribe')
            return Transcription('New raw speech', (), (), 1000, digest)

    class Processor:
        def __init__(self, _, model):
            self.model = model

        def check_ready(self):
            assert format_text

        def complete(self, text, prompt):
            calls.append(self.model)
            if self.model == 'formatter':
                assert text == ('New raw speech' if transcribe else 'Saved raw speech')
                return 'I saw a tan car.'
            import json
            assert json.loads(text)[0]['proposed_word'] == ('tan' if format_text else 'red')
            return '{"1":"accept"}'

    steps = jobs.RunSteps(transcribe, format_text, review, 'refresh' if transcribe else 'reuse')
    expected_review = format_text or review
    assert steps.review == expected_review
    worker = jobs.ProcessingWorker(jobs.Request(
        'doc', str(wav), 'formatter', 'transcriber', 'Format' if format_text else '', {},
        original=revision('I saw a blue car.'), review_model='reviewer', steps=steps,
        raw_transcript='Saved raw speech', raw_wav_sha256=digest,
        incoming=revision('I saw a red car.') if review and not format_text else None),
        TranscriptionCoordinator(), Pipeline, Processor)
    worker.transcribed.connect(lambda *args: saved.append(args))
    worker.succeeded.connect(lambda *args: plain.append(args))
    worker.reviewed.connect(lambda *args: graded.append(args))
    worker.failed.connect(lambda *args: errors.append(args))
    worker.run()
    assert not errors
    assert calls == [name for name, enabled in (
        ('transcribe', transcribe), ('formatter', format_text), ('reviewer', expected_review)) if enabled]
    assert saved == ([('doc', 'New raw speech', digest)] if transcribe else [])
    assert bool(worker.output) == transcribe
    if expected_review:
        assert graded[0][1].after_ai[0].text == ('I saw a tan car.' if format_text else 'I saw a red car.')
    else:
        assert len(plain) == 1


@pytest.mark.parametrize('recording', ['timed original', 'untimed original', 'untimed attachment', 'no timestamps'])
def test_worker_delivers_timing_with_incoming_review(tmp_path, monkeypatch, recording):
    import wave
    from app.src.audio_pipeline import AudioPipeline, media
    from app.src.casecat import codec
    from app.src.jobs import ProcessingWorker, Request
    from app.src.speech_alignment import NO_TIMESTAMPS
    from app.tests.test_native_audio import audio_archive

    bundle = audio_archive(tmp_path)
    job = codec.load_job(bundle, bundle.jobs[0])
    wav = tmp_path / 'sample.wav'
    duration, seconds = 40, (4, 10, 16)
    if recording == 'untimed attachment':
        duration, seconds = 60, (24, 30, 36)
        wav = tmp_path / 'another recorder.wav'
        with wave.open(str(wav), 'wb') as out:
            out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            out.writeframes(bytes(32000 * duration))
    clips = []
    monkeypatch.setattr(media, 'probe', lambda path: duration)
    monkeypatch.setattr(media, 'prepare', lambda path, segment, dest: clips.append(segment))

    class Pipeline(AudioPipeline):
        def __init__(self, *args, output=None, legacy_cache=None):
            super().__init__('fake', tmp_path / 'cache', output=output)

        def transcribe_segment(self, path, progress, *, timing_only=False, segment=None):
            words = ('Alpha', 'beta', 'gamma.')
            if recording == 'no timestamps' or (not timing_only and recording != 'timed original'):
                return [Word(word, 'first', None, None) for word in words]
            start, end = clips[-1]['start'], clips[-1]['end']
            return [Word(word, 'first', second - start, second - start + .1)
                    for word, second in zip(words, seconds) if start <= second < end]

    class Processor:
        def __init__(self, *args):
            pass

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            return 'Alpha New beta gamma.'

    worker = ProcessingWorker(
        Request('test', str(wav), 'model', 'transcribe', 'rules', {}, original=job.baseline,
                bundle=bundle, job=job),
        TranscriptionCoordinator(), Pipeline, Processor)
    results = []
    worker.succeeded.connect(lambda *args: results.append(args))
    worker.run()
    _, incoming, warnings, alignment = results[0]
    assert incoming == 'Alpha New beta gamma.'
    assert worker.output.path('.txt').read_text(encoding='utf-8') == 'Speaker 1: Alpha beta gamma.'
    if recording == 'no timestamps':
        assert warnings == ['No word timestamps for chunk 1.', NO_TIMESTAMPS]
        assert alignment is None
    else:
        assert not warnings
        assert alignment.matches_wav(wav)
        assert alignment.stroke_ms == tuple(s * 1000 for s in seconds)
        assert alignment.playback().position_ms(job.baseline, job.text.index('beta')) == seconds[1] * 1000
