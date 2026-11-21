"""The speaker attribution and turn-boundary review in the live AI-draft pipeline."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from hashlib import sha256
import json

from app.src.audio_pipeline import Transcription, Word, render
from app.tests.test_suggestions import revision
from shared.speaker_review import PROMPT as SPEAKER_PROMPT, review_speakers
from shared.spelling_review import PROMPT as SPELLING_PROMPT

WORDS = tuple(Word(text, speaker, start, start + .3) for text, speaker, start in (
    ('Good', 'Speaker 1', 1.0), ('morning.', 'Speaker 1', 1.4),
    ('Doctor,', 'Speaker 2', 3.0), ('when', 'Speaker 2', 3.4), ('did', 'Speaker 2', 3.8), ('you', 'Speaker 2', 4.2),
    ('examine', 'Speaker 2', 4.6), ('him?', 'Speaker 2', 5.0), ('I', 'Speaker 2', 6.0), ('first', 'Speaker 2', 6.4),
    ('examined', 'Speaker 2', 6.8), ('him', 'Speaker 2', 7.2), ('in', 'Speaker 2', 7.6), ('March.', 'Speaker 2', 8.0)))
DECISIONS = {'turns': [{'id': 1, 'speaker': 'SPEAKER 1'}, {'id': 2, 'speaker': 'SPEAKER 2', 'splits': [
    {'at': 'I first examined him', 'speaker': 'SPEAKER 1', 'why': 'The doctor answers.'}]}]}
FORMATTED = ('     SPEAKER 1:  Good morning.\n\nEXAMINATION\nBY SPEAKER 2:\n'
             '     Q    Doctor, when did you examine him?\n     A    I first examined him in March.')


def test_worker_reviews_speakers_before_formatting_and_keeps_the_gemini_baseline(tmp_path):
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    wav = tmp_path / 'job.wav'
    wav.write_bytes(b'recording')
    gemini = render(WORDS)

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            return Transcription(gemini, WORDS, (), 9000, sha256(path.read_bytes()).hexdigest())

    calls = []

    class Processor:
        def __init__(self, config, model):
            self.model = model

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            calls.append((self.model, prompt, text))
            if prompt == SPEAKER_PROMPT:
                return json.dumps(DECISIONS)
            if prompt == SPELLING_PROMPT:
                return '{"words": []}'
            return FORMATTED

    request = Request('doc', str(wav), 'formatter', 'transcribe', 'rules', {}, original=revision(FORMATTED),
                      review_model='reviewer', context='Witness (deponent): Dr. Paul Chen.')
    worker = ProcessingWorker(request, TranscriptionCoordinator(), Pipeline, Processor)
    reviewed, failed, progress = [], [], []
    worker.reviewed.connect(lambda *args: reviewed.append(args))
    worker.failed.connect(lambda *args: failed.append(args))
    worker.progress.connect(lambda _, message: progress.append(message))
    worker.run()

    assert not failed
    # The AI review model checks speakers on the stitched Gemini transcript first.
    # Spellings are checked after formatting, on the rough and the draft.
    assert [(model, prompt == SPEAKER_PROMPT) for model, prompt, _ in calls] == [
        ('reviewer', True), ('formatter', False), ('reviewer', False)]
    assert calls[2][1] == SPELLING_PROMPT
    sent = json.loads(calls[0][2])
    assert sent['case_context'] == 'Witness (deponent): Dr. Paul Chen.'
    assert calls[1][2] == ('Speaker 1: Good morning.\nSpeaker 2: Doctor, when did you examine him?\n'
                           'Speaker 1: I first examined him in March.')
    assert wav.with_suffix('.raw.txt').read_text(encoding='utf-8') == gemini
    assert progress.index('Reviewing speakers and turn boundaries...') < progress.index('Formatting transcript...')
    _, result, warnings, _ = reviewed[0]
    assert warnings == []
    assert result.summary.startswith('Speaker review: 1 label corrected, 1 turn split, 0 flagged. '
                                     'Spelling review: no words to check. ')
    for snapshot in (result.before_rules, result.after_rules, result.after_ai):
        record = snapshot[2]['speaker_review']
        assert record['corrected'] and record['tokens'][:2] == ['good', 'morning']


def test_worker_without_ai_review_formats_gemini_text_unchanged(tmp_path):
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    wav = tmp_path / 'job.wav'
    wav.write_bytes(b'recording')

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            return Transcription(render(WORDS), WORDS, (), 9000, sha256(path.read_bytes()).hexdigest())

    sent = []

    class Processor:
        def __init__(self, *args):
            pass

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            sent.append(prompt)
            return FORMATTED

    worker = ProcessingWorker(Request('doc', str(wav), 'formatter', 'transcribe', 'rules', {}),
                              TranscriptionCoordinator(), Pipeline, Processor)
    worker.run()
    assert sent == ['rules']


def test_review_view_marks_only_the_corrected_label_in_yellow():
    from PySide6.QtWidgets import QApplication
    from app.src.review_view import ReviewView
    QApplication.instance() or QApplication([])
    record = review_speakers(WORDS, lambda payload, prompt: json.dumps(DECISIONS)).record()
    original = revision(FORMATTED.replace('him?\n     A    I first', 'him?  I first'))
    incoming = revision(FORMATTED)
    view = ReviewView()
    view.set_revisions(original, incoming, review={'speaker_review': record})
    assert [incoming.text[a:b] for a, b in view.corrected_speaker_ranges] == ['A']
    assert view.speaker_label_ranges == view.corrected_speaker_ranges
    view.set_revisions(original, incoming, review=None)
    assert view.corrected_speaker_ranges == () and view.speaker_label_ranges == ()
    view.close()


def test_notice_context_names_the_witness_and_attorneys():
    from app.src.notice_model import Appearance, NoticeDetails
    details = NoticeDetails(deponent='Dr. Paul Chen', taking_side='Defendant', defendant='Acme Corp.',
                            appearances=(Appearance('Defendant', 'Ruiz Law Group', 'Ana Ruiz'),
                                         Appearance('Applicant', '', 'Mark Lee')))
    assert details.speaker_context() == ('Witness (deponent): Dr. Paul Chen.\n'
                                         'Defendant attorney: Ana Ruiz, Ruiz Law Group.\n'
                                         'Applicant attorney: Mark Lee.\n'
                                         'Deposition noticed by the defendant side.\n'
                                         'Defendant: Acme Corp.')
    assert NoticeDetails().speaker_context() == ''


def test_testing_mode_saves_the_speaker_review_request_and_decisions(tmp_path, monkeypatch):
    from app.src import jobs
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    monkeypatch.setattr(jobs.tempfile, 'gettempdir', lambda: str(tmp_path))
    wav = tmp_path / 'job.wav'
    wav.write_bytes(b'recording')

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            return Transcription(render(WORDS), WORDS, (), 9000, sha256(path.read_bytes()).hexdigest())

    class Processor:
        def __init__(self, *args):
            pass

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            return json.dumps(DECISIONS) if prompt == SPEAKER_PROMPT else FORMATTED

    request = Request('doc', str(wav), 'formatter', 'transcribe', 'rules', {'testing': True},
                      original=revision(FORMATTED), review_model='reviewer')
    ProcessingWorker(request, TranscriptionCoordinator(), Pipeline, Processor).run()
    logs = sorted(p.name.rsplit('-', 1)[1] for p in (tmp_path / 'bababui-transcriptions').glob('speaker-review-*'))
    assert logs == ['1.json', 'result.json']
    saved = json.loads(next((tmp_path / 'bababui-transcriptions').glob('*-result.json')).read_text(encoding='utf-8'))
    assert saved['summary'] == 'Speaker review: 1 label corrected, 1 turn split, 0 flagged.'


def test_audio_check_sends_the_clip_with_the_turns_before_and_after(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from app.src import speaker_audio
    from app.src.speaker_audio import AudioSpeakerCheck
    clips, deleted, sent = [], [], []

    def prepare(path, segment, destination):
        clips.append(segment)
        Path(destination).write_bytes(b'clip')
    monkeypatch.setattr(speaker_audio.media, 'prepare', prepare)
    replies = iter(['{"speaker": "SPEAKER 1", "why": "Same voice as the examiner."}',
                    '```json\n{"speaker": "uncertain"}\n```', '{"speaker": "SPEAKER 3"}'])

    class Files:
        def upload(self, file, config):
            assert Path(file).read_bytes() == b'clip' and config == {'mime_type': 'audio/wav'}
            return SimpleNamespace(name='files/clip', uri='gs://clip', state='ACTIVE')

        def delete(self, name):
            deleted.append(name)

    class Interactions:
        def create(self, **kwargs):
            sent.append(kwargs)
            return SimpleNamespace(status='completed', output_text=next(replies))

    check = AudioSpeakerCheck(tmp_path / 'job.wav', 'key', 'gemini-4-argon',
                              sdk=SimpleNamespace(files=Files(), interactions=Interactions()))
    question = {'turn': {'speaker': 'SPEAKER 1', 'proposed': 'SPEAKER 2', 'text': 'Doctor, when you reviewed',
                         'start': 324.1, 'end': 325.9},
                'before': {'speaker': 'SPEAKER 2', 'text': 'The prior MRI findings.', 'start': 319.7, 'end': 323.8},
                'after': {'speaker': 'SPEAKER 3', 'text': 'Objection.', 'start': 326.1, 'end': 328.9},
                'participants': {'SPEAKER 1': 'examining attorney Mr. Smith'}}
    assert check(question) == {'speaker': 'SPEAKER 1', 'why': 'Same voice as the examiner.'}
    assert clips == [{'start': 319.45, 'end': 329.15}]
    assert deleted == ['files/clip']
    request = sent[0]
    assert request['model'] == 'gemini-4-argon' and request['store'] is False
    assert request['input'][0] == {'type': 'audio', 'uri': 'gs://clip', 'mime_type': 'audio/wav'}
    payload = json.loads(request['input'][1]['text'])
    assert (payload['original'], payload['proposed']) == ('SPEAKER 1', 'SPEAKER 2')
    assert payload['before'] == {'speaker': 'SPEAKER 2', 'text': 'The prior MRI findings.', 'from': 0.25, 'to': 4.35}
    assert payload['disputed']['from'] == 4.65 and payload['after']['speaker'] == 'SPEAKER 3'
    # Anything but one of the two labels is uncertain.
    assert check(question)['speaker'] == 'uncertain'
    assert check(question)['speaker'] == 'uncertain'
    assert deleted == ['files/clip'] * 3
