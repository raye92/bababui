"""Review decisions share exact source ranges independently of visual sections."""

import pytest

from app.src.suggestion_filter import _paragraphs
from app.src.suggestions import _paragraph_ops, suggestions, resolve, propose
from app.tests.test_suggestions import revision


def sample_transcript():
    before = '\n'.join([
        '     Q    Were the packages delivered on Monday?',
        '     A    They arrived on Tuesday.',
        '     Q    Please describe the inspection of the loading dock.',
        '     A    The supervisor checked each pallet before signing the receipt.',
        '     Q    Was the replacement valve tested on March 12?',
        '     A    Yes.',
        '     Q    What happened afterward?',
        '     A    The crew returned the tools.',
    ])
    after = '\n'.join([
        '     Q    Were the packages delivered on Tuesday?',
        '     A    They arrived on Tuesday.',
        '     Q    Was the invoice available?',
        '     A    Yes.',
        '     Q    Please describe the inspection of the loading dock.',
        '     A    The supervisor checked each pallet before signing the receipt.',
        '     Q    Was the replacement valve tested on March 14?',
        '     A    Yes.',
        '     Q    All right.',
        '     Q    What happened afterward?',
        '     A    The crew returned the tools.',
    ])
    return before, after


def test_surviving_question_and_answer_follow_their_actual_counterparts():
    before, after = sample_transcript()
    old = [p[3] for p in _paragraphs(before, byline_context=False)]
    new = [p[3] for p in _paragraphs(after, byline_context=False)]
    pairs = {(a, c) for _, a, b, c, d in _paragraph_ops(old, new) if b-a == d-c == 1}
    assert (0, 0) in pairs  # The delivery-day correction.
    assert (4, 6) in pairs  # The surviving valve-test question.
    assert (5, 7) in pairs  # Its Yes., before the inserted short question.


@pytest.mark.parametrize('accept', [False, True])
def test_opening_rewrite_is_one_paired_character_edit_independent_of_name(accept):
    old = revision("You're scheduled to meet with Elena Baker?")
    new = revision("Okay. And you're scheduled to meet with Elena Bailey?")
    changes = suggestions(old, new)
    assert [(old.text[a:b], new.text[c:d]) for s in changes for a,b,c,d in s.ranges] == [
        ('Y', 'Okay. And y'), ('Baker', 'Bailey')]
    kept, pending = resolve(old, new, changes[0], accept)
    assert 'Baker' in kept.text and 'Bailey' in pending.text
    remaining, = suggestions(kept, pending)
    a,b,c,d = remaining.ranges[0]
    assert (kept.text[a:b], pending.text[c:d]) == ('Baker', 'Bailey')


def test_one_visual_section_can_contain_independent_decisions():
    from app.src.review_model import build_review
    old = revision('Q The car was red and large.\nA Yes.\n')
    new = revision('Q The car was blue and small.\nA Yes.\n')
    model = build_review(old, new)
    assert model.original is old and model.incoming is new
    assert len(model.edits) == 2
    assert len(model.sections) == 1
    section, = model.sections
    assert section.edit_indices == (0, 1)
    assert old.text[slice(*section.original_range)] == 'Q The car was red and large.\n'
    assert new.text[slice(*section.incoming_range)] == 'Q The car was blue and small.\n'


def test_model_preserves_identical_gaps_and_exact_source_coverage():
    from app.src.review_model import build_review
    old, new = map(revision, sample_transcript())
    model = build_review(old, new)
    a = c = 0
    for x,y,z,w in sorted(span for edit in model.edits for span in edit.ranges):
        assert x >= a and z >= c
        assert old.text[a:x] == new.text[c:z]
        a,c = y,w
    assert old.text[a:] == new.text[c:]
    assert set(range(len(model.edits))) == {i for section in model.sections for i in section.edit_indices}
    assert not any('Please describe the inspection of the loading dock' in old.text[a:b] and c == d
                   for edit in model.edits for a,b,c,d in edit.ranges)


