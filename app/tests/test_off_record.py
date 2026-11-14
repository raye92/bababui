from types import SimpleNamespace

import pytest

from app.src.casecat.anchors import AnchoredSpan, Revision
from app.src.suggestion_filter import begin_review, auto_accept
from app.src.suggestions import suggestions, resolve


DEPARTURE = 'MR. LEISER: Can we go off real quick.\nMS. SIEMENS: Sure.\n'
NOTE = '(A discussion was held off the record.)\nBY MS. SIEMENS:\n'
RETURN = 'I would like to move to your March 27, 2026, report.'
NEXT = 'On page 3 you state you would be willing to discuss the issue with Mr. Davis as it pertains to his inability to work correct?'
LATER = "Yes, you know, I mean everybody's individually going to find them as they kind of thing."
ORIGINAL = DEPARTURE + NOTE + 'Q ' + RETURN + ' ' + NEXT + '\nA Correct.\nQ What caused the injury to his spine?\nA ' + LATER + " I don't know if he had a preexisting fragility associated with his spine.\n"
INCOMING = ('MS. SIEMENS: Hey, Chris, can we go off real quick, off the record real quick?\n'
            'SPEAKER 9: Do you want to stop the deposition and review the transcripts?\n'
            "Q I'd like to move to your March 27, 2026, report.\nA Let me get there.\n"
            'Q Okay. ' + NEXT + '\nA Correct.\nQ What caused the injury to his spine?\nA ' + LATER + " I don't know if he had a preexisting fragility associated with his spine.\n")


def state_for(text=ORIGINAL):
    original = Revision((AnchoredSpan('root', (), (), text),))
    return SimpleNamespace(original=original, incoming=original, review=None)


def test_excludes_discussion_and_bounds_resumed_testimony_edits():
    state = state_for()
    begin_review(state, INCOMING)
    auto_accept(state)
    assert 'review the transcripts' not in state.incoming.text
    assert state.incoming.text.startswith(DEPARTURE + NOTE)
    assert "I'd like to move" in state.incoming.text
    assert 'Let me get there' in state.incoming.text
    assert 'SPEAKER 9' not in state.review['evidence']['speakers']
    assert LATER in state.incoming.text
    changes = suggestions(state.original, state.incoming)
    assert changes
    start = state.original.text.index('Q ' + RETURN)
    later = state.original.text.index('Q What caused')
    assert all(start <= a <= b <= later for c in changes for a, b, _, _ in c.ranges)
    assert any('would' in state.original.text[a:b] for c in changes for a,b,_,_ in c.ranges)
    for accept in (True, False):
        old, new = state.original, state.incoming
        for _ in range(30):
            pending = suggestions(old, new)
            if not pending:
                break
            old, new = resolve(old, new, pending[0], accept)
        assert not suggestions(old, new)
        assert LATER in old.text


@pytest.mark.parametrize('incoming', [
    INCOMING.replace('March 27', 'March 28'),
    INCOMING.replace("I'd like", "I'd not like"),
    INCOMING.replace("Q I'd like to move to your March 27, 2026, report.\n", ''),
    INCOMING.replace(NEXT, 'A completely different question follows this discussion.'),
    INCOMING + INCOMING,
    INCOMING.replace('Hey, Chris, ', 'He died. '),
    INCOMING.replace('Hey, Chris, ', 'She was injured. '),
    INCOMING.replace('can we go', 'we cannot go'),
    INCOMING.replace('can we go', "we can't go"),
    INCOMING.replace('can we go', 'we can not go'),
    DEPARTURE.replace('Can we', 'We cannot') + 'Q We refused to review the transcripts.\n' + INCOMING[INCOMING.index("Q I'd like"):],
])
def test_ambiguous_or_conflicting_boundaries_do_not_exclude(incoming):
    state = state_for()
    begin_review(state, incoming)
    assert 'review the transcripts' in state.incoming.text
    assert not state.review.get('off_record_changes')


def test_spoken_request_without_original_notation_does_not_exclude():
    state = state_for(ORIGINAL.replace(NOTE, ''))
    begin_review(state, INCOMING)
    assert 'review the transcripts' in state.incoming.text


def test_multiple_intervals_are_handled_in_order():
    state = state_for(ORIGINAL + ORIGINAL.replace('March 27', 'April 19').replace('real quick', 'for a moment'))
    begin_review(state, INCOMING + INCOMING.replace('March 27', 'April 19').replace('real quick', 'for a moment'))
    assert 'review the transcripts' not in state.incoming.text
    assert state.incoming.text.count(NOTE) == 2
    assert len(state.review['off_record_changes']) == 2


def test_relocated_later_sentence_stays_separate_from_departure():
    state = state_for()
    incoming = INCOMING.replace('A ' + LATER + ' ', 'A ').replace("Q I'd like", 'A ' + LATER + '\nQ Sure.\nQ I\'d like')
    begin_review(state, incoming)
    assert state.incoming.text.startswith(DEPARTURE + NOTE)
    changes = suggestions(state.original, state.incoming)
    later = state.original.text.index(LATER)
    assert any(a <= later < b for change in changes for a,b,_,_ in change.ranges)
    assert all(a >= len(DEPARTURE + NOTE) for change in changes for a,_,_,_ in change.ranges)


def test_case_punctuation_and_small_wording_differences_are_matching_only():
    state = state_for()
    incoming = INCOMING.replace("I'd like to move to your March 27, 2026, report.",
                                'ID LIKE TO MOVE TO THE MARCH 27 2026 REPORT!')
    begin_review(state, incoming)
    assert 'review the transcripts' not in state.incoming.text
    assert 'ID LIKE TO MOVE TO THE MARCH 27 2026 REPORT!' in state.incoming.text


def test_undo_snapshot_restores_discussion_and_raw_speaker_locations():
    state = state_for()
    before = begin_review(state, INCOMING)
    auto_accept(state)
    assert state.review['automatic_changes'][0]['rule'] == 'off-record discussion'
    assert 'review the transcripts' in state.review['off_record_changes'][0]['before']
    state.original, state.incoming, state.review = before
    assert 'review the transcripts' in state.incoming.text
    assert 'SPEAKER 9' in state.review['evidence']['speakers']
    for loc in state.review['locations']:
        assert state.incoming.text[loc['start']:loc['end']] == loc['speaker']
    assert auto_accept(state) == []
    assert 'review the transcripts' in state.incoming.text


def test_later_exact_return_cannot_override_earlier_contracted_return():
    state = state_for()
    incoming = INCOMING + 'Q ' + RETURN + '\nQ ' + NEXT + '\nA Correct.\n'
    begin_review(state, incoming)
    assert 'review the transcripts' in state.incoming.text
    assert LATER in state.incoming.text
    assert not state.review.get('off_record_changes')
