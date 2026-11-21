import hashlib
from types import SimpleNamespace as NS

import pytest

from app.src.audio_pipeline import Word, segments, stitch, parse_words, render


def test_duration_and_chunks():
    assert segments(1800) == [(0, 1800)]
    assert segments(3540) == [(0, 1800), (1740, 3540)]
    assert segments(3540.1) == [(0, 1800), (1740, 3540), (3480, 3540.1)]
    assert segments(5280) == [(0, 1800), (1740, 3540), (3480, 5280)]
    assert segments(5280.1)[-1] == (5220, 5280.1)
    assert segments(7020) == [(0, 1800), (1740, 3540), (3480, 5280), (5220, 7020)]
    assert segments(3600, vocabulary=True) == [(0, 3600)]
    assert segments(3600.1, vocabulary=True) == [(0, 3600), (3540, 3600.1)]
    assert segments(7020, vocabulary=True) == [(0, 3600), (3540, 7020)]
    for duration in (0, -1, 7020.1, float('nan')):
        with pytest.raises(ValueError):
            segments(duration)


def test_overlap_maps_swapped_speakers_and_trims_once():
    words = 'one two three four five six seven eight nine ten'.split()
    a = [Word('Before.', 'a', 1700, 1701)] + [Word(w, 'a', 1750+i, 1751+i) for i, w in enumerate(words)]
    b = [Word(w.upper() if i != 2 else 'THREE!', 'b', 10+i, 11+i) for i, w in enumerate(words)]
    b += [Word('After.', 'b', 70, 71), Word('New.', 'c', 72, 73)]
    stitched, warnings = stitch([a, b])
    text = render(stitched)
    assert text.count('Before.') == text.count('After.') == 1
    assert 'Speaker 1:' in text and 'Speaker 2: New.' in text
    assert len(text.split()) < 24
    assert any('unmatched' in warning.lower() for warning in warnings)
    assert (stitched[-2].start, stitched[-2].end) == (1810, 1811)


def test_unaligned_overlap_uses_timestamp_cut():
    a = [Word('Keep.', 'a', 1760, 1761), Word('Drop.', 'a', 1780, 1781)]
    b = [Word('DropB.', 'b', 10, 11), Word('KeepB.', 'b', 40, 41)]
    stitched, warnings = stitch([a, b])
    text = render(stitched)
    assert 'Keep.' in text and 'KeepB.' in text
    assert 'Drop' not in text
    assert warnings


def test_three_chunks_preserve_speaker_labels_and_trim_both_overlaps():
    first_overlap = 'one two three four five'.split()
    second_overlap = 'six seven eight nine ten'.split()
    a = [Word('Opening.', 'a', 40, 41)]
    a += [Word(w, 'a', 1768+i, 1769+i) for i, w in enumerate(first_overlap)]
    b = [Word(w, 'b', 28+i, 29+i) for i, w in enumerate(first_overlap)]
    b += [Word(w, 'c', 1768+i, 1769+i) for i, w in enumerate(second_overlap)]
    c = [Word(w, 'a', 28+i, 29+i) for i, w in enumerate(second_overlap)]
    c += [Word('Closing.', 'a', 80, 81), Word('New.', 'b', 82, 83)]

    words, warnings = stitch([a, b, c])

    assert render(words) == ('Speaker 1: Opening. one two three four five\n'
                             'Speaker 2: six seven eight nine ten Closing.\nSpeaker 3: New.')
    assert words[-2] == Word('Closing.', 'Speaker 2', 3560, 3561)
    assert any('chunk 3' in warning for warning in warnings)


def test_annotation_bytes_preserve_unicode():
    block = NS(type='text', text='Café? Yes.', annotations=[
        NS(type='word_info', speaker='a', start_index=0, end_index=6, start_offset='0s', end_offset='1s'),
        NS(type='word_info', speaker='b', start_index=7, end_index=11, start_offset='1s', end_offset='2s')])
    response = NS(steps=[NS(type='model_output', content=[block])])
    words = parse_words(response)
    assert [w.text for w in words] == ['Café?', 'Yes.']


