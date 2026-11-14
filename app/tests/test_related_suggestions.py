"""Related visual sections preserve independent native review decisions."""
import pytest

from app.tests.test_suggestions import revision
from app.src.suggestions import suggestions, resolve
from app.src.suggestion_filter import automatic_reason


DEPOSITION = 'Have you had your deposition taken previously?'
MEDICAL = 'I did not see them in your medical records review.'
REPORT = 'I would like to move to your March 27, 2026, report'
INJURY = "So, this is an accepted injury. In your opinion, hypothetically, can a patient be anything less than permanently and totally disabled if they're not working?"
REVIEW = 'I would like you to review the deposition transcripts hopefully I can get the older one and I would like to schedule a reevaluation is that all right with you Dr. W?'
EVERYBODY = "Yes, you know, I mean everybody's individually going to find them as they kind of thing."
INTRO = 'Good morning, Dr. Walth. My name is Kristin Siemens, and I am the defense attorney in the matter of Mark Davis versus Labor Ready.'
CHRONOLOGY = 'You have everything nicely listed chronologically. And the last record reviewed on page 14 is September 11th of 2024; so that would be prior to the deposition that I took.'
SPINE = "I don't know if he had a preexisting fragility associated with his spine. A five-gallon bucket of paint is pretty heavy, right? I don't even know what this weighs, sixty pounds, seventy pounds. Again, lifting and twisting could translate all the way up into the shoulder and the cervical spine, thoracic spine."
READ = "I would like to discuss with Mr. Davis at the reevaluation whether living in Colorado Springs is quite different than living in the Central Valley of California, and how that might affect industrial and nonindustrial medical factors, as well as the three-day trip that he took to move from California to Colorado and how that affected him. It's stated in his deposition transcript, and you can read that."
IMPAIRMENT = 'So there are circumstances in which a patient is not working and has permanent impairment on a work-related basis, but the impairment is less than permanent and total?'

EXAMPLES = [
    ('Q ' + INTRO + ' ' + DEPOSITION + '  \nA I have.\n',
     'Q ' + INTRO.replace('Kristin', 'Kristen') + ' \n          ' + DEPOSITION + '\nA I have.\n'),
    ('Q ' + MEDICAL + '\nA Okay.\nQ ' + CHRONOLOGY + '\n',
     'Q Okay. ' + MEDICAL + ' ' + CHRONOLOGY + '\n'),
    ('Q ' + REPORT + '. On page 3 you state you would discuss this issue.\n',
     "Q I'd like to move to your March 27, 2026 report.\nA Let me get there.\nQ See to you. Let me get there.\nA Okay. I'm there.\nQ Okay. On page 3 you state you would discuss this issue.\n"),
    ('A ' + EVERYBODY + '  ' + SPINE + '\n',
     "A Yeah, you know, that's -- I mean, everybody's individually going to find them, you know, as they are kind of thing.\nQ Sure.\nA " + SPINE + '\n'),
    ('Q ' + READ + '  ' + INJURY + ' \nA Yes.\n',
     'Q ' + READ + ' \n          ' + INJURY.replace('So,', 'So').replace("they're", 'they are') + '\nA Yes.\n'),
    ('Q ' + IMPAIRMENT + '\nA Correct.\nQ ' + REVIEW + '\nA Absolutely.\n',
     'Q ' + IMPAIRMENT[:-1] + ". I would like you to review the deposition transcripts, hopefully I can get the older one. And I'd like to schedule a re-evaluation; is that all right with you, Dr. Wolf?\nA Absolutely.\n"),
    ('THE WITNESS: I would like to review it as part of the upcoming reevaluation.\n',
     'MR. LEISER: Oh, I would like to review.\nMS. SIEMENS: Certainly.\nMR. LEISER: As part of the upcoming reevaluation.\n'),
]


@pytest.mark.parametrize('before,after', EXAMPLES[1:4] + EXAMPLES[6:],
                         ids=['medical-review', 'report', 'everybody', 'review-request'])
@pytest.mark.parametrize('accept', [True, False], ids=['accept', 'reject'])
def test_related_edits_share_context_without_merging_decisions(before, after, accept):
    from app.src.review_model import build_review
    old = revision(before)
    new = old.revise(after)
    changes = suggestions(old, new)
    assert len(changes) > 1 and all(len(change.ranges) == 1 for change in changes)
    section, = build_review(old, new).sections
    assert section.edit_indices == tuple(range(len(changes)))
    kept, pending = old, new
    for _ in range(50):
        changes = suggestions(kept, pending)
        if not changes:
            break
        kept, pending = resolve(kept, pending, changes[0], accept)
    assert kept.text == pending.text == (after if accept else before)
    assert not suggestions(kept, pending)


