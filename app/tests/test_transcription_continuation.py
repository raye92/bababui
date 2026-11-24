import json
from pathlib import Path
from types import SimpleNamespace as NS
from app.tests.audio_responses import raw_interactions

import pytest

from app.src.audio_pipeline import AudioPipeline, Word, media


def passage(text, speaker, start):
    return [Word(token, speaker, start + i, start + i + .5)
            for i, token in enumerate(text.split())]


def response(status, words):
    text = ' '.join(w.text for w in words)
    annotations, pos = [], 0
    for w in words:
        end = pos + len(w.text.encode('utf-8'))
        annotations.append(NS(type='word_info', speaker=w.speaker, start_index=pos,
                              end_index=end,
                              start_offset=None if w.start is None else f'{w.start}s',
                              end_offset=None if w.end is None else f'{w.end}s'))
        pos = end + 1
    block = NS(type='text', text=text, annotations=annotations)
    return NS(status=status, steps=[NS(type='model_output', content=[block])])


@pytest.fixture
def recording(tmp_path, monkeypatch):
    """Exercise the normal file/cache path with recorded clip bounds in place of PCM."""
    def setup(duration, responses):
        wav = tmp_path / 'recording.wav'
        wav.write_text(json.dumps([0, duration]))
        requests = []
        replies = iter(responses)

        def prepare(source, bounds, destination):
            origin, _ = json.loads(Path(source).read_text())
            destination.write_text(json.dumps([origin + bounds['start'], origin + bounds['end']]))

        def upload(file, config):
            return NS(uri=Path(file).read_text(), state='ACTIVE')

        def create(input, generation_config, **kwargs):
            start, end = json.loads(input[0]['uri'])
            mode = generation_config['transcription_config']['mode']
            assert mode['type'] == 'verbatim' and mode['diarization_mode'] == 'speaker'
            requests.append((start, end, mode.get('timestamp_granularities')))
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

        def duration_of(path):
            start, end = json.loads(Path(path).read_text())
            return end - start

        monkeypatch.setattr(media, 'prepare', prepare)
        monkeypatch.setattr(media, 'probe', duration_of)
        sdk = NS(files=NS(upload=upload), interactions=raw_interactions(create))
        return AudioPipeline('fake', tmp_path / 'cache', sdk), wav, requests
    return setup


def test_resumes_at_mealer_cutoff_and_matches_speakers_through_next_chunk(recording):
    question = 'Can you read this exhibit aloud'
    answer = 'I have the letter right here'
    next_overlap = 'Mark the next page please'
    first = (passage('Opening.', 'a', 10) + passage(question, 'a', 1344.5)
             + passage(answer, 'b', 1374) + [Word('unfin', 'b', 1379.5, None)])
    resumed = (passage(question, 'b', 25) + passage(answer, 'a', 54.5)
               + passage('Finished.', 'a', 60) + passage('Thank you.', 'b', 63)
               + passage(next_overlap, 'c', 447.5))
    following = passage(next_overlap, 'b', 27) + passage('Closing.', 'b', 90)
    pipeline, wav, requests = recording(1840, [
        response('incomplete', first), response('completed', resumed), response('completed', following)])

    from app.src.transcription_output import RunOutput
    output = RunOutput.create(wav.parent / 'runs', 'Hearing')
    pipeline.output = output
    result = pipeline.run(wav)
    assert json.loads((output.directory / 'Hearing - chunk 1 - response.json').read_bytes())['status'] == 'incomplete'
    assert json.loads((output.directory / 'Hearing - chunk 1 - continuation response.json').read_bytes())['status'] == 'completed'

    assert result.text.splitlines() == [f'Speaker 1: Opening. {question}',
                                        f'Speaker 2: {answer} Finished.',
                                        'Speaker 1: Thank you.',
                                        f'Speaker 3: {next_overlap} Closing.']
    assert next(w for w in result.words if w.text == 'Finished.') == Word('Finished.', 'Speaker 2', 1379.5, 1380)
    assert result.words[-1] == Word('Closing.', 'Speaker 3', 1830, 1830.5)
    assert any('Unmatched speaker' in w and 'Speaker 3' in w for w in result.warnings)
    assert pipeline.run(wav) == result
    assert requests == [(0, 1800, ['word']), (1319.5, 1800, ['word']), (1740, 1840, ['word'])]


@pytest.mark.parametrize('retry', ['incomplete', 'failed', 'overlap only', 'out of bounds',
                                   'drifting overlap', 'untimed overlap', 'malformed tail'])
def test_fallback_uses_full_wording_and_recovers_measured_times(recording, retry):
    overlap = 'we read these five pages'
    early = 'early timed evidence'
    later = 'beyond the old cutoff'
    prefix = passage(early, 'a', 4) + passage(overlap, 'b', 85.5)
    repeated = passage(overlap, 'swapped', 55.5)
    if retry == 'failed':
        second = RuntimeError('upload unavailable')
    elif retry == 'incomplete':
        second = response('incomplete', repeated + passage(later, 'swapped', 62))
    elif retry == 'out of bounds':
        second = response('completed', repeated + passage(later, 'swapped', 200))
    elif retry == 'drifting overlap':
        # Even the start of the last repeated word can drift past the original cutoff.
        second = response('completed', passage(overlap, 'swapped', 56.2))
    elif retry == 'untimed overlap':
        second = response('completed', [Word(w.text, 'swapped', None, None) for w in repeated]
                          + passage(later, 'swapped', 62))
    elif retry == 'malformed tail':
        second = response('completed', repeated + passage(later, 'swapped', 62)
                          + passage('fragment', 'swapped', 68))
        second.steps[0].content[0].annotations[-1].end_index = 4000
    else:
        second = response('completed', repeated)
    full = [Word(early.upper(), 'final A', None, None),
            Word(f'{overlap} {later} closing remarks', 'final B', None, None)]
    pipeline, wav, requests = recording(160.25, [
        response('incomplete', prefix), second, response('completed', full)])

    result = pipeline.run(wav)

    assert requests == [(0, 160.25, ['word']), (30, 160.25, ['word']), (0, 160.25, None)]
    assert result.text == f'Speaker 1: {early.upper()}\nSpeaker 2: {overlap} {later} closing remarks'
    assert result.words[0] == Word('EARLY', 'Speaker 1', 4, 4.5)
    assert next(w.start for w in result.words if w.text == 'pages') == 89.5
    later_measured = retry in ('incomplete', 'untimed overlap', 'malformed tail')
    assert next(w.start for w in result.words if w.text == 'beyond') == (92 if later_measured else None)
    assert result.words[-1].start is None
    assert pipeline.run(wav) == result and len(requests) == 3