@pytest.mark.parametrize('speaker_field', [{}, {'speaker': None}, {'speaker': ''}])
@pytest.mark.parametrize('second_chunk', [False, True])
def test_missing_speaker_preserves_words_and_timestamps(speaker_field, second_chunk):
    block = NS(type='text', text='Who? Me.', annotations=[
        NS(type='word_info', start_index=0, end_index=4, start_offset='40s', end_offset='41s',
           **speaker_field),
        NS(type='word_info', speaker='b', start_index=5, end_index=8, start_offset='42s', end_offset='43s')])
    words = parse_words(NS(steps=[NS(type='model_output', content=[block])]))
    chunks = [[Word('Earlier.', 'a', 0, 1)], words] if second_chunk else [words]
    stitched, _ = stitch(chunks)

    expected = 'Unknown speaker: Who?\nSpeaker 1: Me.'
    if second_chunk:
        expected = 'Speaker 1: Earlier.\nUnknown speaker: Who?\nSpeaker 2: Me.'
    assert render(stitched) == expected
    assert (stitched[-2].start, stitched[-2].end) == ((1780, 1781) if second_chunk else (40, 41))


def test_overlapping_speakers_preserve_transcript_order():
    block = NS(type='text', text='No. How can I?', annotations=[
        NS(type='word_info', speaker='a', start_index=0, end_index=3, start_offset='345.4s', end_offset='345.5s'),
        NS(type='word_info', speaker='b', start_index=4, end_index=7, start_offset='344.8s', end_offset='344.9s'),
        NS(type='word_info', speaker='b', start_index=8, end_index=11, start_offset='344.9s', end_offset='345.1s'),
        NS(type='word_info', speaker='a', start_index=12, end_index=13, start_offset='345.6s', end_offset='345.7s')])
    words = parse_words(NS(steps=[NS(type='model_output', content=[block])]))
    assert words == [Word('No.', 'a', 345.4, 345.5), Word('How', 'b', 344.8, 344.9),
                     Word('can', 'b', 344.9, 345.1), Word('I?', 'a', 345.6, 345.7)]
    stitched, warnings = stitch([words])
    assert render(stitched) == 'Speaker 1: No.\nSpeaker 2: How can\nSpeaker 1: I?'
    assert not warnings


def test_backwards_timestamps_preserve_the_text_for_alignment():
    block = NS(type='text', text='One two three', annotations=[
        NS(type='word_info', speaker='a', start_index=0, end_index=3, start_offset='10s', end_offset='11s'),
        NS(type='word_info', speaker='a', start_index=4, end_index=7, start_offset='12s', end_offset='13s'),
        NS(type='word_info', speaker='a', start_index=8, end_index=13, start_offset='9s', end_offset='10s')])
    words = parse_words(NS(steps=[NS(type='model_output', content=[block])]))
    assert words == [Word('One', 'a', 10, 11), Word('two', 'a', 12, 13), Word('three', 'a', 9, 10)]


def test_reversed_word_retains_text_without_claiming_a_timestamp():
    block = NS(type='text', text='30th, 2026 it', annotations=[
        NS(type='word_info', speaker='a', start_index=0, end_index=5, start_offset='618.8s', end_offset='619.2s'),
        NS(type='word_info', speaker='a', start_index=6, end_index=10, start_offset='619.2s', end_offset='610.4s'),
        NS(type='word_info', speaker='a', start_index=11, end_index=13, start_offset='621.9s', end_offset='622s')])
    words = parse_words(NS(steps=[NS(type='model_output', content=[block])]))
    assert words == [Word('30th,', 'a', 618.8, 619.2), Word('2026', 'a', None, None),
                     Word('it', 'a', 621.9, 622)]


@pytest.mark.parametrize('previous_end,next_start', [('623s', '621.9s'), ('619.2s', 'NaNs'),
                                                     ('619.2s', None)])
def test_invalid_neighbor_times_do_not_discard_the_transcript(previous_end, next_start):
    block = NS(type='text', text='One two three', annotations=[
        NS(type='word_info', speaker='a', start_index=0, end_index=3, start_offset='618s', end_offset=previous_end),
        NS(type='word_info', speaker='a', start_index=4, end_index=7, start_offset='619.2s', end_offset='610.4s'),
        NS(type='word_info', speaker='a', start_index=8, end_index=13, start_offset=next_start, end_offset='624s')])
    words = parse_words(NS(steps=[NS(type='model_output', content=[block])]))
    assert [w.text for w in words] == ['One', 'two', 'three']
    assert words[1].start is None and words[1].end is None


