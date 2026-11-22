"""One decision per uncertain identity, and label-only speaker assignments."""
from dataclasses import replace
from types import SimpleNamespace

from app.src.audio_pipeline import Word
from app.src.jobs import ProcessingWorker
from app.src.speaker_identity import link_voices
from app.src.speaker_questions import TURN, VOICE, questions
from app.src.suggestion_filter import assign_speaker, begin_review
from app.src.suggestions import suggestions
from app.tests.test_suggestions import revision
from shared.speaker_review import review_speakers

TURNS = [('Speaker 1', 10, 'Good morning, Doctor.'),
         ('Speaker 1', 14, 'Please state your name for the record.'),
         ('Speaker 1', 20, 'Doctor, did you review the operative report from March?'),
         ('Speaker 2', 26, 'Yes, I reviewed it before I wrote my report.'),
         ('Speaker 6', 2000, 'Thank you, Doctor, I have nothing further at this time.'),
         ('Speaker 2', 2006, 'Thank you.'),
         ('Speaker 6', 2010, 'Counsel, do you have any questions?'),
         ('Speaker 2', 2016, 'I am done.'),
         ('Speaker 6', 2020, 'Let us go off the record.'),    # the reporter, under the same Gemini number
         ('Speaker 2', 2026, 'Sure.'),
         ('Speaker 6', 2030, 'Okay.')]
DRAFT = '\n'.join([
    '     SPEAKER 1:  Good morning, Doctor.',
    '     SPEAKER 1:  Please state your name for the record.',
    'EXAMINATION',
    'BY SPEAKER 1:',
    '     Q    Doctor, did you review the operative report from March?',
    '     A    Yes, I reviewed it before I wrote my report.',
    '     SPEAKER 6:  Thank you, Doctor, I have nothing further at this time.',
    '     SPEAKER 2:  Thank you.',
    '     SPEAKER 6:  Counsel, do you have any questions?',
    '     SPEAKER 2:  I am done.',
    '     SPEAKER 6:  Let us go off the record.',
    '     SPEAKER 2:  Sure.',
    '     SPEAKER 6:  Okay.'])
ROUGH = '\n'.join([
    '     MR. RAMIREZ:  Good morning, Doctor.',
    '     MR. RAMIREZ:  Please state your name for the record.',
    'EXAMINATION',
    'BY MR. RAMIREZ:',
    '     Q    Doctor, did you review the operative report from March?',
    '     A    Yes, I reviewed it before I wrote my report.',
    '     MR. SWEET:  Nothing further.',
    '     THE WITNESS:  Thank you.',
    '     MR. SWEET:  Over to you.',
    '     THE WITNESS:  I am done.',
    '     THE REPORTER:  We are going off.',
    '     THE WITNESS:  Sure.',
    '     MR. SWEET:  Okay, sure.'])


def stitched():
    words = []
    for speaker, start, text in TURNS:
        words += [Word(t, speaker, start + i * .4, start + i * .4 + .3) for i, t in enumerate(text.split())]
    return words


def heard(start):
    return {2010: 'Speaker 6', 2020: 'none', 2030: 'uncertain'}.get(int(start), 'uncertain')


def review_state():
    """The pipeline's record for the job, then the editor's review of the draft against the rough."""
    identities = {'Speaker 1': {'chunk': 1, 'status': 'first chunk'},
                  'Speaker 2': {'chunk': 1, 'status': 'first chunk'},
                  'Speaker 6': {'chunk': 2, 'status': 'provisional', 'suggested': None, 'evidence': ''}}
    compare = lambda q: ({'matches': {c['id']: heard(c['start']) for c in q['candidates']}}
                         if q['references'][0]['label'] == 'Speaker 6' else
                         {'matches': {c['id']: 'uncertain' for c in q['candidates']}})
    words, identities, _ = link_voices(stitched(), identities, compare)
    keep = lambda payload, prompt: '{"turns": []}'
    result = review_speakers(words, keep, identities=identities)
    result = replace(result, voices=ProcessingWorker._voices(result, compare, lambda m: None, None))
    state = SimpleNamespace(original=revision(ROUGH))
    begin_review(state, DRAFT)
    state.review['speaker_review'] = result.record()
    return state


