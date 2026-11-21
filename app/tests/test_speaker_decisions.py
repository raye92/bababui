"""Speaker decisions through Bababui's normal pipeline and editor.

The acceptance test from the reporter's editor: the witness explains clinical
findings, another voice says "Okay.", and the witness resumes, "You have to have
those objective findings." Gemini put "Okay." and the resumed answer under the
examiner's number. The exchange supports the resumed answer, so it goes to the
witness without a question. The audio recheck cannot tell who said "Okay.", so
the reporter is asked only that. Assigning it changes only the label and leaves
the wording suggestion next to it pending.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from hashlib import sha256
import json
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.src.ai_review import AssistedReview
from app.src.audio_pipeline import Transcription, Word, render
from app.src.speaker_questions import TURN, VOICE
from app.src.suggestion_filter import auto_accept, begin_review
from app.tests.test_native_editor import native_window, source_zip  # noqa: F401 - fixture
from app.tests.test_speaker_questions import DRAFT as GROUP_DRAFT, ROUGH as GROUP_ROUGH, review_state
from shared.speaker_review import PROMPT as SPEAKER_PROMPT
from shared.spelling_review import PROMPT as SPELLING_PROMPT

TURNS = [('Speaker 1', 880.0, 'Good morning, Doctor.'),
         ('Speaker 2', 883.0, 'Good morning.'),
         ('Speaker 1', 885.0, 'Let us begin with your examination.'),
         ('Speaker 1', 890.0, 'Doctor, did you examine the knee?'),
         ('Speaker 3', 895.0, 'Objection. Form.'),
         ('Speaker 2', 898.0, 'I examined both knees.'),
         ('Speaker 1', 940.0, 'Was there swelling?'),
         ('Speaker 3', 945.0, 'Objection. Vague.'),
         ('Speaker 2', 948.0, 'There was mild swelling.'),
         ('Speaker 1', 1000.0, 'Doctor, what are the clinical findings?'),
         ('Speaker 2', 1004.0, 'The clinical findings are the objective signs on examination.'),
         # Gemini merged another voice's "Okay." and the witness resuming under the examiner's number.
         ('Speaker 1', 1052.0, 'Okay. You have to have those objective findings.'),
         ('Speaker 1', 1060.0, 'Thank you, Doctor.')]
DECISIONS = {'participants': {'SPEAKER 1': 'examining attorney', 'SPEAKER 2': 'witness',
                              'SPEAKER 3': 'defense attorney'},
             # Turn 11 is Gemini's "Okay. You have to have those objective findings. Thank you, Doctor."
             'turns': [{'id': 11, 'speaker': 'SPEAKER 3', 'why': 'Defense counsel acknowledges the answer.',
                        'splits': [{'at': 'You have to have those objective findings', 'speaker': 'SPEAKER 2',
                                    'why': 'The witness resumes the interrupted answer.'},
                                   {'at': 'Thank you, Doctor', 'speaker': 'SPEAKER 1',
                                    'why': 'The examiner thanks the witness.'}]}]}
DRAFT = '\n'.join([
    '     SPEAKER 1:  Good morning, Doctor.',
    '     THE WITNESS:  Good morning.',
    '     SPEAKER 1:  Let us begin with your examination.',
    'EXAMINATION',
    'BY SPEAKER 1:',
    '     Q    Doctor, did you examine the knee?',
    '     SPEAKER 3:  Objection.  Form.',
    '     A    I examined both knees.',
    '     Q    Was there swelling?',
    '     SPEAKER 3:  Objection.  Vague.',
    '     A    There was mild swelling.',
    '     Q    Doctor, what are the clinical findings?',
    '     A    The clinical findings are the objective signs on examination.',
    '     Q    Okay.',
    '     A    You have to have those objective findings.',
    '     Q    Thank you, Doctor.'])
ROUGH = '\n'.join([
    '     MR. RAMIREZ:  Good morning, Doctor.',
    '     THE WITNESS:  Good morning.',
    '     MR. RAMIREZ:  Let us begin with your examination.',
    'EXAMINATION',
    'BY MR. RAMIREZ:',
    '     Q    Doctor, did you examine the knee?',
    '     MR. SWEET:  Objection.  Form.',
    '     A    I examined both knees.',
    '     Q    Was there swelling?',
    '     MR. SWEET:  Objection.  Vague.',
    '     A    There was mild swelling.',
    '     Q    Doctor, what are the clinical findings?',
    '     A    The clinical findings are the objective signs on examination.',
    '     MR. SWEET:  Okay.',
    '     A    You got to have those objective findings.',
    '     Q    Thank you, Doctor.'])


def words():
    found = []
    for speaker, start, text in TURNS:
        found += [Word(t, speaker, round(start + i * .4, 2), round(start + i * .4 + .3, 2))
                  for i, t in enumerate(text.split())]
    return tuple(found)


def processed(tmp_path, monkeypatch, original):
    """Run the normal processing worker with fake Gemini and review models."""
    from app.src import jobs
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    wav = tmp_path / 'deposition.wav'
    wav.write_bytes(b'recording')
    stitched = words()
    asked = []

    class Audio:
        def __init__(self, *args):
            pass

        def __call__(self, question):
            asked.append(question)
            return {'speaker': 'uncertain', 'why': 'Too short to tell the voices apart.'}
    monkeypatch.setattr(jobs, 'AudioSpeakerCheck', Audio)
    monkeypatch.setattr(jobs, 'has_key', lambda key: True)
    monkeypatch.setattr(jobs, 'VoiceComparison', lambda *args: None)

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            identities = {f'Speaker {n}': {'chunk': 1, 'status': 'first chunk'} for n in (1, 2, 3)}
            return Transcription(render(stitched), stitched, (), 1100000, sha256(path.read_bytes()).hexdigest(),
                                 identities)

    class Processor:
        def __init__(self, config, model):
            pass

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            if prompt == SPEAKER_PROMPT:
                return json.dumps(DECISIONS)
            if prompt == 'rules':
                return DRAFT
            if prompt == SPELLING_PROMPT:
                return '{"words": []}'
            return '{}'

    request = Request('doc', str(wav), 'formatter', 'transcribe', 'rules', {'gemini_api_key': 'key'},
                      original=original, review_model='reviewer')
    worker = ProcessingWorker(request, TranscriptionCoordinator(), Pipeline, Processor)
    reviewed, failed = [], []
    worker.reviewed.connect(lambda *args: reviewed.append(args))
    worker.failed.connect(lambda *args: failed.append(args))
    worker.run()
    assert not failed, failed
    return reviewed[0], asked


def editor_with_rough(native_window, tmp_path, rough):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText(rough)
    return view


def pending(state):
    from app.src.suggestions import suggestions
    return [(state.original.text[a:b], state.incoming.text[c:d])
            for change in suggestions(state.original, state.incoming) for a, b, c, d in change.ranges]


def test_only_who_said_okay_is_asked_and_assigning_it_keeps_the_wording_pending(native_window, tmp_path,
                                                                                 monkeypatch):
    view = editor_with_rough(native_window, tmp_path, ROUGH)
    state = view.document.native
    (_, result, warnings, _), asked = processed(tmp_path, monkeypatch, state.original)
    view.receive_reviewed(result, warnings)
    QApplication.processEvents()

    # The audio recheck heard the exchange around "Okay.": two turns before and after it.
    (question,) = asked
    assert question['turn']['text'] == 'Okay.' and question['earlier'] and question['later']
    # One question, about "Okay." only, at its time in the original WAV.
    (okay,) = view.diff_view.questions
    assert (okay.kind, okay.text, okay.time) == (TURN, 'Okay.', 1052.0)
    assert okay.suggestion == 'MR. SWEET'
    card = view.diff_view.question_cards[0]
    assert card.findChild(QLabel, 'questionTitle').text() == 'Who said this?'
    assert 'Speakers · 1 unresolved · 1 turn' in view.diff_view.summary.text()
    # The resumed answer went to the witness automatically. Only its corrected label is yellow.
    text = state.incoming.text
    assert [text[a:b] for a, b in view.diff_view.speaker_label_ranges] == ['A']
    assert view.diff_view.speaker_label_ranges[0][0] == text.index('     A    You have to have') + 5
    wording = ('got', 'have')
    assert wording in pending(state)

    card.combo.setCurrentIndex(card.combo.findData('MR. SWEET'))
    card.this_button.click()
    QApplication.processEvents()
    assert '     MR. SWEET:  Okay.' in state.incoming.text
    assert view.diff_view.questions == []
    # Only the label changed: the wording suggestion beside it is still waiting.
    assert pending(state) == [wording]
    assert 'Assigned 1 turn to MR. SWEET.' in view.document.status

    view.diff_view.undo_button.click()
    assert [q.text for q in view.diff_view.questions] == ['Okay.']
    assert '     Q    Okay.' in state.incoming.text


def group_result(state, draft=GROUP_DRAFT, rename=None):
    """A review of the grouped-voice job, as the worker returns it."""
    reference = review_state()
    record = reference.review['speaker_review']
    if rename:
        record = json.loads(json.dumps(record).replace(*rename))
    review = SimpleNamespace(original=state.original)
    begin_review(review, draft)
    review.review['speaker_review'] = record
    auto_accept(review)
    snapshot = (review.original, review.incoming, review.review)
    return AssistedReview(state.original, None, snapshot, snapshot, snapshot, 'Speaker review.', None)


def test_a_recurring_voice_is_assigned_once_with_undo_reopen_and_rerun(native_window, tmp_path, monkeypatch):
    from app.src import documents
    view = editor_with_rough(native_window, tmp_path, GROUP_ROUGH)
    state = view.document.native
    view.receive_reviewed(group_result(state), [])
    voice, reporter, okay = view.diff_view.questions
    assert (voice.kind, voice.turns, reporter.kind, okay.kind) == (VOICE, 2, TURN, TURN)
    card = view.diff_view.question_cards[0]
    assert card.all_button.text() == 'Assign all 2 linked turns' and card.all_button.isVisible()
    assert 'Speakers · 3 unresolved · 4 turns' in view.diff_view.summary.text()
    # Resolved speakers stay collapsed.
    resolved = view.diff_view.speaker_scroll.widget().findChild(QWidget, 'resolvedSpeakers')
    assert resolved is not None and not resolved.isVisible()
    before = pending(state)

    card.combo.setCurrentIndex(card.combo.findData('MR. SWEET'))
    card.all_button.click()
    assert state.incoming.text.count('MR. SWEET:') == 2
    assert [q.text for q in view.diff_view.questions] == ['Let us go off the record.', 'Okay.']
    assert len(pending(state)) == len(before) - 2
    view.diff_view.undo_button.click()
    assert len(view.diff_view.questions) == 3
    card = view.diff_view.question_cards[0]
    card.combo.setCurrentIndex(card.combo.findData('MR. SWEET'))
    card.all_button.click()
    assignments = state.review['assignments']
    assert [a['name'] for a in assignments] == ['MR. SWEET'] and len(assignments[0]['times']) == 2

    # Close and reopen: the assignment and its audio times stay with the job.
    path = tmp_path / 'job.bababui'
    documents.save_document(view.document, path)
    reopened = documents.open_document(path)
    assert reopened.native.review['assignments'] == assignments
    again = native_window.add_document(reopened)
    assert [q.text for q in again.diff_view.questions] == ['Let us go off the record.', 'Okay.']

    # Rerun: Gemini numbers the attorney 9 this time, and gives the reporter the old number 6.
    draft = GROUP_DRAFT
    lines = draft.split('\n')
    for k, line in enumerate(lines):
        if 'SPEAKER 6' in line and 'record' not in line:
            lines[k] = line.replace('SPEAKER 6', 'SPEAKER 9')
    rerun = group_result(state, '\n'.join(lines), rename=('"Speaker 6"', '"Speaker 9"'))
    view.receive_reviewed(rerun, [])
    # The name follows the audio, not the number: both attorney turns are assigned again,
    # and the reporter's turn, which now has the old number, is still asked.
    assert state.incoming.text.count('MR. SWEET:') == 2
    remaining = [q.text for q in view.diff_view.questions]
    assert 'Let us go off the record.' in remaining
    assert 'Thank you, Doctor, I have nothing further at this time.' not in remaining


def test_review_jumps_to_the_identifying_clip_and_plays_the_exchange_around_it(native_window, tmp_path):
    view = editor_with_rough(native_window, tmp_path, GROUP_ROUGH)
    state = view.document.native
    view.receive_reviewed(group_result(state), [])
    played = []
    view.playback = SimpleNamespace(seek=lambda ms: played.append(('seek', ms)),
                                    player=SimpleNamespace(play=lambda: played.append(('play',))),
                                    stop=lambda: None)
    card = view.diff_view.question_cards[0]
    card.review_button.click()
    question = card.question
    # Four seconds before the clip, so the exchange that leads into it is heard.
    assert played == [('seek', (2000 - 4) * 1000), ('play',)]
    change = view.diff_view.changes[view.diff_view.current]
    assert any(c <= question.label[0] < d for _, _, c, d in change.ranges)
    assert view.diff_view.speaker_filter == 'SPEAKER 6'
    view.playback = None
