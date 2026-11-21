"""Regression: the examiner's interrupted question must stay Q.

From deposition_3_speakers.wav at 5:24. Gemini labeled "Doctor, when you reviewed
the records" as SPEAKER 1, the examiner, and the reporter's rough has it as Mr.
Smith's Q. The speaker review proposed the witness instead, and the editor then
offered Q -> THE WITNESS:. The turn speaks directly to the doctor, and the next
turn says "Let him finish the question", so the proposal conflicts with the
exchange and must not reach the editor.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from hashlib import sha256
import json
import re

import pytest

from app.src.audio_pipeline import Transcription, Word, render
from app.tests.test_suggestions import revision
from shared import speaker_review
from shared.speaker_review import PROMPT as SPEAKER_PROMPT

TURNS = (
    (281.0, 'Speaker 3', 'Can we go off the record for a moment?'),
    (284.0, 'Speaker 2', 'Of course, take your time.'),
    (287.0, 'Speaker 1', 'Back on the record.'),
    (289.0, 'Speaker 2', 'I am ready to continue.'),
    (300.0, 'Speaker 1', 'Doctor, I have just a few follow-up questions. You testified that you assigned 20% '
                         'apportionment to pre-existing degeneration. Correct?'),
    (309.7, 'Speaker 2', 'Correct.'),
    (311.2, 'Speaker 1', 'Did you identify any objective findings supporting that apportionment?'),
    (315.6, 'Speaker 2', 'Yes.'),
    (317.0, 'Speaker 1', 'What findings did you rely upon?'),
    (319.7, 'Speaker 2', "The prior MRI findings and the applicant's medical history."),
    (324.1, 'Speaker 1', 'Doctor, when you reviewed the records'),
    (326.1, 'Speaker 3', 'Objection, let him finish the question.'),
    (329.2, 'Speaker 1', 'Did you see the MRI report from March?'),
    (332.1, 'Speaker 2', 'Yes, I did.'),
)
ROUGH = """     MS. JONES:  Can we go off the record for a moment?
     THE WITNESS:  Of course, take your time.
     MR. SMITH:  Back on the record.
     THE WITNESS:  I am ready to continue.
BY MR. SMITH:
     Q    Doctor, I have just a few follow-up questions.  You testified that you assigned 20 percent apportionment to preexisting degeneration?
     A    Correct.
     Q    Did you identify any objective findings supporting that apportionment?
     A    Yes.
     Q    What findings did you rely upon?
     A    The prior MRI findings and the applicant's medical history.
     Q    Doctor, when you reviewed the records?
     MS. JONES:  Objection.  Let him finish the question.
BY MR. SMITH:
     Q    Did you see the MRI report from March?
     A    Yes, I did.
