from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from app.src.jobs import TranscriptionCoordinator
from transcript_formatting import TranscriptFormatter


@pytest.mark.parametrize('fails', [False, True])
def test_shared_transcription_one_call_and_same_outcome(tmp_path, fails):
    wav = tmp_path/'one.wav'
    wav.write_bytes(b'same audio')
    copy = tmp_path/'copy.wav'
    copy.write_bytes(wav.read_bytes())
    started, release, waiting = Event(), Event(), Event()
    calls = []
    class Pipeline:
        def run(self, path, progress):
            calls.append(path)
            started.set()
            assert release.wait(5)
            if fails:
                raise ValueError('Transcription failed')
            return 'Speaker 1: Hello', []
    coordinator = TranscriptionCoordinator()
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(coordinator.run, wav, 'gemini-3.5-transcribe', Pipeline(), lambda _: None)
        assert started.wait(5)
        b = pool.submit(coordinator.run, copy, 'gemini-3.5-transcribe', Pipeline(), lambda _: waiting.set())
        assert waiting.wait(5)
        release.set()
        for result in (a, b):
            if fails:
                with pytest.raises(ValueError, match='Transcription failed'):
                    result.result(5)
            else:
                assert result.result(5) == ('Speaker 1: Hello', [])
    assert len(calls) == 1


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
        def __init__(self, *args):
            pass
        def run(self, path, progress):
            calls.append('transcribe')
            entered.set()
            assert release.wait(5)
            return 'Audio transcript', []
    class Processor:
        def __init__(self, config, model):
            self.model = model
        def check_ready(self):
            pass
        def complete(self, text, prompt):
            assert wav.with_suffix('.raw.txt').read_text(encoding='utf-8') == text
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
    assert results == [('first', TranscriptFormatter().apply_formatting('success')[0], [])]
    assert failures == [('second', 'Formatting failed')]
    assert set(finished) == {'first', 'second'} and not manager.workers
    assert calls.count('transcribe') == 1
    assert ('success', 'Audio transcript', 'Captured prompt') in calls


def test_worker_numbers_model_output_before_emitting_incoming(tmp_path):
    from app.src.jobs import ProcessingWorker, Request

    wav = tmp_path / 'sample.wav'
    wav.write_bytes(b'audio')
    output = (
        'EXAMINATION\nBY SPEAKER 2:\n'
        '     Q    Please describe the records you reviewed before the examination.\n'
        + '\n'.join(f'     Q    Question {i}?' for i in range(23)))

    class Pipeline:
        def __init__(self, *args):
            pass

        def run(self, path, progress):
            return 'Speaker 2: Question?', ['Transcription warning']

    class Processor:
        def __init__(self, *args):
            pass

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            assert text == 'Speaker 2: Question?'
            assert wav.with_suffix('.raw.txt').read_text(encoding='utf-8') == text
            return output

    worker = ProcessingWorker(
        Request('document', str(wav), 'model', 'transcribe', 'rules', {}),
        TranscriptionCoordinator(), Pipeline, Processor)
    results, failures = [], []
    worker.succeeded.connect(lambda *args: results.append(args))
    worker.failed.connect(lambda *args: failures.append(args))
    worker.run()

    assert not failures
    identifier, incoming, warnings = results[0]
    assert identifier == 'document'
    assert warnings == ['Transcription warning']
    assert incoming.count('\f') == 1
    assert '          1                          EXAMINATION' in incoming
    assert '          2    BY SPEAKER 2:' in incoming
    assert '          3         Q    Please describe the records you reviewed\n' in incoming
    assert '          4    before the examination.\n' in incoming
    assert '          1         Q    Question 21?' in incoming
    assert TranscriptFormatter().strip_formatting(incoming) == ' ' * 22 + output
