import pytest

from app.src import audio_pipeline as audio
from app.src.audio_pipeline import Word
from app.src.flash_speakers import align_flash_words
from app.src.vocabulary_reconciliation import reconcile_vocabulary


def words(text, speaker, start=0):
    return [Word(surface, speaker, start + i, start + i + .5)
            for i, surface in enumerate(text.split())]


def test_flash_supplies_words_turns_and_punctuation_and_transcribe_supplies_times():
    native = words('Yes. Okay. Next question.', 'native')
    flash = 'Speaker 2: YES!\nSpeaker 1: Next question?'
    result, = align_flash_words([native], flash)
    assert audio.render(result) == flash
    assert [(w.text, w.start, w.end) for w in result] == [
        ('YES!', 0, .5), ('Next', 2, 2.5), ('question?', 3, 3.5)]


def test_flash_only_interruption_and_unmatched_words_stay_untimed():
    native = words('I recall the meeting.', 'other')
    flash = 'Speaker 4: I\nSpeaker 7: Wait!\nSpeaker 4: recall the hearing.'
    result, = align_flash_words([native], flash)
    assert audio.render(result) == flash
    assert [(w.start, w.end) for w in result] == [(0, .5), (None, None), (1, 1.5), (2, 2.5), (None, None)]


def test_compound_word_needs_a_complete_timed_match():
    native = words('first L4 L5 then L3 L5 today', 'a')
    result, = align_flash_words([native], 'Speaker 1: First L4-L5, then L4-L5 today.')
    assert [(w.text, w.start, w.end) for w in result] == [
        ('First', 0, .5), ('L4-L5,', 1, 2.5), ('then', 3, 3.5),
        ('L4-L5', None, None), ('today.', 6, 6.5)]


def test_explicit_turns_survive_legacy_untimed_records_and_notice_spelling():
    native = [Word('They called Jack Son yesterday.', 'local', None, None)]
    flash = '**Speaker 3:** They called Jack\n**Speaker 3:**\nSon yesterday.'
    result, = align_flash_words([native], flash)
    expected = 'Speaker 3: They called Jack\nSpeaker 3: Son yesterday.'
    assert audio.render(result) == expected
    assert all(w.start is None and w.end is None for w in result)
    reconciled = reconcile_vocabulary(result, [(0, 20)] * len(result),
                                      [(0, 20, 'They called Jackson yesterday.')], ('Jackson',))
    assert audio.render(reconciled) == expected


def test_unrelated_or_unlabelled_response_cannot_become_recording_speakers():
    for flash in ('no labels here', 'Speaker 1: Completely unrelated.'):
        with pytest.raises(ValueError, match='Flash'):
            align_flash_words([words('Original speech.', '1')], flash)
    with pytest.raises(ValueError, match='Flash'):
        align_flash_words([words('The original witness discussed a procedure.', '1')],
                             'Speaker 1: The default microphone only records static.')


def test_failed_flash_reuses_native_words_and_only_publishes_a_matched_pass(tmp_path, monkeypatch):
    wav = tmp_path / 'source.wav'
    wav.write_bytes(b'test audio')
    monkeypatch.setattr(audio.media, 'probe', lambda _: 8)
    monkeypatch.setattr(audio.media, 'prepare', lambda *args: None)
    calls = []
    def native(*args, **kwargs):
        calls.append('native')
        return words('First question. Yes.', 'native')
    monkeypatch.setattr(audio.AudioPipeline, 'transcribe_segment', native)
    replies = iter(['unlabelled response', 'Speaker 2: First question.\nSpeaker 3: Yes.'])
    def flash(*args):
        calls.append('flash')
        return next(replies)
    monkeypatch.setattr(audio.AudioPipeline, '_request_flash', flash)
    pipeline = audio.AudioPipeline('test', tmp_path / 'cache')
    with pytest.raises(ValueError, match='Flash'):
        pipeline.run(wav)
    assert not list(pipeline.cache.rglob('flash-speakers*.txt'))
    assert pipeline.run(wav).text == 'Speaker 2: First question.\nSpeaker 3: Yes.'
    assert calls == ['native', 'flash', 'flash']


def test_desktop_reports_a_flash_upload_cleanup_failure_without_promising_a_retry(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    monkeypatch.setattr(audio.media, 'prepare', lambda *args: None)
    def failed_delete(**kwargs):
        raise OSError('offline')
    files = NS(upload=lambda **kwargs: NS(name='files/clip', uri='audio', state='ACTIVE'), delete=failed_delete)
    response = NS(status='completed', steps=[], output_text='Speaker 1: Hello.')
    sdk = NS(files=files, interactions=NS(create=lambda **kwargs: response))
    pipeline = audio.AudioPipeline('test', tmp_path, sdk=sdk)
    messages = []
    assert pipeline._request_flash(tmp_path / 'clip.wav', 1, messages.append) == response.output_text
    assert messages == ['Could not delete the temporary audio upload.']


def test_desktop_requests_one_flash_pass_per_recording_and_reuses_it(tmp_path, monkeypatch):
    from app.src.jobs import ProcessingWorker
    from app.src.transcription_output import RunOutput
    import inspect

    assert inspect.signature(ProcessingWorker.__init__).parameters['pipeline_factory'].default is audio.AudioPipeline
    wav = tmp_path / 'hearing.wav'
    wav.write_bytes(b'hearing')
    calls = []
    monkeypatch.setattr(audio.media, 'probe', lambda _: 1850)
    monkeypatch.setattr(audio.media, 'prepare', lambda path, interval, destination: destination.write_bytes(b'audio'))
    def transcribe(self, path, progress, *, segment):
        calls.append(segment.label)
        shared = 'one two three four five six seven eight nine ten'
        if segment.label == 'chunk 1':
            return words('I am here.', 'a') + words('Doctor is ready.', 'c', 30) + words(shared, 'b', 1750)
        return words(shared, 'x', 10) + words('Yes. Okay. We can resume.', 'y', 70)
    monkeypatch.setattr(audio.AudioPipeline, 'transcribe_segment', transcribe)
    def flash(self, path, duration, progress):
        calls.append(('flash', duration))
        return ('Speaker 1: I am here.\nSpeaker 3: Doctor is ready.\n'
                'Speaker 2: one two three four five six seven eight nine ten\n'
                'Speaker 3: Yes.\nSpeaker 1: We may resume.')
    monkeypatch.setattr(audio.AudioPipeline, '_request_flash', flash, raising=False)
    cache = tmp_path / 'cache'
    output = RunOutput.create(tmp_path, 'run')
    pipeline = audio.AudioPipeline('fake', cache, output=output)
    result = pipeline.run(wav)
    assert result.text.endswith('Speaker 3: Yes.\nSpeaker 1: We may resume.')
    assert [(w.text, w.start) for w in result.words[-4:]] == [
        ('Yes.', 1810), ('We', 1812), ('may', None), ('resume.', 1814)]
    assert not any('Unmatched speaker' in warning for warning in result.warnings)
    assert calls == ['chunk 1', 'chunk 2', ('flash', 1850)]
    assert pipeline.run(wav) == result
    assert audio.AudioPipeline('', cache, cache_mode='saved').run(wav) == result
    assert len(calls) == 3
    assert any('flash' in key.lower() for key in output.files)
