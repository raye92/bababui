"""Regression: the rough check must not learn who's who from Gemini's mixed-up labels.

From a November 2026 job at 8:37. Gemini put most of the examiner's words under
SPEAKER 2, the doctor's label, and most of the doctor's under SPEAKER 1. The
speaker review gave "Okay. Let me go back to my questioning." back to the
examiner, and the reporter's rough has it as Mr. Homen's Q. The rough check
matched each rough name to the Gemini label holding most of its words, so it had
the examiner as SPEAKER 2 and called the rough a match for Gemini. The audio check
was unsure, the turn kept SPEAKER 2, and the editor offered Q -> THE WITNESS: as an
ordinary Speaker card.

The text here is made up with the same pattern; the job's own text stays out of Git.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from hashlib import sha256
import json

import pytest

from app.src.audio_pipeline import Transcription, Word, render
from app.tests.test_suggestions import revision
from shared import speaker_review
from shared.speaker_review import KEPT, PROMPT as SPEAKER_PROMPT, rough_attribution

EXAMINER, WITNESS = 'SPEAKER 1', 'SPEAKER 2'
# (start, Gemini's label, words, who spoke). Gemini has the first four turns right
# and gives every later turn to the other voice, so its fourth turn holds the
# doctor's answer and the examiner's next question.
TURNS = (
    (10.0, 'Speaker 1', 'Good morning, Doctor. My name is John Smith and I represent the applicant in this case.',
     EXAMINER),
    (16.0, 'Speaker 2', 'Good morning. I am Dr. Lee, the evaluating physician.', WITNESS),
    (20.0, 'Speaker 1', 'Doctor, you examined the applicant on March 3, correct?', EXAMINER),
    (24.0, 'Speaker 2', 'Yes, I examined her on March 3 at my office in Fresno.', WITNESS),
    (30.0, 'Speaker 2', 'Okay. And what did you find when you examined her left foot that day?', EXAMINER),
    (35.0, 'Speaker 1', 'I found tenderness over the third interspace and a positive squeeze test, which is '
                        'consistent with a neuroma.', WITNESS),
    (44.0, 'Speaker 2', 'Okay. Did you order any imaging studies to confirm that diagnosis at the time?', EXAMINER),
    (50.0, 'Speaker 1', 'I reviewed the prior MRI and x-ray reports, and I recommended an ultrasound of the '
                        'forefoot.', WITNESS),
    (58.0, 'Speaker 2', 'Okay. Let me go back to my questioning. Now, Doctor, the MRI on page 8 of your report '
                        'showed no neuroma?', EXAMINER),
    (66.0, 'Speaker 1', 'Yes, that is what the report says, but an MRI often misses a small neuroma.', WITNESS),
    (72.0, 'Speaker 2', 'Okay. Thank you, Doctor. I have no further questions.', EXAMINER),
)
ROUGH = """EXAMINATION
BY MR. SMITH:
     Q    Good morning, Doctor.  My name is John Smith, and I represent the applicant in this case.
     A    Good morning.  I am Dr. Lee, the evaluating physician.
     Q    Doctor, you examined the applicant on March 3, correct?
     A    Yes, I examined her on March 3 at my office in Fresno.
     Q    Okay.  And what did you find when you examined her left foot that day?
     A    I found tenderness over the third interspace and a positive squeeze test, which is consistent with a neuroma.
     Q    Okay.  Did you order any imaging studies to confirm that diagnosis at the time?
     A    I reviewed the prior MRI and X-ray reports, and I recommended an ultrasound of the forefoot.
     Q    Okay.  Let me go back to my questioning.  Now, Doctor, the MRI on page 8 of your report showed no neuroma?
     A    Yes, that is what the report says, but an MRI often misses a small neuroma.
     Q    Okay.  Thank you, Doctor.  I have no further questions.
"""
RESUMES = 'Okay. Let me go back to my questioning.'
WHY = {EXAMINER: 'The examiner questions the doctor.', WITNESS: 'The doctor answers the question.'}


def proposal():
    """The speaker review's answer: each Gemini turn, and each part of one, goes to
    the person who spoke it."""
    turns, previous = [], None
    for _, label, text, who in TURNS:
        if label != previous:
            entry = {'id': len(turns) + 1, 'speaker': who}
            if who != label.upper():
                entry['why'] = WHY[who]
            turns.append(entry)
        else:
            turns[-1].setdefault('splits', []).append(
                {'at': ' '.join(text.split()[:5]), 'speaker': who, 'why': WHY[who]})
        previous = label
    return {'participants': {EXAMINER: 'examining attorney Mr. Smith', WITNESS: 'witness Dr. Lee'}, 'turns': turns}


PROPOSAL = proposal()

def words():
    result = []
    for start, label, text, _ in TURNS:
        for k, token in enumerate(text.split()):
            result.append(Word(token, label, start + .3 * k, start + .3 * k + .25))
    return tuple(result)


def formatter(text):
    """Stand-in for the formatting model. SPEAKER 1 is Q and SPEAKER 2 is A, but a
    second doctor turn in a row is colloquy, as the real formatter wrote it."""
    lines, previous = ['EXAMINATION', 'BY MR. SMITH:'], None
    for line in text.split('\n'):
        label, body = line.split(': ', 1)
        label = label.replace(' [unconfirmed]', '').upper()
        if label == EXAMINER:
            lines.append(f'     Q    {body}')
        elif previous == WITNESS:
            lines.append(f'     THE WITNESS:  {body}')
        else:
            lines.append(f'     A    {body}')
        previous = label
    return '\n'.join(lines) + '\n'


def run(tmp_path, monkeypatch):
    from app.src import jobs
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    wav = tmp_path / 'job.wav'
    wav.write_bytes(b'recording')
    stitched = words()
    questions = []

    class Audio:
        """The audio check could not tell who said the turn at 8:37."""
        def __init__(self, path, key, model):
            pass

        def __call__(self, question):
            questions.append(question)
            if question['turn']['text'].startswith(RESUMES):
                return {'speaker': 'uncertain'}
            return {'speaker': question['turn']['proposed'], 'why': 'The voice matches.'}
    monkeypatch.setattr(jobs, 'AudioSpeakerCheck', Audio)

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            return Transcription(render(stitched), stitched, (), 80000, sha256(path.read_bytes()).hexdigest())

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


def resumes_line(text):
    return next(line for line in text.split('\n') if 'go back to my questioning' in line)


def witness_cards(view, original, incoming):
    """Cards that replace the resumed question's Q with another label."""
    start = original.text.index('Let me go back')
    q = original.text.rfind('Q', 0, start)
    return [index for index, change in enumerate(view.changes)
            for a, b, c, d in change.ranges if a <= q < b or a == b == q]


