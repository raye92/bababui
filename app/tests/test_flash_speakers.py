import pytest

from app.src import audio_pipeline as audio
from app.src.audio_pipeline import Word


def words(text, speaker, start=0):
    return [Word(surface, speaker, start + i, start + i + .5)
            for i, surface in enumerate(text.split())]


def resolve(chunks, flash):
    from app.src.flash_speakers import apply_flash_speakers
    result = apply_flash_speakers(chunks, flash)
    for original, labelled in zip(chunks, result, strict=True):
        assert [(w.text, w.start, w.end) for w in labelled] == [
            (w.text, w.start, w.end) for w in original]
    return [[w.speaker for w in chunk] for chunk in result]


def test_returning_voice_is_resolved_outside_overlap_and_local_numbers_can_be_reused():
    first = words('Morning counsel.', '1') + words('All set.', '2') + words('My oath.', '3')
    second = words('Next question.', '1', 1800) + words('Yeah, again I remember.', '5', 1810)
    flash = ('Speaker 1: Morning counsel.\nSpeaker 2: All set.\nSpeaker 3: My oath.\n'
             'Speaker 2: Next question.\nSpeaker 3: Again I remember.')
    assert resolve([first, second], flash) == [
        ['Speaker 1'] * 2 + ['Speaker 2'] * 2 + ['Speaker 3'] * 2,
        ['Speaker 2'] * 2 + ['Speaker 3'] * 4]


def test_flash_switch_and_gap_inside_one_transcribe_turn():
    source = words('the body parts. Well, that is correct.', '4')
    flash = 'Speaker 2: The body\nSpeaker 1: That is correct.'
    assert resolve([source], flash) == [['Speaker 2'] * 3 + ['Speaker 1'] * 4]
    source = words('Yes. Okay. Doctor are you a practicing surgeon?', '4')
    assert resolve([source], 'Speaker 3: Yes.\nSpeaker 1: Okay. Doctor, are you a practicing surgeon?') == [
        ['Speaker 3'] + ['Speaker 1'] * 7]


def test_backup_places_omitted_phrase_with_outgoing_speaker_and_keeps_wording():
    source = words('You wrote letters to the judge claiming that', '5') + words('I object.', '2', 12)
    flash = 'Speaker 1: You wrote letters.\nSpeaker 2: I object.'
    assert resolve([source], flash) == [['Speaker 1'] * 8 + ['Speaker 2'] * 2]


def test_flash_only_text_is_never_inserted_and_unlabelled_continuations_are_kept():
    source = [Word('Dr.', None, None, None), Word('Lee,', None, None, None),
              Word('do', None, 5, 5.1), Word('you?', None, 5.1, 5.3), Word('Yes.', None, 6, 6.2)]
    flash = '**Speaker 2:** Doctor Lee,\n\nuh, do you?\n\n**Speaker 1:** Yes.'
    assert resolve([source], flash) == [['Speaker 2'] * 4 + ['Speaker 1']]


def test_unrelated_or_unlabelled_response_cannot_become_recording_speakers():
    from app.src.flash_speakers import apply_flash_speakers
    for flash in ('no labels here', 'Speaker 1: Completely unrelated.'):
        with pytest.raises(ValueError, match='Flash'):
            apply_flash_speakers([words('Original speech.', '1')], flash)
    with pytest.raises(ValueError, match='Flash'):
        apply_flash_speakers([words('The original witness discussed a procedure.', '1')],
                             'Speaker 1: The default microphone only records static.')


def test_an_untimed_legacy_turn_can_contain_a_flash_handoff():
    from app.src.flash_speakers import apply_flash_speakers
    old = Word('Yes.  Okay. Doctor are you ready?', 'local', None, None)
    flash = 'Speaker 3: Yes.\nSpeaker 1: Okay. Doctor, are you ready?'
    assert apply_flash_speakers([[old]], flash) == [[Word('Yes.', 'Speaker 3', None, None),
        Word('Okay. Doctor are you ready?', 'Speaker 1', None, None)]]


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
                'Speaker 3: Yes.\nSpeaker 1: Okay. We can resume.')
    monkeypatch.setattr(audio.AudioPipeline, '_request_flash', flash, raising=False)
    cache = tmp_path / 'cache'
    output = RunOutput.create(tmp_path, 'run')
    pipeline = audio.AudioPipeline('fake', cache, output=output)
    result = pipeline.run(wav)
    assert result.text.endswith('Speaker 3: Yes.\nSpeaker 1: Okay. We can resume.')
    assert not any('Unmatched speaker' in warning for warning in result.warnings)
    assert calls == ['chunk 1', 'chunk 2', ('flash', 1850)]
    assert pipeline.run(wav) == result
    assert audio.AudioPipeline('', cache, cache_mode='saved').run(wav) == result
    assert len(calls) == 3
    assert any('flash' in key.lower() for key in output.files)