@pytest.mark.parametrize('position', [0, 1])
def test_invalid_edge_word_is_kept_for_text_review(position):
    annotations = [
        NS(type='word_info', speaker='a', start_index=0, end_index=3, start_offset='0s', end_offset='1s'),
        NS(type='word_info', speaker='a', start_index=4, end_index=7, start_offset='2s', end_offset='3s')]
    annotations[position].start_offset = '5s'
    block = NS(type='text', text='One two', annotations=annotations)
    words = parse_words(NS(steps=[NS(type='model_output', content=[block])]))
    assert words[position].start is None
    assert words[position].text == ('One', 'two')[position]


@pytest.mark.parametrize('testing', [False, True])
def test_real_sdk_contract_and_cache(tmp_path, monkeypatch, testing):
    import httpx
    from google import genai
    from app.src.audio_pipeline import AudioPipeline, AUDIO_MODEL, media, save_json
    requests = []
    text = 'Hello there.'
    def transport(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'status': 'completed', 'steps': [
            {'type': 'model_output', 'content': [{'type': 'text', 'text': text, 'annotations': [
                {'type': 'word_info', 'speaker': 's1', 'start_index': 0, 'end_index': 5,
                 'start_offset': '0s', 'end_offset': '0.5s'},
                {'type': 'word_info', 'speaker': 's1', 'start_index': 6, 'end_index': 12,
                 'start_offset': '0.5s', 'end_offset': '1s'}]}]}]})
    files = NS(upload=lambda **kw: NS(name='files/test', uri='uri', state='ACTIVE'))
    wav = tmp_path / 'source.wav'
    wav.write_bytes(b'wav')
    directory = tmp_path/'cache'/AUDIO_MODEL/'overlap-v1'/hashlib.sha256(b'wav').hexdigest()
    save_json(directory/'state.json', {'remote': 'files/old'})
    monkeypatch.setattr(media, 'probe', lambda _: 1)
    monkeypatch.setattr(media, 'prepare', lambda *a: None)
    monkeypatch.setattr('app.src.audio_pipeline.tempfile.gettempdir', lambda: str(tmp_path))
    with genai.Client(api_key='fake', http_options={'client_args': {
            'transport': httpx.MockTransport(transport)}}) as sdk:
        pipeline = AudioPipeline('fake', tmp_path/'cache', NS(files=files, interactions=sdk.interactions),
                                 testing=testing)
        result = pipeline.run(wav)
        assert result.text == 'Speaker 1: Hello there.' and not result.warnings
        assert result.words == (Word('Hello', 'Speaker 1', 0, .5), Word('there.', 'Speaker 1', .5, 1))
        assert result.wav_sha256 == hashlib.sha256(b'wav').hexdigest()
        assert pipeline.run(wav) == result
    dumps = tmp_path/'bababui-transcriptions'
    if testing:
        response, = dumps.glob('response-*.json')
        assert response.with_suffix('.txt').read_text(encoding='utf-8') == text
    else:
        assert not dumps.exists()
    assert (directory/'state.json').read_text(encoding='utf-8') == '{"remote": "files/old"}'
    assert len(requests) == 1
    assert requests[0]['generation_config']['transcription_config']['mode'] == {
        'type': 'verbatim', 'diarization_mode': 'speaker', 'timestamp_granularities': ['word']}


def test_completed_text_without_annotations_is_kept_for_timing_recovery():
    block = NS(type='text', text='Hello there.', annotations=[])
    assert parse_words(NS(steps=[NS(type='model_output', content=[block])])) == [
        Word('Hello', None, None, None), Word('there.', None, None, None)]