def test_the_rough_names_each_label_from_turns_gemini_and_the_review_agree_on():
    stitched = words()
    review = speaker_review.review_speakers(stitched, lambda payload, prompt: json.dumps(PROPOSAL))
    _, everywhere = rough_attribution(stitched, ROUGH)
    _, agreed = rough_attribution(stitched, ROUGH, review.segments)
    # Most of SPEAKER 2's words are the examiner's, so a majority over every turn swaps them.
    assert everywhere == {'THE WITNESS': EXAMINER, 'MR. SMITH': WITNESS}
    assert agreed == {'MR. SMITH': EXAMINER, 'THE WITNESS': WITNESS}
    assert {s.speaker for s in review.segments if s.status == KEPT} == {EXAMINER, WITNESS}


def test_the_resumed_question_goes_to_the_examiner_and_stays_q(tmp_path, monkeypatch):
    result, warnings, formatter_input, questions = run(tmp_path, monkeypatch)

    # The rough agrees with every fix, so none needs the audio.
    assert questions == []
    assert resumes_line(formatter_input).startswith('Speaker 1: ' + RESUMES)
    record = result.after_ai[2]['speaker_review']
    change = next(c for c in record['changes'] if c['text'].startswith('Okay. Let me'))
    assert (change['gemini'], change['speaker'], change['status']) == (WITNESS, EXAMINER, 'corrected')
    assert change['checks'] == ["the reporter's rough agrees (MR. SMITH)"]
    assert not record['flags']
    assert not any('go back' in w for w in warnings)

    view, original, incoming = editor_view(result)
    assert resumes_line(incoming.text).lstrip().startswith('Q    ' + RESUMES)
    assert witness_cards(view, original, incoming) == []
    view.close()


def test_with_the_old_rough_labels_the_turn_is_flagged_and_its_card_needs_review(tmp_path, monkeypatch):
    """Shows the test can fail: learning labels from every turn brings back the bad
    check. The unsettled turn's card is then marked Needs review, and Accept All asks."""
    from PySide6.QtWidgets import QLabel
    from app.src.suggestion_filter import flagged_attributions
    learn_from_all = rough_attribution
    monkeypatch.setattr(speaker_review, 'rough_attribution', lambda w, r, segments=None: learn_from_all(w, r))
    result, warnings, formatter_input, questions = run(tmp_path, monkeypatch)

    resumed = next(q for q in questions if q['turn']['text'].startswith(RESUMES))
    assert "the reporter's rough has MR. SMITH, which matches Gemini" in resumed['conflicts']
    assert resumes_line(formatter_input).startswith('Speaker 2 [unconfirmed]: ' + RESUMES)
    assert any('Kept Speaker 2 for now; check the audio.' in w for w in warnings)

    view, original, incoming = editor_view(result)
    assert resumes_line(incoming.text).lstrip().startswith('THE WITNESS:  ' + RESUMES)
    found = witness_cards(view, original, incoming)
    assert len(found) == 1
    index = found[0]
    assert card_title(view, index) == 'Speaker attribution · Needs review'
    assert index in view.needs_review
    note = view.cards[index].findChild(QLabel, 'speakerFlag').text()
    assert note.startswith('AI speaker review: “Okay. Let me go back to ...” was proposed for SPEAKER 1 '
                           '(The examiner questions the doctor), but ')
    assert note.endswith('and the audio check was uncertain. Check the audio.')
    view.close()

    review = result.after_ai[2]
    ranges = [r for change in view.changes for r in change.ranges]
    assert flagged_attributions(review, ranges) == 0
    assert flagged_attributions(review, ranges, incoming.text) == 1
    assert flagged_attributions(review, [], incoming.text) == 0


@pytest.mark.parametrize('flags', [None, []])
def test_a_review_without_flags_marks_no_card(flags):
    from shared.speaker_review import label_flags
    record = {'tokens': ['okay'], 'flags': flags}
    assert label_flags(record, '     Q    Okay.\n') == ()
    assert label_flags(None, '     Q    Okay.\n') == ()
