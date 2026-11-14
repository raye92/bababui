import hashlib
from types import SimpleNamespace as NS

import pytest

from app.src.audio_pipeline import Word, segments, stitch, parse_words, render


def test_duration_and_chunks():
    assert segments(1800) == [(0, 1800)]
    assert segments(3540) == [(0, 1800), (1740, 3540)]
    for duration in (0, -1, 3540.1, float('nan')):
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


def test_annotation_bytes_preserve_unicode():
    block = NS(type='text', text='Café? Yes.', annotations=[
        NS(type='word_info', speaker='a', start_index=0, end_index=6, start_offset='0s', end_offset='1s'),
        NS(type='word_info', speaker='b', start_index=7, end_index=11, start_offset='1s', end_offset='2s')])
    response = NS(steps=[NS(type='model_output', content=[block])])
    words = parse_words(response)
    assert [w.text for w in words] == ['Café?', 'Yes.']


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


def test_missing_annotations_and_bad_timestamps_are_rejected():
    with pytest.raises(ValueError, match='timestamps'):
        parse_words(NS(steps=[NS(type='model_output', content=[NS(type='text', text='Hello', annotations=[])])]))


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
    def transcribe(path):
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

    def transcribe(path):
        wav.write_bytes(b'different audio')
        return [Word('Word', 'a', 0, .1)]

    monkeypatch.setattr(pipeline, 'transcribe_segment', transcribe)
    with pytest.raises(ValueError, match='WAV changed'):
        pipeline.run(wav)
    assert not list(pipeline.cache.rglob('chunk-*.json'))