@pytest.mark.parametrize('statuses', [(429, 200), (429, 429), (403,)])
@pytest.mark.parametrize('transcript', [('First.', 'Second.'), ('First.', 'Second.', 'Third.')])
def test_later_chunk_rate_limit_waits_then_retries_same_upload(tmp_path, monkeypatch, statuses, transcript):
    import json
    import httpx
    from google import genai
    from app.src.audio_pipeline import AudioPipeline, media

    requests, uploads, waits, progress = [], [], [], []
    prior_chunks = len(transcript) - 1
    remaining = iter((200,) * prior_chunks + statuses)

    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        status = next(remaining)
        if status != 200:
            return httpx.Response(status, json={'error': {'code': status, 'message': 'Request failed'}})
        text = transcript[len(uploads) - 1]
        return httpx.Response(200, json={'status': 'completed', 'steps': [
            {'type': 'model_output', 'content': [{'type': 'text', 'text': text, 'annotations': [
                {'type': 'word_info', 'speaker': 's1', 'start_index': 0, 'end_index': len(text),
                 'start_offset': '40s', 'end_offset': '41s'}]}]}]})

    def upload(**kwargs):
        uploads.append(kwargs['file'])
        return NS(uri=f'files/chunk-{len(uploads)}', state='ACTIVE')

    wav = tmp_path / 'source.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: 3540 if len(transcript) == 2 else 5280)
    monkeypatch.setattr(media, 'prepare', lambda *args: None)
    monkeypatch.setattr('app.src.audio_pipeline.time.sleep', waits.append)
    # Isolate the app's fallback from the SDK's short built-in retries.
    with genai.Client(api_key='fake', http_options={'retry_options': {
            'attempts': 1, 'http_status_codes': [503]},
            'client_args': {'transport': httpx.MockTransport(transport)}}) as sdk:
        pipeline = AudioPipeline('fake', tmp_path / 'cache',
                                 NS(files=NS(upload=upload), interactions=sdk.interactions))
        if statuses[-1] == 200:
            result = pipeline.run(wav, progress.append)
            assert result.text.splitlines() == [f'Speaker {i}: {word}' for i, word in enumerate(transcript, 1)]
            assert pipeline.run(wav) == result
        else:
            with pytest.raises(Exception) as caught:
                pipeline.run(wav, progress.append)
            assert getattr(caught.value, 'status_code', getattr(caught.value, 'code', None)) == statuses[-1]
        assert len(list(pipeline.cache.rglob('chunk-*.json'))) == prior_chunks + (statuses[-1] == 200)

    assert len(uploads) == len(transcript)
    assert len(requests) == prior_chunks + len(statuses)
    assert waits == ([60] if statuses[0] == 429 else [])
    if statuses[0] == 429:
        assert requests[-2] == requests[-1]
        assert any('60 seconds' in message and '429' in message for message in progress)