"""
INTERRUPTED = 'Doctor, when you reviewed the records'
COLLOQUY = {'Can we go off the record for a moment?', 'Of course, take your time.', 'Back on the record.',
            'I am ready to continue.'}
# The review model's answer that caused the bad suggestion.
PROPOSAL = {'participants': {'SPEAKER 1': 'examining attorney Mr. Smith', 'SPEAKER 2': 'witness Dr. Chen',
                             'SPEAKER 3': 'attorney Ms. Jones'},
            'turns': [{'id': n, 'speaker': f'SPEAKER {label[-1]}'} for n, (_, label, _) in enumerate(TURNS, 1)]}
PROPOSAL['turns'][10] = {'id': 11, 'speaker': 'SPEAKER 2', 'why': 'The witness interrupts with a question.'}


def words():
    result = []
    for start, label, text in TURNS:
        for k, token in enumerate(text.split()):
            result.append(Word(token, label, start + .3 * k, start + .3 * k + .25))
    return tuple(result)


def formatter(text):
    """Stand-in for the formatting model, faithful to its labels. A witness turn that
    addresses the doctor becomes flagged colloquy, as the real formatter did."""
    lines, flags, previous = [], [], None
    for line in text.split('\n'):
        label, body = line.split(': ', 1)
        unconfirmed = label.endswith(' [unconfirmed]')
        label = label.replace(' [unconfirmed]', '').upper()
        if body in COLLOQUY or label == 'SPEAKER 3' or (label == 'SPEAKER 2' and body.startswith('Doctor,')):
            if label == 'SPEAKER 2' and body.startswith('Doctor,'):
                unconfirmed = True
            out, kind = f'     {label}:  {body}', 'colloquy'
        elif label == 'SPEAKER 1':
            if previous == 'colloquy':
                lines.append('BY SPEAKER 1:')
            out, kind = f'     Q    {body}', 'q'
        else:
            out, kind = f'     A    {body}', 'a'
        if unconfirmed:
            flags.append(body)
            out += f'  [REVIEW {len(flags)}]'
        lines.append(out)
        previous = kind
    return '\n'.join(lines)


def run(tmp_path, monkeypatch, audio):
    from app.src import jobs
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    wav = tmp_path / 'deposition_3_speakers.wav'
    wav.write_bytes(b'recording')
    stitched = words()
    questions = []

    class Audio:
        def __init__(self, path, key, model):
            pass

        def __call__(self, question):
            questions.append(question)
            return {'speaker': audio, 'why': 'Same voice as the examiner.'} if audio else {'speaker': 'uncertain'}
    monkeypatch.setattr(jobs, 'AudioSpeakerCheck', Audio)

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            return Transcription(render(stitched), stitched, (), 340000, sha256(path.read_bytes()).hexdigest())

    sent = []

    class Processor:
        def __init__(self, config, model):
            pass

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            if prompt == SPEAKER_PROMPT:
                return json.dumps(PROPOSAL)
            if prompt == 'rules':
                sent.append(text)
                return formatter(text)
            return '{}'

    request = Request('doc', str(wav), 'formatter', 'transcribe', 'rules', {'gemini_api_key': 'key'},
                      original=revision(ROUGH), review_model='gemini-4-argon')
    worker = ProcessingWorker(request, TranscriptionCoordinator(), Pipeline, Processor)
    reviewed, failed = [], []
    worker.reviewed.connect(lambda *args: reviewed.append(args))
    worker.failed.connect(lambda *args: failed.append(args))
    worker.run()
    assert not failed
    _, result, warnings, _ = reviewed[0]
    return result, warnings, sent[0], questions


def editor_view(result):
    from PySide6.QtWidgets import QApplication
    from app.src.review_view import ReviewView
    QApplication.instance() or QApplication([])
    original, incoming, review = result.after_ai
    view = ReviewView()
    view.set_revisions(original, incoming, review=review)
    return view, original, incoming


def card_title(view, index):
    from PySide6.QtWidgets import QLabel
    return view.cards[index].findChildren(QLabel)[0].text()


def interrupted_line(text):
    return next(line for line in text.split('\n') if INTERRUPTED in line)


def label_suggestions(view, original, incoming):
    """Cards that replace the interrupted line's Q with another label."""
    start = original.text.index(INTERRUPTED)
    q = original.text.rfind('Q', 0, start)
    found = []
    for index, change in enumerate(view.changes):
        for a, b, c, d in change.ranges:
            if a <= q < b or (a == b == q):
                found.append((index, original.text[a:b], incoming.text[c:d]))
    return found


