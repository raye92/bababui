"""Whom a turn addressed, through Bababui's normal pipeline and editor.

The formatter labels Mr. Sweet's question Q. The witness asks, "Are you asking me or
counsel?" and Mr. Sweet answers, "Counsel, I'm sorry." The worker corrects the
labels after the formatter, the speaker review leaves them alone, and the reporter's
editor shows all three turns as colloquy under MR. SWEET: and THE WITNESS:. Accepting
the label correction leaves the wording suggestion in the same question pending.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from hashlib import sha256
import json

from PySide6.QtWidgets import QApplication, QLabel
import pytest

from app.src.audio_pipeline import Transcription, Word, render
from app.tests.test_native_editor import native_window  # noqa: F401 - fixture
from app.tests.test_speaker_decisions import editor_with_rough, pending
from shared.speaker_review import PROMPT as SPEAKER_PROMPT
from shared.spelling_review import PROMPT as SPELLING_PROMPT

QUESTION = 'What page are you on again, and what paragraph?'
OPENING = [('Speaker 1', 10.0, 'Good morning, Doctor.'),
           ('Speaker 2', 13.0, 'Good morning.'),
           ('Speaker 3', 15.0, 'Good morning, everyone.'),
           ('Speaker 2', 17.0, 'Can everyone hear me?'),
           ('Speaker 1', 18.5, 'Yes, we can hear you.'),
           ('Speaker 3', 19.5, 'I can hear you too.'),
           ('Speaker 1', 20.0, 'Doctor, please turn to your report.'),
           ('Speaker 2', 24.0, 'Okay.'),
           ('Speaker 1', 30.0, QUESTION),
           ('Speaker 2', 34.0, 'Are you asking me or counsel? Sorry.')]
TO_COUNSEL = OPENING + [('Speaker 1', 38.0, "Counsel, I'm sorry."),
                        ('Speaker 3', 41.0, 'Page 12, paragraph 3.'),
                        ('Speaker 1', 45.0, 'Thank you. Doctor, do you see paragraph 3?'),
                        ('Speaker 2', 50.0, 'Yes, I do.')]
TO_WITNESS = OPENING + [('Speaker 1', 38.0, 'You, Doctor.'),
                        ('Speaker 2', 41.0, 'Page 12, paragraph 3.'),
                        ('Speaker 1', 45.0, 'Thank you. Do you see where it says lumbar strain?'),
                        ('Speaker 2', 50.0, 'Yes, I do.')]
HEAD = ['     SPEAKER 1:  Good morning, Doctor.',
        '     SPEAKER 2:  Good morning.',
        '     SPEAKER 3:  Good morning, everyone.',
        '     SPEAKER 2:  Can everyone hear me?',
        '     SPEAKER 1:  Yes, we can hear you.',
        '     SPEAKER 3:  I can hear you too.',
        'EXAMINATION',
        'BY SPEAKER 1:',
        '     Q    Doctor, please turn to your report.',
        '     A    Okay.']
# The formatter's first guess: the question to counsel as Q.
COUNSEL_DRAFT = '\n'.join(HEAD + [
    f'     Q    {QUESTION}',
    '     A    Are you asking me or counsel?  Sorry.',
    "     Q    Counsel, I'm sorry.",
    '     SPEAKER 3:  Page 12, paragraph 3.',
    'BY SPEAKER 1:',
    '     Q    Thank you.  Doctor, do you see paragraph 3?',
    '     A    Yes, I do.'])
# The formatter's first guess the other way: the question to the witness as colloquy.
WITNESS_DRAFT = '\n'.join(HEAD + [
    f'     SPEAKER 1:  {QUESTION}',
    '     SPEAKER 2:  Are you asking me or counsel?  Sorry.',
    '     SPEAKER 1:  You, Doctor.',
    '     SPEAKER 2:  Page 12, paragraph 3.',
    'BY SPEAKER 1:',
    '     Q    Thank you.  Do you see where it says lumbar strain?',
    '     A    Yes, I do.'])
# The reporter's rough: the question as Q, without "again".
ROUGH_HEAD = ['     MR. SWEET:  Good morning, Doctor.',
              '     THE WITNESS:  Good morning.',
              '     MS. JONES:  Good morning, everyone.',
              '     THE WITNESS:  Can everyone hear me?',
              '     MR. SWEET:  Yes, we can hear you.',
              '     MS. JONES:  I can hear you too.',
              'EXAMINATION',
              'BY MR. SWEET:',
              '     Q    Doctor, please turn to your report.',
              '     A    Okay.',
              '     Q    What page are you on, and what paragraph?',
              '     A    Are you asking me or counsel?  Sorry.']
COUNSEL_ROUGH = '\n'.join(ROUGH_HEAD + [
    "     Q    Counsel, I'm sorry.",
    '     MS. JONES:  Page 12, paragraph 3.',
    'BY MR. SWEET:',
    '     Q    Thank you.  Doctor, do you see paragraph 3?',
    '     A    Yes, I do.'])
WITNESS_ROUGH = '\n'.join(ROUGH_HEAD + [
    '     Q    You, Doctor.',
    '     A    Page 12, paragraph 3.',
    '     Q    Thank you.  Do you see where it says lumbar strain?',
    '     A    Yes, I do.'])
PARTICIPANTS = {'SPEAKER 1': 'examining attorney', 'SPEAKER 2': 'witness', 'SPEAKER 3': 'defense attorney'}
DECISIONS = {'participants': PARTICIPANTS, 'turns': []}
# Gemini put the witness's clarification under the examiner's number, so the question,
# the clarification and the reply are one turn (id 9). The speaker review splits it.
MERGED = [(('Speaker 1' if text.startswith('Are you asking') else speaker), start, text)
          for speaker, start, text in TO_COUNSEL]
SPLIT = {'participants': PARTICIPANTS,
         'turns': [{'id': 9, 'speaker': 'SPEAKER 1', 'why': 'The examiner asks about the page.',
                    'splits': [{'at': 'Are you asking me or counsel', 'speaker': 'SPEAKER 2',
                                'why': 'The witness asks whom the question was for.'},
                               {'at': "Counsel, I'm sorry", 'speaker': 'SPEAKER 1',
                                'why': 'The examiner answers the witness.'}]}]}


def processed(tmp_path, monkeypatch, original, turns, draft, decisions=DECISIONS):
    """The normal processing worker with fake Gemini, formatter and review models.
    Returns the reviewed result and what the formatter was given."""
    from app.src import jobs
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    wav = tmp_path / 'deposition.wav'
    wav.write_bytes(b'recording')
    stitched = tuple(Word(t, speaker, round(start + i * .4, 2), round(start + i * .4 + .3, 2))
                     for speaker, start, text in turns for i, t in enumerate(text.split()))
    given = []
    monkeypatch.setattr(jobs, 'has_key', lambda key: True)
    monkeypatch.setattr(jobs, 'VoiceComparison', lambda *args: None)
    monkeypatch.setattr(jobs, 'AudioSpeakerCheck', lambda *args: lambda question: {'speaker': 'uncertain'})

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            identities = {f'Speaker {n}': {'chunk': 1, 'status': 'first chunk'} for n in (1, 2, 3)}
            return Transcription(render(stitched), stitched, (), 60000, sha256(path.read_bytes()).hexdigest(),
                                 identities)

    class Processor:
        def __init__(self, config, model):
            pass

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            if prompt == SPEAKER_PROMPT:
                return json.dumps(decisions)
            if prompt == 'rules':
                given.append(text)
                return draft
            if prompt == SPELLING_PROMPT:
                return '{"words": []}'
            return '{}'

    request = Request('doc', str(wav), 'formatter', 'transcribe', 'rules', {'gemini_api_key': 'key'},
                      original=original, review_model='reviewer')
    worker = ProcessingWorker(request, TranscriptionCoordinator(), Pipeline, Processor)
    reviewed, failed, progress = [], [], []
    worker.reviewed.connect(lambda *args: reviewed.append(args))
    worker.failed.connect(lambda *args: failed.append(args))
    worker.progress.connect(lambda _, message: progress.append(message))
    worker.run()
    assert not failed, failed
    assert 'Checking whom each turn addressed...' in progress
    (given,) = given
    return reviewed[0], given


def card_for(view, line, part):
    """The review card whose change covers `part` of `line` in the AI draft."""
    incoming = view.document.native.incoming.text
    start = incoming.index(line) + line.index(part)
    end = start + len(part)
    for index, change in enumerate(view.diff_view.changes):
        if any(c < end and d > start for _, _, c, d in change.ranges):
            return index, view.diff_view.cards[index]
    raise AssertionError(f'No card for {part!r} in {line!r}')


@pytest.mark.parametrize('gemini', ['labels right', 'clarification under the examiner'])
def test_a_question_to_counsel_becomes_colloquy_in_the_editor(native_window, tmp_path, monkeypatch, gemini):
    view = editor_with_rough(native_window, tmp_path, COUNSEL_ROUGH)
    state = view.document.native
    turns, decisions = (TO_COUNSEL, DECISIONS) if gemini == 'labels right' else (MERGED, SPLIT)
    (_, result, warnings, _), given = processed(tmp_path, monkeypatch, state.original, turns, COUNSEL_DRAFT,
                                                decisions)
    # The formatter was given who spoke each turn after the speaker review.
    assert [f'Speaker 1: {QUESTION}', 'Speaker 2: Are you asking me or counsel? Sorry.',
            "Speaker 1: Counsel, I'm sorry."] == given.split('\n')[8:11]
    view.receive_reviewed(result, warnings)
    QApplication.processEvents()

    incoming = state.incoming.text.split('\n')
    exchange = incoming[incoming.index(f'     MR. SWEET:  {QUESTION}'):]
    assert exchange == [f'     MR. SWEET:  {QUESTION}',
                        '     THE WITNESS:  Are you asking me or counsel?  Sorry.',
                        "     MR. SWEET:  Counsel, I'm sorry.",
                        '     MS. JONES:  Page 12, paragraph 3.',
                        '     MR. SWEET:  Thank you.',
                        'BY MR. SWEET:',
                        '     Q    Doctor, do you see paragraph 3?',
                        '     A    Yes, I do.']
    # The question, the clarification, the reply, and "Thank you." split from the resumed Q.
    assert 'Addressee check: 5 labels revised.' in result.summary

    # The label correction is its own card, with why. The wording is another card.
    wording, label = ('', ' again'), ('     Q    ', '     MR. SWEET:  ')
    assert label in pending(state) and wording in pending(state)
    index, card = card_for(view, f'     MR. SWEET:  {QUESTION}', 'MR. SWEET:')
    assert card.findChildren(QLabel)[0].text().startswith('Q/A or colloquy')
    why = card.findChild(QLabel, 'addresseeReason').text()
    assert "“Counsel, I'm sorry.”" in why and 'addressed to counsel' in why
    _, wording_card = card_for(view, QUESTION, ' again')
    assert wording_card.findChild(QLabel, 'addresseeReason') is None
    # A label the speaker review corrected stays yellow under its new colloquy label.
    text = state.incoming.text
    corrected = [text[a:b] for a, b in view.diff_view.speaker_label_ranges]
    assert corrected == ([] if gemini == 'labels right' else ['THE WITNESS'])

    # Accepting the label correction keeps the spoken words and leaves the wording pending.
    view.review(index, True)
    QApplication.processEvents()
    assert '     MR. SWEET:  What page are you on, and what paragraph?' in state.original.text.split('\n')
    assert pending(state).count(label) == 1  # only "Counsel, I'm sorry." is left
    assert wording in pending(state)

    # Saved and reopened, the remaining label card still says why.
    from app.src import documents
    path = tmp_path / 'job.bababui'
    documents.save_document(view.document, path)
    again = native_window.add_document(documents.open_document(path))
    _, card = card_for(again, "     MR. SWEET:  Counsel, I'm sorry.", 'MR. SWEET:')
    assert 'addressing counsel' in card.findChild(QLabel, 'addresseeReason').text()


def test_a_question_to_the_witness_stays_q_and_a_in_the_editor(native_window, tmp_path, monkeypatch):
    """The paired case: "You, Doctor." The formatter guessed colloquy; the reply says Q."""
    view = editor_with_rough(native_window, tmp_path, WITNESS_ROUGH)
    state = view.document.native
    (_, result, warnings, _), _ = processed(tmp_path, monkeypatch, state.original, TO_WITNESS, WITNESS_DRAFT)
    view.receive_reviewed(result, warnings)
    QApplication.processEvents()

    incoming = state.incoming.text.split('\n')
    exchange = incoming[incoming.index(f'     Q    {QUESTION}'):]
    assert exchange == [f'     Q    {QUESTION}',
                        '     A    Are you asking me or counsel?  Sorry.',
                        '     Q    You, Doctor.',
                        '     A    Page 12, paragraph 3.',
                        '     Q    Thank you.  Do you see where it says lumbar strain?',
                        '     A    Yes, I do.']
    # The labels already match the rough. Only the wording is left to decide.
    assert pending(state) == [('', ' again')]