def test_short_partial_skips_continuation_and_recovers_early_timing(recording):
    partial = passage('three early words', 'a', 10) + [Word('invalid', 'a', 110, 500)]
    fallback = [Word('Three early words remain.', 'b', None, None)]
    pipeline, wav, requests = recording(160, [
        response('incomplete', partial), response('completed', fallback)])

    result = pipeline.run(wav)

    assert result.text == 'Speaker 1: Three early words remain.'
    assert [w.start for w in result.words] == [10, 11, 12, None]
    assert requests == [(0, 160, ['word']), (0, 160, None)]


def test_distinctive_untimed_overlap_matches_speaker_and_keeps_new_repetition(recording):
    phrase = 'Please read the last line of that exhibit again.'
    prefix = passage(phrase, 'first', 81.5)
    repeated = [Word(w.text, 'reassigned', None, None) for w in prefix]
    retry = repeated + [Word('Again?', 'reassigned', 60.25, 60.75)]
    pipeline, wav, requests = recording(160, [response('incomplete', prefix), response('completed', retry)])

    result = pipeline.run(wav)

    assert result.text == f'Speaker 1: {phrase} Again?'
    assert result.words[-2:] == (Word('again.', 'Speaker 1', 89.5, 90),
                                 Word('Again?', 'Speaker 1', 90.25, 90.75))
    assert not result.warnings
    assert requests == [(0, 160, ['word']), (30, 160, ['word'])]


def test_resume_without_spoken_overlap_keeps_prefix_in_short_final_chunk(recording):
    shared = 'Can we read this back'
    first = passage('Opening.', 'a', 10) + passage('Ready.', 'c', 100) + passage(shared, 'b', 1768)
    prefix = passage(shared, 'same', 28) + passage('These are my recorded words.', 'same', 85.5)
    retry = passage('Now we can continue.', 'new', 62)
    pipeline, wav, requests = recording(1900, [
        response('completed', first), response('incomplete', prefix), response('completed', retry)])

    from app.src.transcription_output import RunOutput
    output = RunOutput.create(wav.parent / 'runs', 'Hearing')
    pipeline.output = output
    result = pipeline.run(wav)
    assert json.loads((output.directory / 'Hearing - chunk 2 - response.json').read_bytes())['status'] == 'incomplete'
    assert json.loads((output.directory / 'Hearing - chunk 2 - continuation response.json').read_bytes())['status'] == 'completed'

    assert result.text.splitlines() == ['Speaker 1: Opening.', 'Speaker 2: Ready.',
                                        f'Speaker 3: {shared} These are my recorded words.',
                                        'Speaker 4: Now we can continue.']
    assert result.words[-1] == Word('continue.', 'Speaker 4', 1835, 1835.5)
    speaker_warnings = [w for w in result.warnings if 'Unmatched speaker' in w]
    assert len(speaker_warnings) == 1 and 'Speaker 4' in speaker_warnings[0] and 'chunk 2' in speaker_warnings[0]
    assert pipeline.run(wav) == result
    assert requests == [(0, 1800, ['word']), (1740, 1900, ['word']), (1770, 1900, ['word'])]


def test_partial_annotation_cut_inside_utf8_keeps_the_earlier_timed_words(recording):
    prefix = passage('Early words here.', 'a', 2) + passage('Please read these five pages', 'a', 85.5)
    partial = response('incomplete', prefix + [Word('Café', 'a', 90, None)])
    partial.steps[0].content[0].annotations[-1].end_index -= 1
    retry = passage('Please read these five pages', 'b', 55.5) + passage('Café closed.', 'b', 60)
    pipeline, wav, requests = recording(160, [partial, response('completed', retry)])

    result = pipeline.run(wav)

    assert result.text == 'Speaker 1: Early words here. Please read these five pages Café closed.'
    assert next(w.start for w in result.words if w.text == 'Café') == 90
    assert requests == [(0, 160, ['word']), (30, 160, ['word'])]

def test_failed_continuation_export_stops_before_fallback(recording, monkeypatch):
    from app.src import transcription_output

    prefix = passage('Words from the initial response.', 'a', 82)
    pipeline, wav, requests = recording(160, [
        response('incomplete', prefix), response('completed', prefix)])
    pipeline.output = transcription_output.RunOutput.create(wav.parent / 'runs', 'Hearing')
    write = transcription_output.atomic_bytes

    def fail_continuation(path, data):
        if 'continuation response' in path.name:
            raise OSError('disk full')
        write(path, data)

    monkeypatch.setattr(transcription_output, 'atomic_bytes', fail_continuation)
    with pytest.raises(OSError, match='disk full'):
        pipeline.run(wav)
    assert len(requests) == 2
    assert pipeline.output.path(' - chunk 1 - response.json').is_file()