@pytest.mark.parametrize('audio', ['SPEAKER 1', None], ids=['audio hears the examiner', 'audio uncertain'])
def test_interrupted_question_stays_q_with_no_witness_suggestion(tmp_path, monkeypatch, audio):
    result, warnings, formatter_input, questions = run(tmp_path, monkeypatch, audio)

    # The proposal conflicted with the exchange and the rough, so the audio was asked.
    assert len(questions) == 1
    question = questions[0]
    assert (question['turn']['speaker'], question['turn']['proposed']) == ('SPEAKER 1', 'SPEAKER 2')
    assert question['before']['text'] == "The prior MRI findings and the applicant's medical history."
    assert question['after']['text'] == 'Objection, let him finish the question.'
    assert any('speaks directly to SPEAKER 2' in c for c in question['conflicts'])
    assert any("rough has MR. SMITH" in c for c in question['conflicts'])

    # The formatter receives Gemini's examiner label, never the witness.
    line = interrupted_line(formatter_input)
    assert line.startswith('Speaker 1')

    view, original, incoming = editor_view(result)
    assert interrupted_line(incoming.text).lstrip().startswith('Q    Doctor, when you reviewed the records')
    assert label_suggestions(view, original, incoming) == []
    assert not any('THE WITNESS' in incoming.text[c:d] and original.text[a:b].strip() == 'Q'
                   for change in view.changes for a, b, c, d in change.ranges)
    assert view.speaker_changes == frozenset()
    assert all(not card_title(view, i).startswith('Speaker') for i in range(len(view.cards)))
    assert not view.corrected_speaker_ranges
    view.close()

    record = result.after_ai[2]['speaker_review']
    change = record['changes'][0]
    assert (change['gemini'], change['proposed'], change['reason']) == (
        'SPEAKER 1', 'SPEAKER 2', 'The witness interrupts with a question.')
    if audio:
        assert change['status'] == 'kept' and line == 'Speaker 1: ' + INTERRUPTED
        assert 'dropped after the audio check' in result.summary
        assert not any(INTERRUPTED[:20] in w for w in warnings)
    else:
        # Still uncertain: Gemini's label stays and the turn is flagged with its time.
        assert change['status'] == 'flagged' and line == 'Speaker 1 [unconfirmed]: ' + INTERRUPTED
        warning = next(w for w in warnings if 'Doctor, when you reviewed' in w)
        assert warning.startswith('Speaker review at 0:05:24: ')
        assert 'was proposed for SPEAKER 2 (The witness interrupts with a question)' in warning
        assert 'Kept Speaker 1 for now; check the audio.' in warning


def test_without_the_checks_the_bad_proposal_reaches_the_editor(tmp_path, monkeypatch):
    """Shows the regression test can fail: with the checks off, the editor again
    offers to replace the examiner's Q with THE WITNESS."""
    monkeypatch.setattr(speaker_review, 'conflicts', lambda *args: [])
    result, _, formatter_input, questions = run(tmp_path, monkeypatch, None)
    assert not questions
    assert interrupted_line(formatter_input).startswith('Speaker 2')
    view, original, incoming = editor_view(result)
    found = label_suggestions(view, original, incoming)
    assert found and 'THE WITNESS' in found[0][2]
    assert card_title(view, found[0][0]).startswith('Speaker')
    assert view.corrected_speaker_ranges
    view.close()


def test_a_real_speaker_change_is_a_speaker_card_with_a_yellow_label_inside_green():
    """A label that truly changes speaker is classified as Speaker, shows the proposal
    and reason, and keeps its yellow label even though the edit around it is green."""
    from app.src.review_view import ReviewView
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.instance() or QApplication([])
    stitched = (Word('Doctor,', 'Speaker 1', 1.0, 1.2), Word('when', 'Speaker 1', 1.3, 1.5),
                Word('did', 'Speaker 1', 1.6, 1.8), Word('you', 'Speaker 1', 1.9, 2.0),
                Word('see', 'Speaker 1', 2.1, 2.2), Word('him?', 'Speaker 1', 2.3, 2.5),
                Word('I', 'Speaker 1', 3.0, 3.1), Word('saw', 'Speaker 1', 3.2, 3.3),
                Word('him', 'Speaker 1', 3.4, 3.5), Word('in', 'Speaker 1', 3.6, 3.7),
                Word('March.', 'Speaker 1', 3.8, 4.0), Word('Thank', 'Speaker 2', 5.0, 5.2),
                Word('you.', 'Speaker 2', 5.3, 5.5))
    answer = {'participants': {'SPEAKER 1': 'examiner', 'SPEAKER 2': 'witness'},
              'turns': [{'id': 1, 'speaker': 'SPEAKER 1', 'splits': [
                  {'at': 'I saw him in March', 'speaker': 'SPEAKER 2', 'why': 'The doctor answers.'}]},
                        {'id': 2, 'speaker': 'SPEAKER 2'}]}
    record = speaker_review.review_speakers(stitched, lambda p, q: json.dumps(answer)).record()
    original = revision('BY MR. SMITH:\n     Q    Doctor, when did you see him?  I saw him in March.\n')
    incoming = revision('BY MR. SMITH:\n     Q    Doctor, when did you see him?\n     A    I saw him in early March.\n')
    view = ReviewView()
    view.set_revisions(original, incoming, review={'speaker_review': record})
    a_label = incoming.text.index('A    I saw')
    assert view.corrected_speaker_ranges == ((a_label, a_label + 1),)
    speaker = [i for i in range(len(view.cards)) if card_title(view, i).startswith('Speaker')]
    assert speaker and view.speaker_changes == frozenset(speaker)
    note = view.cards[speaker[0]].findChild(QLabel, 'speakerReason').text()
    assert note.startswith('AI speaker review: Gemini had SPEAKER 1, proposed SPEAKER 2. The doctor answers.')
    view.close()