def test_incomplete_chunk_retries_without_timestamps_then_next_chunk_uses_them(tmp_path, monkeypatch):
    from app.src.audio_pipeline import AudioPipeline, media

    overlap = 'Please read the signed agreement to the witness again.'
    untimed = f'We started today. {overlap}'
    requests, uploads, prepared = [], [], []

    def upload(**kwargs):
        uploads.append(prepared[-1])
        return NS(uri=f'files/chunk-{len(uploads)}', state='ACTIVE')

    def create(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            return NS(status='incomplete')
        if len(requests) == 2:
            text = untimed
            annotations = [NS(type='word_info', start_index=0, end_index=len(text), speaker='first')]
        else:
            clip = uploads[-1]
            if clip['start'] == 1740:
                text = f'{overlap} We can adjourn.'
                times = [i + 27 if i < len(overlap.split()) else i + 62 for i in range(len(text.split()))]
            elif clip['start'] == 1500:
                text = overlap
                times = range(267, 267 + len(text.split()))
            elif clip['start'] == 0:
                text, times = 'We started today.', (1, 2, 3)
            else:
                text, times = 'Other testimony.', (10, 11)
            annotations, offset = [], 0
            for token, start in zip(text.split(), times):
                annotations.append(NS(type='word_info', start_index=offset, end_index=offset+len(token),
                                      speaker='second', start_offset=f'{start}s', end_offset=f'{start+0.5}s'))
                offset += len(token) + 1
        block = NS(type='text', text=text, annotations=annotations)
        return NS(status='completed', steps=[NS(type='model_output', content=[block])])

    wav = tmp_path/'source.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: 2942)
    monkeypatch.setattr(media, 'prepare', lambda path, clip, destination: prepared.append(clip))
    sdk = NS(files=NS(upload=upload), interactions=NS(create=create))
    pipeline = AudioPipeline('fake', tmp_path/'cache', sdk)

    result = pipeline.run(wav)

    assert result.text == f'Speaker 1: {untimed} We can adjourn.'
    assert result.words[0].start == 1
    assert next(w.start for w in result.words if w.text == 'Please') == 1767
    assert not result.warnings
    assert pipeline.run(wav) == result
    assert [clip['start'] for clip in uploads] == [0, 0, 300, 600, 900, 1200, 1500, 1740]
    assert requests[0]['input'] == requests[1]['input']
    configs = [request['generation_config'] for request in requests]
    assert all(config['max_output_tokens'] == 16384 for config in configs)
    modes = [config['transcription_config']['mode'] for config in configs]
    assert [mode.get('timestamp_granularities') for mode in modes] == [['word'], None] + [['word']] * 7
    assert all(mode['diarization_mode'] == 'speaker' for mode in modes)


def test_unmatched_untimed_overlap_keeps_text_from_both_chunks():
    a = [Word('Keep the first chunk.', 'a', 1742, 1745)]
    b = [Word('Keep the second chunk.', 'b', None, None)]
    words, warnings = stitch([a, b])
    assert render(words) == 'Speaker 1: Keep the first chunk.\nSpeaker 2: Keep the second chunk.'
    assert any('Both chunks' in warning for warning in warnings)


@pytest.mark.parametrize('whole_turns', [False, True], ids=['words', 'speaker-turns'])
def test_recovers_word_times_from_short_clips_for_a_cached_untimed_chunk(tmp_path, monkeypatch, whole_turns):
    from dataclasses import asdict
    from app.src.audio_pipeline import AUDIO_MODEL, AudioPipeline, media, save_json

    wav = tmp_path / 'old.wav'
    wav.write_bytes(b'recording')
    cache = tmp_path / 'cache'
    digest = hashlib.sha256(wav.read_bytes()).hexdigest()
    directory = cache / AUDIO_MODEL / 'overlap-v1' / digest
    original = [Word(word, speaker, None, None)
                for speaker, passage in [('a', 'Bring the papers.'), ('b', 'Yes, I will.')]
                for word in ([passage] if whole_turns else passage.split())]
    save_json(directory / 'chunk-0.json', [asdict(w) for w in original])
    clips = []
    monkeypatch.setattr(media, 'probe', lambda _: 360)
    monkeypatch.setattr(media, 'prepare', lambda path, segment, dest: clips.append(segment))
    pipeline = AudioPipeline('fake', cache)

    def transcribe(path, progress, *, timing_only):
        assert timing_only
        passage = 'bring the papers' if clips[-1]['start'] == 0 else 'yes I will'
        return [Word(word, 'different label', i + 2, i + 2.5) for i, word in enumerate(passage.split())]

    monkeypatch.setattr(pipeline, 'transcribe_segment', transcribe)
    result = pipeline.run(wav)

    assert result.text == 'Speaker 1: Bring the papers.\nSpeaker 2: Yes, I will.'
    assert [w.start for w in result.words] == [2, 3, 4, 182, 183, 184]
    assert not result.warnings
    assert pipeline.run(wav) == result
    assert clips == [{'start': 0, 'end': 180}, {'start': 180, 'end': 360}]


def test_ambiguous_speakers_are_not_merged():
    a = [Word(str(i), 'a' if i < 6 else 'b', 1750+i, 1751+i) for i in range(12)]
    b = [Word(str(i), 'c', 10+i, 11+i) for i in range(12)]
    stitched, warnings = stitch([a, b])
    text = render(stitched)
    assert 'Speaker 3:' in text and warnings


def test_concurrent_cache_use_is_rejected(tmp_path, monkeypatch):
    from shared.storage import file_lock
    from app.src.audio_pipeline import AudioPipeline, AUDIO_MODEL, media
    wav = tmp_path/'input.wav'
    wav.write_bytes(b'wav')
    directory = tmp_path/'cache'/AUDIO_MODEL/'overlap-v1'/hashlib.sha256(b'wav').hexdigest()
    monkeypatch.setattr(media, 'probe', lambda _: 1)
    with file_lock(directory/'cache.lock'):
        with pytest.raises(ValueError, match='another session'):
            AudioPipeline('fake', tmp_path/'cache').run(wav)


def test_partial_run_reuses_first_chunk(tmp_path, monkeypatch):
    from app.src.audio_pipeline import AudioPipeline, media
    wav = tmp_path/'input.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: 3540)
    prepared = []
    monkeypatch.setattr(media, 'prepare', lambda source, segment, dest: prepared.append(segment))
    pipeline = AudioPipeline('fake', tmp_path/'cache')
    attempts = []
    def transcribe(path, progress=lambda message: None):
        attempts.append(path)
        if len(attempts) == 2:
            raise ValueError('temporary failure')
        return [Word('Hello', 'a', 40, 41)]
    monkeypatch.setattr(pipeline, 'transcribe_segment', transcribe)
    with pytest.raises(ValueError, match='temporary failure'):
        pipeline.run(wav)
    result = pipeline.run(wav)
    assert result.text and result.warnings and len(attempts) == 3
    assert [word.start for word in result.words] == [40, 1780]
    assert prepared == [{'start': 0, 'end': 1800}, {'start': 1740, 'end': 3540},
                        {'start': 1740, 'end': 3540}]


def test_two_speakers_swap_labels_without_changing_identity():
    words = 'one two three four five six seven eight nine ten eleven twelve'.split()
    a = [Word(w, 'a' if i < 6 else 'b', 1750+i, 1751+i) for i,w in enumerate(words)]
    b = [Word(w, 'y' if i < 6 else 'x', 10+i, 11+i) for i,w in enumerate(words)]
    b += [Word('First.', 'y', 65, 66), Word('Second.', 'x', 67, 68)]
    stitched, warnings = stitch([a, b])
    text = render(stitched)
    assert not warnings
    assert 'Speaker 1: First.' in text and 'Speaker 2: Second.' in text


def test_bad_annotation_times_can_be_ignored_without_losing_words():
    block = NS(type='text', text='We can start now.', annotations=[
        NS(type='word_info', speaker='a', start_index=0, end_index=2, start_offset='1s', end_offset='1.1s'),
        NS(type='word_info', speaker='a', start_index=3, end_index=6, start_offset='2s', end_offset='1.5s'),
        NS(type='word_info', speaker='a', start_index=7, end_index=12, start_offset='3s', end_offset='3.1s'),
        NS(type='word_info', speaker='b', start_index=13, end_index=17, start_offset='NaNs', end_offset='5s')])
    result = parse_words(NS(steps=[NS(type='model_output', content=[block])]))
    assert result == [Word('We', 'a', 1, 1.1), Word('can', 'a', None, None),
                      Word('start', 'a', 3, 3.1), Word('now.', 'b', None, None)]


def test_replaced_wav_cannot_populate_the_old_recording_cache(tmp_path, monkeypatch):
    from app.src.audio_pipeline import AudioPipeline, media

    wav = tmp_path / 'source.wav'
    wav.write_bytes(b'first')
    monkeypatch.setattr(media, 'probe', lambda _: 1)
    monkeypatch.setattr(media, 'prepare', lambda *args: None)
    pipeline = AudioPipeline('fake', tmp_path / 'cache')

    def transcribe(path, progress=lambda message: None):
        wav.write_bytes(b'different audio')
        return [Word('Word', 'a', 0, .1)]

    monkeypatch.setattr(pipeline, 'transcribe_segment', transcribe)
    with pytest.raises(ValueError, match='WAV changed'):
        pipeline.run(wav)
    assert not list(pipeline.cache.rglob('chunk-*.json'))


def _steady(first, last, speaker='s1'):
    """Steady speech: one word every two seconds."""
    return [Word(f'w{t}', speaker, t, t + 1) for t in range(first, last, 2)]


def test_when_a_chunk_stops_before_the_overlap_the_next_chunk_is_kept_from_there():
    # 261109ponton: chunk 1 stopped at 28:04, and one early word claimed an end time
    # of 30:00. The midpoint cut at 29:30 dropped chunk 2's first 30 seconds.
    a = [Word('early', 's1', 407.9, 1800.0)] + _steady(1384, 1684) + [Word('Uh', 's2', 1684.8, 1684.8)]
    said = 'You said that he required neurosurgery to relieve pressure. Right. No, I don\'t.'.split()
    b = [Word(word, 'b1', 2.5 + i, 3 + i) for i, word in enumerate(said)]
    stitched, warnings = stitch([a, b])
    text = render(stitched)
    assert text.endswith('Speaker 3: ' + ' '.join(said))
    assert 'Uncertain overlap alignment: joined at 28:04. Review for missing or repeated words.' in warnings
    assert ('No words were transcribed between 28:04 and 29:00. Check the audio there for missing testimony.'
            in warnings)


def test_a_chunk_that_stops_early_is_transcribed_again_and_joined_once(tmp_path, monkeypatch):
    from app.src.audio_pipeline import AudioPipeline, media
    wav = tmp_path / 'input.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: 3540)
    prepared = []
    monkeypatch.setattr(media, 'prepare', lambda source, segment, dest: prepared.append(dict(segment)))
    missing = "I don't have that information.".split()
    answer = 'He said that he required neurosurgery.'.split()

    def transcribe(path, progress=lambda message: None):
        start = prepared[-1]['start']
        if start == 0:  # Gemini stops at 28:04 of a 30-minute chunk.
            return _steady(1384, 1684) + [Word('Uh', 's2', 1684.8, 1684.8)]
        if start == 1624:  # The rest of chunk 1, from a minute before its last word.
            return ([Word(w.text, 'x1', w.start - 1624, w.end - 1624) for w in _steady(1624, 1684)]
                    + [Word('Uh', 'x3', 60.8, 60.8)]
                    + [Word(word, 'x2', 70 + i, 70.5 + i) for i, word in enumerate(missing)]
                    + [Word(word, 'x2', 160 + i, 160.5 + i) for i, word in enumerate(answer)])
        return ([Word(word, 'b2', 44 + i, 44.5 + i) for i, word in enumerate(answer)]
                + [Word(word, 'b1', 90 + i, 90.5 + i) for i, word in enumerate("No, I don't.".split())])
    pipeline = AudioPipeline('fake', tmp_path / 'cache')
    monkeypatch.setattr(pipeline, 'transcribe_segment', transcribe)
    progress = []
    result = pipeline.run(wav, progress.append)
    assert prepared == [{'start': 0, 'end': 1800}, {'start': 1624, 'end': 1800}, {'start': 1740, 'end': 3540}]
    assert result.text.count("I don't have that information.") == 1
    assert result.text.count('He said that he required neurosurgery.') == 1
    assert result.text.index('Uh') < result.text.index("I don't have") < result.text.index('He said')
    assert any(w.startswith('Chunk 1 of the transcription stopped at 28:04, 1:55 before its end.')
               for w in result.warnings)
    assert 'Chunk 1 of the transcription stopped at 28:04. Transcribing the rest of that chunk...' in progress
    # The rest is cached with the chunk, so a second run asks for nothing new.
    assert pipeline.run(wav) == result and len(prepared) == 3


def test_a_pause_before_the_chunk_end_is_not_transcribed_again(tmp_path, monkeypatch):
    from app.src.audio_pipeline import AudioPipeline, media
    wav = tmp_path / 'input.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: 3540)
    prepared = []
    monkeypatch.setattr(media, 'prepare', lambda source, segment, dest: prepared.append(dict(segment)))
    pipeline = AudioPipeline('fake', tmp_path / 'cache')
    # A few words, then a long pause: speech had stopped, not the transcript.
    monkeypatch.setattr(pipeline, 'transcribe_segment',
                        lambda path, progress=None: [Word('Off', 's1', 1200, 1201), Word('record.', 's1', 1201, 1202)])
    pipeline.run(wav)
    assert prepared == [{'start': 0, 'end': 1800}, {'start': 1740, 'end': 3540}]


def test_when_the_rest_cannot_be_transcribed_the_gap_is_reported(tmp_path, monkeypatch):
    from app.src.audio_pipeline import AudioPipeline, media
    wav = tmp_path / 'input.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: 3540)
    prepared = []
    monkeypatch.setattr(media, 'prepare', lambda source, segment, dest: prepared.append(dict(segment)))

    def transcribe(path, progress=lambda message: None):
        if prepared[-1]['start'] == 1624:
            raise ValueError('temporary failure')
        return _steady(1384, 1684) + [Word('Uh', 's2', 1684.8, 1684.8)]
    pipeline = AudioPipeline('fake', tmp_path / 'cache')
    monkeypatch.setattr(pipeline, 'transcribe_segment', transcribe)
    result = pipeline.run(wav)
    assert ('Chunk 1 of the transcription stopped at 28:04, 1:55 before its end, and the rest could not be '
            'transcribed. Words may be missing between 28:04 and 30:00.') in result.warnings


def _one_chunk(tmp_path, monkeypatch, transcribe, length=1500):
    from app.src.audio_pipeline import AudioPipeline, media
    wav = tmp_path / 'input.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: length)
    prepared = []
    monkeypatch.setattr(media, 'prepare', lambda source, segment, dest: prepared.append(dict(segment)))
    pipeline = AudioPipeline('fake', tmp_path / 'cache')
    monkeypatch.setattr(pipeline, 'transcribe_segment',
                        lambda path, progress=None: transcribe(prepared[-1]['start']))
    return pipeline, wav, prepared


def test_the_last_chunk_that_stops_early_is_transcribed_again(tmp_path, monkeypatch):
    missing = 'And that was the last visit.'.split()

    def transcribe(start):
        if start == 0:  # A one-chunk recording whose transcript stops at 16:38 of 25:00.
            return _steady(0, 1000)
        assert start == 938
        return ([Word(w.text, 'x1', w.start - 938, w.end - 938) for w in _steady(938, 1000)]
                + [Word(word, 'x1', 70 + i, 70.5 + i) for i, word in enumerate(missing)])
    pipeline, wav, prepared = _one_chunk(tmp_path, monkeypatch, transcribe)
    progress = []
    result = pipeline.run(wav, progress.append)
    assert prepared == [{'start': 0, 'end': 1500}, {'start': 938, 'end': 1500}]
    assert result.text.count('w998') == 1
    assert result.text.endswith('w998 ' + ' '.join(missing))
    assert any(w.startswith('Chunk 1 of the transcription stopped at 16:38, 8:22 before its end.')
               for w in result.warnings)
    assert 'Chunk 1 of the transcription stopped at 16:38. Transcribing the rest of that chunk...' in progress
    assert pipeline.run(wav) == result and len(prepared) == 2


def test_a_gap_in_the_middle_of_a_chunk_is_transcribed_again_and_joined_once(tmp_path, monkeypatch):
    missing = 'I saw him at the clinic twice.'.split()

    def transcribe(start):
        if start == 0:  # Gemini skips from 9:58 to 11:40, then carries on.
            return _steady(0, 600) + _steady(700, 1500)
        assert start == 538  # A minute before the gap to a minute after it.
        return ([Word(w.text, 'x1', w.start - 538, w.end - 538) for w in _steady(538, 600)]
                + [Word(word, 'x1', 70 + i, 70.5 + i) for i, word in enumerate(missing)]
                + [Word(w.text, 'x1', w.start - 538, w.end - 538) for w in _steady(700, 760)])
    pipeline, wav, prepared = _one_chunk(tmp_path, monkeypatch, transcribe)
    progress = []
    result = pipeline.run(wav, progress.append)
    assert prepared == [{'start': 0, 'end': 1500}, {'start': 538, 'end': 760}]
    text = result.text
    assert text.count(' '.join(missing)) == 1 and text.count('w598 ') == 1 and text.count('w700 ') == 1
    assert text.index('w598 ') < text.index(' '.join(missing)) < text.index('w700 ') < text.index('w1498')
    assert ('Chunk 1 of the transcription skipped from 9:58 to 11:40. That part was transcribed again; '
            'review it.') in result.warnings
    assert 'Chunk 1 of the transcription skipped from 9:58 to 11:40. Transcribing that part again...' in progress


def test_a_gap_after_going_off_the_record_is_not_transcribed_again(tmp_path, monkeypatch):
    said = "Let's go off the record for a few minutes.".split()
    words = (_steady(0, 600) + [Word(word, 's1', 600 + i, 600.5 + i) for i, word in enumerate(said)]
             + _steady(900, 1500))
    pipeline, wav, prepared = _one_chunk(tmp_path, monkeypatch, lambda start: words)
    result = pipeline.run(wav)
    assert prepared == [{'start': 0, 'end': 1500}]
    assert not any('skipped' in w for w in result.warnings)


def test_a_gap_where_nothing_more_was_said_keeps_the_chunk_as_it_was(tmp_path, monkeypatch):
    def transcribe(start):
        if start == 0:
            return _steady(0, 600) + _steady(700, 1500)
        return [Word(w.text, 'x1', w.start - 538, w.end - 538) for w in _steady(538, 600) + _steady(700, 760)]
    pipeline, wav, prepared = _one_chunk(tmp_path, monkeypatch, transcribe)
    result = pipeline.run(wav)
    assert len(prepared) == 2 and not any('skipped' in w for w in result.warnings)
    assert result.text.count('w598 ') == 1 and result.text.count('w700 ') == 1
