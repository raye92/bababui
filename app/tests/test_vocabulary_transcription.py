import json
from contextlib import ExitStack
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

import httpx
from google import genai
from PySide6.QtCore import Qt

from app.src.audio_pipeline import AUDIO_MODEL, AudioPipeline, Word, media, render
from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator


def timed(text, start=0, speaker='s'):
    return tuple(Word(token, speaker, start + i, start + i + .5) for i, token in enumerate(text.split()))


def test_merge_copies_only_supported_spellings_and_keeps_speakers_times_and_punctuation():
    from app.src.vocabulary_reconciliation import reconcile_vocabulary

    base = timed('We called Shon Smyth, yesterday.', speaker='A') + timed('He said yes.', 12, 'B')
    result = reconcile_vocabulary(base, [(0, 30)] * len(base),
        [(0, 30, 'We phoned Sean Smythe yesterday. He actually said absolutely yes.')],
        ('Sean Smythe', 'Rogers LLP'))

    assert render(result) == 'A: We called Sean Smythe, yesterday.\nB: He said yes.'
    assert [(w.speaker, w.start, w.end) for w in result] == [(w.speaker, w.start, w.end) for w in base]


def test_merge_uses_local_recording_interval_and_applies_overlap_name_once():
    from app.src.vocabulary_reconciliation import reconcile_vocabulary

    base = (timed('We asked Smyth again.', 10) + timed('We asked Smyth again.', 3550)
            + timed('We asked Smyth again.', 4500))
    result = reconcile_vocabulary(base, [(0, 5000)] * len(base),
        [(0, 3600, 'We asked Smyth again. We asked Smythe again.'),
         (3540, 5000, 'We asked Smythe again. We asked Smyth again.')], ('Smythe',))

    assert render(result) == 's: We asked Smyth again. We asked Smythe again. We asked Smyth again.'
    assert result[6] == Word('Smythe', 's', 3552, 3552.5)


def test_merge_treats_cross_speaker_and_unrelated_replacements_as_unsupported():
    from app.src.vocabulary_reconciliation import reconcile_vocabulary

    base = timed('We called Jon', speaker='A') + timed('Smyth today.', 10, 'B') + timed('They hired plumbers.', 20, 'B')
    result = reconcile_vocabulary(base, [(0, 40)] * len(base),
        [(0, 40, 'We called John Smythe today. They hired Roberts.')], ('John Smythe', 'Roberts'))
    assert result == base


def test_firm_retokenization_uses_measured_extent_and_spoken_surname_uses_context():
    from app.src.vocabulary_reconciliation import reconcile_vocabulary

    base = timed('We retained Mac Laren and Company. Then Ms. Brien spoke.')
    result = reconcile_vocabulary(base, [(0, 30)] * len(base),
        [(0, 30, 'We retained McLaren & Company. Then Ms. Brienn spoke.')],
        ('McLaren & Company', 'Grace Brienn'))
    assert render(result) == 's: We retained McLaren & Company. Then Ms. Brienn spoke.'
    assert result[2].start == 2 and result[2].end == 3.5
    assert result[-2] == Word('Brienn', 's', 8, 8.5)


def test_shorter_vocabulary_transcript_cannot_resolve_a_repeated_phrase():
    from app.src.vocabulary_reconciliation import reconcile_vocabulary

    base = timed('We asked Smyth again.', 2, 'A') + timed('We asked Smyth again.', 12, 'B')
    result = reconcile_vocabulary(base, [(0, 20)] * len(base),
                                  [(0, 20, 'We asked Smythe again.')], ('Smythe',))
    assert result == base


def test_vocabulary_windows_that_support_different_confirmed_names_leave_the_base_spelling():
    from app.src.vocabulary_reconciliation import reconcile_vocabulary

    base = timed('We heard Smyth testify.', 3560)
    result = reconcile_vocabulary(base, [(0, 7020)] * len(base),
        [(0, 3600, 'We heard Smythe testify.'), (3540, 7020, 'We heard Smyth testify.')], ('Smyth', 'Smythe'))
    assert result == base


def test_confirmed_capitalized_caption_can_recover_normal_transcript_case_and_possessive():
    from app.src.vocabulary_reconciliation import reconcile_vocabulary

    base = timed("That is Maclaud's signature.")
    result = reconcile_vocabulary(base, [(0, 30)] * len(base), [(0, 30, "That is McLeod's signature.")],
                                  ('ANN MCLEOD',))
    assert render(result) == "s: That is McLeod's signature."


def test_retokenizing_a_name_cannot_swallow_an_initial_or_drop_a_known_time():
    from app.src.vocabulary_reconciliation import reconcile_vocabulary

    base = timed('We called J Smyth yesterday. Then Mac') + (Word('Laren', 's', None, None),) + timed('spoke.', 12)
    result = reconcile_vocabulary(base, [(0, 30)] * len(base),
        [(0, 30, 'We called Smythe yesterday. Then McLaren spoke.')], ('Smythe', 'McLaren'))
    assert result == base