def test_linked_field_has_one_decision_and_multiple_visual_occurrences():
    from app.src.review_model import build_review
    old = revision('').insert_field(0, 'NAME', 'Jane')
    old = old.replace(len(old.text), len(old.text), ': First.\nOther text.\n')
    old = old.insert_field(len(old.text), 'NAME', 'Jane')
    old = old.replace(len(old.text), len(old.text), ': Last.\n')
    model = build_review(old, old.set_field('NAME', 'Joan'))
    assert len(model.edits) == 1 and len(model.edits[0].ranges) == 2
    assert len(model.sections) == 2
    assert all(section.edit_indices == (0,) for section in model.sections)


@pytest.mark.parametrize('prepare', [propose, lambda original, text: original.revise(text)])
def test_proposal_preserves_unchanged_native_spans_in_surviving_question(prepare):
    from app.src.casecat.anchors import AnchoredSpan, Revision
    before, after = sample_transcript()
    start = before.index('The supervisor checked each pallet')
    end = before.index('     Q    Was the replacement valve', start)
    retained = AnchoredSpan('question', (7,), ('00:07',), before[start:end])
    old = Revision((AnchoredSpan('before', (0,), (), before[:start]), retained,
                    AnchoredSpan('after', (8,), (), before[end:])))
    new = prepare(old, after)
    assert retained in new.spans


def test_large_repeated_changed_gap_preserves_order_and_coverage():
    left = ['Repeated earlier testimony about the same report.'] * 120
    right = ['Repeated later testimony about the same report.'] * 120
    right.insert(60, 'An entirely additional question.')
    ops = _paragraph_ops(left, right)
    a = c = 0
    for _, start, end, ns, ne in ops:
        assert (start, ns) == (a, c)
        a, c = end, ne
    assert (a, c) == (len(left), len(right))


def test_repeated_unchanged_context_retains_only_first_change():
    left = ['The same unchanged repeated paragraph.'] * 80
    right = left.copy()
    right[0] = 'The same corrected repeated paragraph.'
    ops = _paragraph_ops(left, right)
    assert [op for op in ops if op[0] != 'equal'] == [('replace', 0, 1, 0, 1)]


def test_plain_paragraph_splits_preserve_each_unchanged_audio_span():
    from app.src.casecat.anchors import AnchoredSpan, Revision
    old = Revision((AnchoredSpan('alpha', (0,), ('00:01',), 'Alpha '),
                    AnchoredSpan('beta', (1,), ('00:02',), 'beta '),
                    AnchoredSpan('gamma', (2,), ('00:03',), 'gamma.')))
    new = old.revise('Alpha \nbeta \ngamma.')
    assert all(span in new.spans for span in old.spans)


@pytest.mark.parametrize('before,after', [
    ('First.\nSecond.', 'First.\n\nSecond.'),
    ('Gone.\nKept.', 'Kept.'),
    ('Q Test.\nA Yes.', 'BY MR. COUNSEL:\nQ Test.\nA Yes.'),
])
def test_visual_section_boundaries_leave_identical_common_gaps(before, after):
    from app.src.review_model import build_review
    model = build_review(revision(before), revision(after))
    a = c = 0
    for section in model.sections:
        x,y = section.original_range
        z,w = section.incoming_range
        assert before[a:x] == after[c:z]
        a,c = y,w
    assert before[a:] == after[c:]


def test_complete_review_preserves_correspondence_and_round_trips():
    from dataclasses import replace
    from app.src.review_model import build_review
    before, after = sample_transcript()
    old = revision(before)
    new = old.revise(after)
    model = build_review(old, new)
    aa = [p[3] for p in _paragraphs(before, byline_context=False)]
    bb = [p[3] for p in _paragraphs(after, byline_context=False)]
    pairs = {(a,c) for _,a,b,c,d in _paragraph_ops(aa,bb) if b-a == d-c == 1}
    assert {(0,0), (4,6), (5,7)} <= pairs
    for ranges in (sorted(span for edit in model.edits for span in edit.ranges),
                   [(*section.original_range, *section.incoming_range) for section in model.sections]):
        a = c = 0
        for x,y,z,w in ranges:
            assert before[a:x] == after[c:z]
            a,c = y,w
        assert before[a:] == after[c:]
    for accept, expected in ((True, after), (False, before)):
        kept, pending = old, new
        for change in reversed(model.edits):
            change = replace(change, original=kept, incoming=pending)
            kept, pending = resolve(kept, pending, change, accept)
        assert kept.text == pending.text == expected