def test_turns_linked_by_voice_are_one_decision_and_others_stay_separate():
    state = review_state()
    asked, resolved = questions(state.review, state.incoming.text)
    assert resolved == {'SPEAKER 1': 'MR. RAMIREZ', 'SPEAKER 2': 'THE WITNESS'}
    voice, *turns = asked
    assert voice.kind == VOICE and voice.speaker == 'SPEAKER 6' and voice.turns == 2
    assert voice.text == 'Thank you, Doctor, I have nothing further at this time.' and voice.time == 2000
    # The rough's aligned "Okay." suggests a name; the voice check alone never does.
    assert voice.suggestion == 'MR. SWEET'
    assert [(q.kind, q.text) for q in turns] == [(TURN, 'Let us go off the record.'), (TURN, 'Okay.')]


def test_without_a_voice_check_a_shared_number_does_not_group_turns():
    state = review_state()
    record = state.review['speaker_review']
    record['voices'] = []
    asked, _ = questions(state.review, state.incoming.text)
    assert [q.kind for q in asked] == [TURN] * 4


def pending(state):
    return [(state.original.text[a:b], state.incoming.text[c:d])
            for change in suggestions(state.original, state.incoming) for a, b, c, d in change.ranges]


def test_assigning_a_voice_changes_only_the_labels_and_keeps_wording_pending():
    state = review_state()
    voice = questions(state.review, state.incoming.text)[0][0]
    before = pending(state)
    assert before[:3] == [('MR. SWEET', 'SPEAKER 6'), ('N', 'Thank you, Doctor, I have n'), ('', ' at this time')]
    assign_speaker(state, 'MR. SWEET', voice.locations, times=[(2000, 2003), (2010, 2012)])
    assert state.incoming.text.count('MR. SWEET:') == 2 and state.incoming.text.count('SPEAKER 6:') == 2
    # Only the two label decisions are gone. Every wording change, even on the same line, remains.
    assert pending(state) == [p for k, p in enumerate(before) if k not in (0, 3)]
    assert state.review['assignments'] == [{'name': 'MR. SWEET', 'times': [[2000, 2003], [2010, 2012]]}]
    asked, _ = questions(state.review, state.incoming.text)
    assert [q.text for q in asked] == ['Let us go off the record.', 'Okay.']


def test_assigning_one_turn_accepts_its_label_into_the_rough_only():
    state = review_state()
    reporter = questions(state.review, state.incoming.text)[0][1]
    rough_before = state.original.text
    assign_speaker(state, 'THE REPORTER', reporter.locations)
    # The rough already says THE REPORTER there: nothing else in it changed.
    assert state.original.text == rough_before
    okay = questions(state.review, state.incoming.text)[0][-1]
    assign_speaker(state, 'MR. RAMIREZ', okay.locations)
    # The rough's label for "Okay." is now MR. RAMIREZ; its wording "Okay, sure." is still a pending suggestion.
    assert '     MR. RAMIREZ:  Okay, sure.' in state.original.text
    after = [(state.original.text[a:b], state.incoming.text[c:d])
             for change in suggestions(state.original, state.incoming) for a, b, c, d in change.ranges]
    assert any('sure' in x for x, _ in after)