def test_long_recording_reuses_base_and_successful_vocabulary_after_optional_failure(tmp_path, monkeypatch):
    wav = tmp_path / 'job.wav'
    wav.write_bytes(b'recording')
    monkeypatch.setattr(media, 'probe', lambda _: 7020)
    monkeypatch.setattr(media, 'prepare', lambda path, clip, dest: dest.write_text(str(clip['start'])))
    waits, uploads, calls = [], [], []
    monkeypatch.setattr('app.src.audio_pipeline.time.sleep', waits.append)
    retry = False
    passages = {0: 'Opening statements.', 1740: 'Read this back.', 3480: 'We called Smyth yesterday.',
                5220: 'Smyth answered the question.'}

    def upload(file, config):
        from pathlib import Path
        start = int(Path(file).read_text())
        uri = f'files/{start}/{len(uploads)}'
        uploads.append(uri)
        return NS(uri=uri, state='ACTIVE')

    def transport(request):
        payload = json.loads(request.content)
        config = payload['generation_config']['transcription_config']
        uri = payload['input'][0]['content'][0]['uri']
        start = int(uri.split('/')[1])
        calls.append((uri, config))
        names = config.get('custom_vocabulary')
        if names:
            assert config == {'mode': {'type': 'verbatim'}, 'custom_vocabulary': names}
            if start == 3540 and not retry:
                return httpx.Response(429, json={'error': {'code': 429, 'message': 'rate limit'}})
            text = ('Opening statements. Read this back. We called NAME yesterday.' if start == 0
                    else 'We called NAME yesterday. NAME answered the question.').replace('NAME', names[0])
            annotations = []
        else:
            assert config['mode'] == {'type': 'verbatim', 'diarization_mode': 'speaker',
                                      'timestamp_granularities': ['word']}
            text, annotations, pos = passages[start], [], 0
            for i, word in enumerate(text.split()):
                annotations.append({'type': 'word_info', 'start_index': pos, 'end_index': pos + len(word),
                                    'speaker': 'a', 'start_offset': f'{90+i}s', 'end_offset': f'{91+i}s'})
                pos += len(word) + 1
        return httpx.Response(200, json={'status': 'completed', 'steps': [
            {'type': 'model_output', 'content': [{'type': 'text', 'text': text, 'annotations': annotations}]}]})

    with ExitStack() as clients:
        sdk_client = genai.Client

        def client(api_key, http_options):
            options = {**http_options, 'client_args': {'transport': httpx.MockTransport(transport)}}
            sdk = clients.enter_context(sdk_client(api_key=api_key, http_options=options))
            return NS(files=NS(upload=upload), interactions=sdk.interactions)

        monkeypatch.setattr(genai, 'Client', client)
        pipeline = AudioPipeline('fake', tmp_path / 'cache')
        messages = []
        partial = pipeline.run(wav, messages.append, vocabulary=('Smythe',))
        assert 'We called Smythe yesterday.' in partial.text and 'Smyth answered' in partial.text
        assert any('vocabulary' in msg.lower() and '2' in msg for msg in partial.warnings)
        assert len(uploads) == 6 and len(calls) == 7
        assert calls[-2] == calls[-1] and waits == [60]
        assert any('4 of 4' in msg for msg in messages) and any('2 of 2' in msg for msg in messages)
        retry = True
        complete = pipeline.run(wav, vocabulary=('Smythe',))
        assert 'Smythe answered' in complete.text and not any('vocabulary' in msg.lower() for msg in complete.warnings)
        assert len(uploads) == 7
        assert pipeline.run(wav, vocabulary=('Smythe',)) == complete and len(uploads) == 7
        different = pipeline.run(wav, vocabulary=('Smith',))
        assert 'We called Smith yesterday.' in different.text and 'Smith answered' in different.text
        assert len(uploads) == 9
        plain = pipeline.run(wav)
        assert 'We called Smyth yesterday.' in plain.text and len(uploads) == 9
        assert pipeline.run(wav, vocabulary=(' ', '-')) == plain and len(uploads) == 9


def test_two_tabs_with_different_names_share_base_calls_and_format_their_own_raw_text(tmp_path, monkeypatch):
    wav = tmp_path / 'sample.wav'
    wav.write_bytes(b'same source')
    monkeypatch.setattr(media, 'probe', lambda _: 30)
    monkeypatch.setattr(media, 'prepare', lambda *args: None)
    entered, release, waiting = Event(), Event(), Event()
    calls, formatted, errors = [], [], []

    class Pipeline(AudioPipeline):
        def __init__(self, *args, **kwargs):
            super().__init__('fake', tmp_path / 'cache')

        def transcribe_segment(self, path, progress, *, vocabulary=()):
            calls.append(vocabulary)
            if not vocabulary:
                entered.set()
                assert release.wait(5)
                return timed('They called Smyth yesterday.')
            return timed(f'They called {vocabulary[0]} yesterday.')

    class Processor:
        def __init__(self, config, model):
            self.model = model

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            formatted.append((self.model, text))
            return text

    coordinator = TranscriptionCoordinator()
    workers = [ProcessingWorker(Request(name, str(wav), name, AUDIO_MODEL, 'Format the transcript.', {},
                                        vocabulary=(name,)), coordinator, Pipeline, Processor)
               for name in ('Smythe', 'Smith')]
    for worker in workers:
        worker.failed.connect(lambda *args: errors.append(args), Qt.DirectConnection)
    workers[1].progress.connect(lambda _, msg: waiting.set() if 'shared' in msg else None, Qt.DirectConnection)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(workers[0].run)
        assert entered.wait(5)
        second = pool.submit(workers[1].run)
        try:
            assert waiting.wait(5)
        finally:
            release.set()
        first.result(5)
        second.result(5)
    assert not errors
    assert len(calls) == 3 and calls.count(()) == 1
    assert sorted(formatted) == [('Smith', 'Speaker 1: They called Smith yesterday.'),
                                 ('Smythe', 'Speaker 1: They called Smythe yesterday.')]
    assert wav.with_suffix('.raw.txt').read_text(encoding='utf-8') in {text for _, text in formatted}