def test_accept_all_preview_draws_the_yellow_label_over_the_green_edit():
    from PySide6.QtGui import QColor, QFont, QTextCursor
    from PySide6.QtWidgets import QApplication
    from app.src.accept_all_preview import AcceptAllPreviewEditor
    from app.src.review_colors import ADDITION_BACKGROUND, CHECK_BACKGROUND
    QApplication.instance() or QApplication([])
    text = '     Q    Doctor, when did you see him?\n     A    I saw him in early March.'
    editor = AcceptAllPreviewEditor(QFont())
    editor.setPlainText(text)
    editor._text = text
    start = text.index('     A')
    cursor = QTextCursor(editor.document())
    cursor.setPosition(start)
    cursor.setPosition(len(text), QTextCursor.KeepAnchor)
    editor._highlights = [(start, len(text), 0, cursor)]
    label = text.index('A    I saw')
    editor.set_label_ranges([(label, label + 1)])
    editor.highlight_edit(0)
    marks = editor._review_selections
    assert [m.format.background().color().name() for m in marks] == [
        QColor(ADDITION_BACKGROUND).name(), QColor(CHECK_BACKGROUND).name()]
    yellow = marks[-1].cursor
    assert (yellow.selectionStart(), yellow.selectionEnd()) == (label, label + 1)
    editor.close()


def test_a_bare_thank_you_needs_the_audio_to_change_speaker():
    stitched = (Word('Not', 'Speaker 3', 1.0, 1.2), Word('the', 'Speaker 3', 1.3, 1.4),
                Word('supplemental', 'Speaker 3', 1.5, 1.9), Word('report?', 'Speaker 3', 2.0, 2.3),
                Word('Correct.', 'Speaker 1', 2.5, 2.8), Word('Thank', 'Speaker 2', 3.0, 3.2),
                Word('you.', 'Speaker 2', 3.3, 3.5))
    answer = {'turns': [{'id': 1, 'speaker': 'SPEAKER 3'}, {'id': 2, 'speaker': 'SPEAKER 1'},
                        {'id': 3, 'speaker': 'SPEAKER 3', 'why': 'Ms. Jones thanks counsel.'}]}
    complete = lambda payload, prompt: json.dumps(answer)
    unchecked = speaker_review.review_speakers(stitched, complete)
    last = unchecked.segments[-1]
    assert (last.status, last.speaker, last.proposed) == ('flagged', 'SPEAKER 2', 'SPEAKER 3')
    assert any('too little context' in c for c in last.checks)
    heard = speaker_review.review_speakers(stitched, complete, verify=lambda q: {'speaker': 'SPEAKER 3'})
    assert (heard.segments[-1].status, heard.segments[-1].speaker) == ('corrected', 'SPEAKER 3')
    assert re.search(r'audio check heard SPEAKER 3', ' '.join(heard.segments[-1].checks))