def test_who_spoke_decides_whether_an_assigned_turn_shows_as_q_a_or_colloquy():
    rough = ('     MR. SWEET:  Objection.\n     THE WITNESS:  Sorry.\nBY MR. RAMIREZ:\n'
             '     Q    Did you see him?\n     A    Yes.\n     Q    Okay.\n     A    Next.')
    draft = rough.replace('     Q    Okay.', '     A    Okay.')
    for name, expected in (('MR. RAMIREZ', '     Q    Okay.'), ('THE WITNESS', '     A    Okay.'),
                           ('MR. SWEET', '     MR. SWEET:  Okay.')):
        state = SimpleNamespace(original=revision(rough), incoming=revision(draft), review={'locations': []})
        label = draft.index('A    Okay.')
        assign_speaker(state, name, spans=[(label, label + 1)], answered=['flag:1'])
        assert expected in state.incoming.text
        assert state.review['answered'] == ['flag:1']
        # The label decision is accepted into the rough; nothing else changes there.
        assert state.original.text == rough.replace('     Q    Okay.', expected)


QUESTIONING = ('     MS. JONES:  Objection.\nBY MR. HOMEN:\n     Q    Could that have created the neuroma?\n'
               '     A    Wait.  Write it out and justify your questions.\n     Q    Thank you, Doctor.\n'
               '     A    What entry are you saying was a fracture?\n     MR. HOMEN:  Let us go off the record.\n'
               '     THE WITNESS:  Sure.\n')


def unsettled(draft, line):
    """The draft with one turn under THE WITNESS:, and that label's location."""
    start = draft.index(line)
    label = draft.rindex('THE WITNESS', 0, start)
    location = {'id': 1, 'speaker': 'SPEAKER 2', 'start': label, 'end': label + len('THE WITNESS'),
                'resolved': False}
    return draft, location


def test_a_colloquy_label_given_to_the_examiner_while_he_questions_becomes_q():
    """From a November 2026 job at 12:23: the turn showed as THE WITNESS:, and giving it to
    the examiner made it MR. HOMEN: colloquy, where the rough has his Q."""
    draft, location = unsettled(QUESTIONING.replace('     Q    Thank you, Doctor.',
                                                    '     THE WITNESS:  Sure.  Thank you, Doctor.'), 'Sure.  Thank')
    for ids, spans in (((1,), ()), ((), ((location['start'], location['end']),))):
        state = SimpleNamespace(original=revision(QUESTIONING), incoming=revision(draft),
                                review={'locations': [dict(location)]})
        assign_speaker(state, 'MR. HOMEN', ids, spans)
        assert '     A    Wait.  Write it out and justify your questions.\n     Q    Sure.  Thank you, Doctor.\n' \
            in state.incoming.text
        # The rough already has his Q: only "Sure." is left to review.
        assert state.original.text == QUESTIONING
        changed = [(state.original.text[a:b], state.incoming.text[c:d])
                   for change in suggestions(state.original, state.incoming) for a, b, c, d in change.ranges]
        assert changed == [('', 'Sure.  ')]
        if ids:
            q = state.incoming.text.index('Q    Sure.')
            assert (state.review['locations'][0]['start'], state.review['locations'][0]['end']) == (q, q + 1)
            assert state.review['locations'][0]['resolved']


def test_the_rough_keeps_colloquy_and_turns_outside_questioning_stay_colloquy():
    # The rough has the examiner's own colloquy here, so it stays colloquy under his name.
    draft, location = unsettled(QUESTIONING.replace('     MR. HOMEN:  Let us go off', '     THE WITNESS:  Let us go off'),
                                'Let us go off')
    state = SimpleNamespace(original=revision(QUESTIONING), incoming=revision(draft), review={'locations': [location]})
    assign_speaker(state, 'MR. HOMEN', (1,))
    assert state.incoming.text == QUESTIONING
    # Before any BY line, the examiner's turn is colloquy, whatever the rough says.
    rough = '     MR. HOMEN:  Good morning.\n     THE WITNESS:  Good morning.\nBY MR. HOMEN:\n     Q    Ready?\n'
    draft, location = unsettled(rough.replace('     MR. HOMEN:  Good', '     THE WITNESS:  Good', 1), 'Good morning.')
    state = SimpleNamespace(original=revision(rough), incoming=revision(draft), review={'locations': [location]})
    assign_speaker(state, 'MR. HOMEN', (1,))
    assert state.incoming.text == rough