def test_unrelated_wording_remains_independent_of_paragraph_move():
    before, after = EXAMPLES[0]
    old = revision(before)
    new = old.revise(after.replace('Kristin', 'Kristen'))
    changes = suggestions(old, new)
    structural, = [c for c in changes if c.kind == 'structure']
    assert all(c.kind != 'group' for c in changes)
    kept, pending = resolve(old, new, structural, True)
    assert kept.text == before.replace(' Have you', ' \n          Have you')
    assert 'Kristen' in pending.text
    assert all(c.kind == 'text' for c in suggestions(kept, pending))


@pytest.mark.parametrize('bridge', [
    'Q Did you read a different report?\nA Yes.\n',
    '(A discussion was held off the record.)\n',
])
def test_related_words_across_unrelated_testimony_or_off_record_note_stay_separate(bridge):
    before = 'Q Intro. ' + DEPOSITION + '\n' + bridge + 'A I have.\n'
    after = 'Q Intro.\n' + bridge + 'Q ' + DEPOSITION + '\nA I have.\n'
    changes = suggestions(revision(before), revision(after))
    assert len(changes) >= 2
    assert all(len(c.ranges) == 1 for c in changes)


def test_short_repeated_answers_do_not_link_independent_edits():
    before = 'Q Intro. Okay.\nA Yes.\n'
    after = 'Q Intro.\nQ Okay.\nA Yes.\n'
    changes = suggestions(revision(before), revision(after))
    assert changes
    assert all(len(c.ranges) == 1 for c in changes)


def test_competing_insertions_are_not_paired_by_position_alone():
    from app.src.suggestions import Suggestion
    from app.src.related_suggestions import related_groups
    phrase = DEPOSITION + '\n'
    old, new = revision(phrase), revision(phrase * 2)
    changes = [Suggestion(old, new, (span,)) for span in (
        (0, len(phrase), 0, 0),
        (len(phrase), len(phrase), 0, len(phrase)),
        (len(phrase), len(phrase), len(phrase), len(phrase)*2),
    )]
    assert related_groups(old, new, changes) == ((0,), (1,), (2,))


def test_conclusion_move_does_not_absorb_intervening_dialogue_change():
    before = ('MS. SIEMENS: Certainly. Then we are concluding at 10:19 a.m.\n'
              'Mr. Bui, do you have any questions.\n'
              'MS. SIEMENS: Dr. Walth, would you like to review this transcript or waive signature?\n')
    after = ('MS. SIEMENS: Certainly.\nMR. LEISER: Our re-evaluation report, excuse me.\n'
             'MS. SIEMENS: Yes, certainly. Okay. Then we are concluded at 10:19 A.M. '
             'Dr. Walth, would you like to review this transcript or waive signature?\n')
    changes = suggestions(revision(before), revision(after))
    assert len(changes) >= 3
    assert all(c.kind != 'group' for c in changes)


def test_long_mixed_insertion_is_not_grouped_with_one_matching_question():
    from app.src.suggestions import Suggestion
    from app.src.related_suggestions import related_groups
    old = revision('A \nQ ' + REVIEW + '\n')
    new = revision('Q ' + REVIEW + '\n' + 'A Additional testimony about unrelated issues.\n' * 8)
    changes = [Suggestion(old, new, (span,), 'structure') for span in (
        (0, 2, 0, len(new.text)), (3, len(old.text), len(new.text), len(new.text)),
    )]
    assert related_groups(old, new, changes) == ((0,), (1,))


def test_related_visual_section_contains_one_before_after_passage():
    from app.src.review_model import build_review
    before, after = EXAMPLES[1]
    section, = build_review(revision(before), revision(after)).sections
    rendered_before = before[slice(*section.original_range)]
    rendered_after = after[slice(*section.incoming_range)]
    assert rendered_before == before
    assert rendered_after == after
    assert rendered_before.count(MEDICAL) == rendered_after.count(MEDICAL) == 1


def test_accepting_related_edits_keeps_unchanged_audio_anchors():
    from app.src.casecat.anchors import AnchoredSpan, Revision
    before, after = EXAMPLES[1]
    offset = before.index('Q You have')
    old = Revision((
        AnchoredSpan('departure', (0,), ('00:01',), before[:offset]),
        AnchoredSpan('label', (1,), ('00:02',), 'Q'),
        AnchoredSpan('testimony', (2,), ('00:03',), before[offset+1:]),
    ))
    new = old.revise(after)
    accepted, pending = old, new
    for _ in range(20):
        changes = suggestions(accepted, pending)
        if not changes:
            break
        accepted, pending = resolve(accepted, pending, changes[0], True)
    assert accepted.text == after
    # The joined-away Q label is deleted. Surviving testimony retains its
    # exact native association instead of inheriting a broad replacement span.
    assert old.spans[1] not in accepted.spans
    assert old.spans[2] in accepted.spans
