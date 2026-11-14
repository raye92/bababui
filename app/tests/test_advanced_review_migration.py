"""Behavioral checks for advanced inner changes through native review."""
from itertools import permutations, product

import pytest

from app.src.casecat.anchors import AnchoredSpan, Revision
from app.src.suggestions import resolve, suggestions


# Invented transcript exercises a paragraph join beside independent corrections.
BEFORE = '     MR. DAWSON:  The technician reviewed the delivery schedule.  \nFor the next shipment, could you please confirm the expected arrival?  \n     MS. RIVERA:  Yes.  '
AFTER = '     MR. DAWSON:  The technician reviewed the delivery schedule.  For the next shipment, can you please confirm the expected arrival. \n     THE WITNESS:  Yes.  '
PAIRS = {'join': ('\n', ''), 'word': ('could', 'can'),
         'speaker': ('MS. RIVERA', 'THE WITNESS')}


def passage():
    return BEFORE, AFTER


def revision(text):
    yes = text.rindex('Yes.')
    return Revision((AnchoredSpan('before', (1,), ('00:01',), text[:yes]),
                     AnchoredSpan('answer', (2,), ('00:02',), 'Yes.'),
                     AnchoredSpan('after', (3,), (), text[yes+4:])))


def change_for(old, new, pair):
    matches = [change for change in suggestions(old, new)
               if [(old.text[a:b], new.text[c:d]) for a,b,c,d in change.ranges] == [pair]]
    assert len(matches) == 1, (pair, [(old.text[a:b], new.text[c:d])
                                      for change in suggestions(old, new) for a,b,c,d in change.ranges])
    return matches[0]


def apply_one(text, before, after):
    # The paragraph join is the first boundary, before the surviving sentence.
    if before == '\n':
        return text.replace('\nFor the next shipment', 'For the next shipment', 1)
    if before in ('could', 'can'):
        return text.replace(before + ' you please', after + ' you please', 1)
    assert text.count(before) == 1
    return text.replace(before, after, 1)


@pytest.mark.parametrize('order', list(permutations(PAIRS)))
@pytest.mark.parametrize('choices', list(product((False, True), repeat=3)))
def test_join_wording_and_speaker_resolve_in_any_order(order, choices):
    before, after = passage()
    old = revision(before)
    new = old.revise(after)
    answer = old.spans[1]
    assert answer in new.spans
    expected_old, expected_new = before, after
    pending = set(PAIRS)
    for name, accept in zip(order, choices):
        old_text, new_text = PAIRS[name]
        change = change_for(old, new, (old_text, new_text))
        old, new = resolve(old, new, change, accept)
        if accept:
            expected_old = apply_one(expected_old, old_text, new_text)
        elif name == 'join':
            expected_new = expected_new.replace('For the next shipment', '\nFor the next shipment', 1)
        else:
            expected_new = apply_one(expected_new, new_text, old_text)
        assert old.text == expected_old
        assert new.text == expected_new
        assert answer in old.spans and answer in new.spans
        pending.remove(name)
        for remaining in pending:
            change_for(old, new, PAIRS[remaining])
        # Other punctuation corrections remain reviewable throughout.
        change_for(old, new, ('? ', '.'))


@pytest.mark.parametrize('accept', (False, True))
def test_join_does_not_absorb_native_speaker_field(accept):
    before, after = passage()
    old = revision(before)
    start = before.index('MS. RIVERA')
    old = old._replace(start, start+len('MS. RIVERA'), '').insert_field(start, 'SPEAKER', 'MS. RIVERA')
    new = old.revise(after)
    change = change_for(old, new, PAIRS['speaker'])
    assert change.kind == 'field' and change.field == 'SPEAKER'
    assert not any('\n' in old.text[a:b]+new.text[c:d] for a,b,c,d in change.ranges)
    old, new = resolve(old, new, change, accept)
    change_for(old, new, PAIRS['join'])
    change_for(old, new, PAIRS['word'])
    assert dict(old.definitions)['SPEAKER'] == dict(new.definitions)['SPEAKER'] == ('THE WITNESS' if accept else 'MS. RIVERA')
    assert all(any(e.kind == 'field' and e.name == 'SPEAKER' for e in rev.elements) for rev in (old, new))


@pytest.mark.parametrize('before,after', [
    ('😀 Start.\nQ The car is red.\nA Yes.', '😀 Start.\nQ The car is blue.\nA Yes.'),
    ('😀 Start.\r\nQ The car is red.\r\nA Yes.', '😀 Start.\r\nQ The car is blue.\r\nA Yes.'),
    ('😀 Start.\r\nQ The car is red.\rA Yes.', '😀 Start.\nQ The car is blue.\r\nA Yes.'),
    ('First.\r\nSecond.\r\n', 'First.\nSecond.\n'),
    ('First.\nSecond.\n', 'First.\r\nSecond.\r\n'),
    ('\r\n', '\n'),
    ('', '😀 Hello.\r\n'),
    ('😀 Hello.\r\n', ''),
    ('😀', '😃'),
    ('Text\r\n', 'Text'),
    ('Text', 'Text\r\n'),
])
def test_engine_ranges_are_python_offsets_and_reconstruct_exact_raw_text(before, after):
    from app.src.advanced_diff import text_edits
    ranges = text_edits(before, after)
    a = c = 0
    for x, y, z, w in ranges:
        assert a <= x <= y <= len(before)
        assert c <= z <= w <= len(after)
        assert before[a:x] == after[c:z]
        a, c = y, w
    assert before[a:] == after[c:]
    forward, reverse = before, after
    for a, b, c, d in reversed(ranges):
        forward = forward[:a] + after[c:d] + forward[b:]
        reverse = reverse[:c] + before[a:b] + reverse[d:]
    assert forward == after
    assert reverse == before


def test_synthetic_passage_has_four_independent_inner_changes():
    from app.src.advanced_diff import text_edits
    before, after = passage()
    assert [(before[a:b], after[c:d]) for a,b,c,d in text_edits(before, after)] == [
        ('\n', ''), ('could', 'can'), ('? ', '.'), ('MS. RIVERA', 'THE WITNESS'),
    ]
