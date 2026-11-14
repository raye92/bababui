from types import SimpleNamespace as NS

import pytest

from app.src.audio_pipeline import Word, segments, stitch, parse_words


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
    text, warnings = stitch([a, b])
    assert text.count('Before.') == text.count('After.') == 1
    assert 'Speaker 1:' in text and 'Speaker 2: New.' in text
    assert len(text.split()) < 24
    assert any('unmatched' in warning.lower() for warning in warnings)


def test_unaligned_overlap_uses_timestamp_cut():
    a = [Word('Keep.', 'a', 1760, 1761), Word('Drop.', 'a', 1780, 1781)]
    b = [Word('DropB.', 'b', 10, 11), Word('KeepB.', 'b', 40, 41)]
    text, warnings = stitch([a, b])
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
    assert stitch([words]) == ('Speaker 1: No.\nSpeaker 2: How can\nSpeaker 1: I?', [])


@pytest.mark.parametrize('speakers', [('a', 'a', 'a'), ('a', 'b', 'a')])
def test_backwards_timestamps_for_same_speaker_are_rejected(speakers):
    block = NS(type='text', text='One two three', annotations=[
        NS(type='word_info', speaker=speakers[0], start_index=0, end_index=3, start_offset='10s', end_offset='11s'),
        NS(type='word_info', speaker=speakers[1], start_index=4, end_index=7, start_offset='12s', end_offset='13s'),
        NS(type='word_info', speaker=speakers[2], start_index=8, end_index=13, start_offset='9s', end_offset='10s')])
    with pytest.raises(ValueError, match='timestamps are out of order'):
        parse_words(NS(steps=[NS(type='model_output', content=[block])]))


def test_real_sdk_contract_cleanup_and_cache(tmp_path, monkeypatch):
    import httpx
    from google import genai
    from app.src.audio_pipeline import AudioPipeline, media
    requests, deleted = [], []
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
    files = NS(upload=lambda **kw: NS(name='files/test', uri='uri', state='ACTIVE'),
               delete=lambda **kw: deleted.append(kw['name']))
    wav = tmp_path / 'source.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: 1)
    monkeypatch.setattr(media, 'prepare', lambda *a: None)
    with genai.Client(api_key='fake', http_options={'client_args': {
            'transport': httpx.MockTransport(transport)}}) as sdk:
        pipeline = AudioPipeline('fake', tmp_path/'cache', NS(files=files, interactions=sdk.interactions))
        result, warnings = pipeline.run(wav)
        assert result == 'Speaker 1: Hello there.' and not warnings
        assert pipeline.run(wav) == (result, [])
    assert len(requests) == 1 and deleted == ['files/test']
    assert requests[0]['generation_config']['transcription_config']['mode'] == {
        'type': 'verbatim', 'diarization_mode': 'speaker', 'timestamp_granularities': ['word']}


def test_transcription_failure_still_cleans_remote(tmp_path):
    from app.src.audio_pipeline import AudioPipeline
    deleted = []
    files = NS(upload=lambda **kw: NS(name='files/test', uri='uri', state='ACTIVE'),
               delete=lambda **kw: deleted.append(kw['name']))
    sdk = NS(files=files, interactions=NS(create=lambda **kw: NS(status='incomplete')))
    with pytest.raises(ValueError, match='complete'):
        AudioPipeline('fake', tmp_path, sdk).transcribe_segment(tmp_path/'x.wav', tmp_path/'state.json', [])
    assert deleted == ['files/test']


def test_missing_annotations_and_bad_timestamps_are_rejected():
    with pytest.raises(ValueError, match='timestamps'):
        parse_words(NS(steps=[NS(type='model_output', content=[NS(type='text', text='Hello', annotations=[])])]))


def test_ambiguous_speakers_are_not_merged():
    a = [Word(str(i), 'a' if i < 6 else 'b', 1750+i, 1751+i) for i in range(12)]
    b = [Word(str(i), 'c', 10+i, 11+i) for i in range(12)]
    text, warnings = stitch([a, b])
    assert 'Speaker 3:' in text and warnings


def test_cached_text_survives_pending_cleanup_failure(tmp_path, monkeypatch):
    import hashlib
    from dataclasses import asdict
    from app.src.audio_pipeline import AudioPipeline, AUDIO_MODEL, media, save_json
    wav = tmp_path/'input.wav'
    wav.write_bytes(b'wav')
    directory = tmp_path/'cache'/AUDIO_MODEL/'overlap-v1'/hashlib.sha256(b'wav').hexdigest()
    save_json(directory/'chunk-0.json', [asdict(Word('Hello', 'a', 0, 1))])
    save_json(directory/'state.json', {'remote': 'files/pending'})
    monkeypatch.setattr(media, 'probe', lambda _: 1)
    pipeline = AudioPipeline('fake', tmp_path/'cache')
    def fail(name):
        raise ValueError('cleanup unavailable')
    monkeypatch.setattr(pipeline.client, 'delete', fail)
    text, warnings = pipeline.run(wav)
    assert text == 'Speaker 1: Hello' and warnings


def test_concurrent_cache_use_is_rejected(tmp_path, monkeypatch):
    import hashlib
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
    def transcribe(path, state, warnings):
        attempts.append(path)
        if len(attempts) == 2:
            raise ValueError('temporary failure')
        return [Word('Hello', 'a', 40, 41)]
    monkeypatch.setattr(pipeline, 'transcribe_segment', transcribe)
    with pytest.raises(ValueError, match='temporary failure'):
        pipeline.run(wav)
    text, warnings = pipeline.run(wav)
    assert text and warnings and len(attempts) == 3
    assert prepared == [{'start': 0, 'end': 1800}, {'start': 1740, 'end': 3540},
                        {'start': 1740, 'end': 3540}]


def test_two_speakers_swap_labels_without_changing_identity():
    words = 'one two three four five six seven eight nine ten eleven twelve'.split()
    a = [Word(w, 'a' if i < 6 else 'b', 1750+i, 1751+i) for i,w in enumerate(words)]
    b = [Word(w, 'y' if i < 6 else 'x', 10+i, 11+i) for i,w in enumerate(words)]
    b += [Word('First.', 'y', 65, 66), Word('Second.', 'x', 67, 68)]
    text, warnings = stitch([a,b])
    assert not warnings
    assert 'Speaker 1: First.' in text and 'Speaker 2: Second.' in text
