"""A retained sentence moving to a new paragraph is a boundary edit."""
import pytest

from app.tests.test_suggestions import revision
from app.src.suggestions import suggestions, resolve


FIRST = 'Please describe the inspection of the machine and the maintenance records that you reviewed.'
LAST = "In your opinion, could these findings affect the operation of the machine if they're left unresolved?"
CORRECTED = 'In your opinion, could these findings affect the operation of the machine if they are left unresolved?'


@pytest.mark.parametrize('first_label,last_label', [
    ('Q ', '          '), ('Q ', 'Q '), ('A ', 'A '),
    ('MS. COUNSEL: ', '     '), ('', '    '),
])
@pytest.mark.parametrize('reverse', [False, True])
def test_preserved_paragraph_split_and_join_keep_wording_independent(first_label, last_label, reverse):
    before = first_label + FIRST + '  ' + LAST + '\nA Understood.\n'
    after = first_label + FIRST + '\n' + last_label + CORRECTED + '\nA Understood.\n'
    if reverse:
        before, after = after, before
    old, new = revision(before), revision(after)
    changes = suggestions(old, new)
    assert all(change.kind != 'group' for change in changes)
    structural = [change for change in changes if change.kind == 'structure']
    assert len(structural) == 1
    a,b,c,d = structural[0].ranges[0]
    # The engine leaves common spaces outside the changed range. Applying the
    # boundary edit still produces exactly the new layout without wording.
    changed_layout = before[:a] + after[c:d] + before[b:]
    assert changed_layout == (after.replace(LAST, CORRECTED) if reverse else after.replace(CORRECTED, LAST))
    # Accepting or rejecting the break must not decide the contraction edit.
    kept, pending = resolve(old, new, structural[0], True)
    assert (CORRECTED if reverse else LAST) in kept.text
    assert (LAST if reverse else CORRECTED) in pending.text
    kept, pending = resolve(old, new, structural[0], False)
    assert (LAST if reverse else CORRECTED) in pending.text
    assert kept.text == before
    for accept in (False, True):
        kept, pending = old, new
        for _ in range(30):
            remaining = suggestions(kept, pending)
            if not remaining:
                break
            kept, pending = resolve(kept, pending, remaining[-1], accept)
        assert not suggestions(kept, pending)
        assert kept.text == pending.text == (after if accept else before)


def test_sentence_split_with_changes_on_both_sides_and_trailing_spaces():
    before = 'Q '+FIRST+'  '+LAST+' \nA Understood.\n'
    after = 'Q '+FIRST.replace('inspection', 'assessment')+' \n          '+CORRECTED+'\nA Understood.\n'
    old, new = revision(before), revision(after)
    changes = suggestions(old,new)
    assert all(c.kind != 'group' for c in changes)
    assert all(max(b-a,d-c) < 25 for change in changes for a,b,c,d in change.ranges)
    structural, = [c for c in changes if c.kind == 'structure']
    kept, pending = resolve(old,new,structural,True)
    assert FIRST in kept.text and LAST in kept.text
    assert 'assessment' in pending.text and CORRECTED in pending.text


@pytest.mark.parametrize('second', ['A ', 'MR. OTHER: '])
def test_speaker_changes_are_not_silently_treated_as_same_turn_splits(second):
    before='Q '+FIRST+' '+LAST+'\n'
    after='Q '+FIRST+'\n'+second+LAST+'\n'
    changes=suggestions(revision(before),revision(after))
    assert not any(before[a:b] == ' ' and after[c:d] == '\n'+second
                   for change in changes for a,b,c,d in change.ranges)


def test_repeated_tail_is_not_assumed_to_be_a_unique_split():
    before='Q '+FIRST+' '+LAST+' '+LAST+'\n'
    after='Q '+FIRST+' '+LAST+'\n          '+CORRECTED+'\n'
    changes=suggestions(revision(before),revision(after))
    assert not any(before[a:b] == ' ' and after[c:d] == '\n          '
                   for change in changes for a,b,c,d in change.ranges)


@pytest.mark.parametrize('index', [0, 4])
@pytest.mark.parametrize('accept', [False, True])
def test_existing_transcript_splits_are_small_independent_decisions(index, accept):
    from app.tests.test_related_suggestions import EXAMPLES
    before, after = EXAMPLES[index]
    old, new = revision(before), revision(after)
    changes = suggestions(old,new)
    assert all(c.kind != 'group' for c in changes)
    structural, = [c for c in changes if c.kind == 'structure']
    a,b,c,d = structural.ranges[0]
    assert not before[a:b].strip()
    assert '\n' in after[c:d] and not after[c:d].strip()
    kept, pending = resolve(old,new,structural,True)
    assert ("they're not working" if index == 4 else 'Kristin') in kept.text
    for _ in range(30):
        remaining = suggestions(old,new)
        if not remaining:
            break
        old,new = resolve(old,new,remaining[0],accept)
    assert old.text == new.text == (after if accept else before)


@pytest.mark.parametrize('prefix', ['And ', 'Well, '])
def test_unmatched_leading_words_cannot_move_the_previous_sentence_end(prefix):
    before='Q '+FIRST+' '+LAST+'\n'
    after='Q '+FIRST+'\n          '+prefix+CORRECTED+'\n'
    old,new=revision(before),revision(after)
    for change in suggestions(old,new):
        if change.kind == 'structure':
            kept,_=resolve(old,new,change,True)
            assert FIRST in kept.text


@pytest.mark.parametrize('opening,closing', [('"', '"'), ('(', ')'), ('[', ']'), ('\u201c', '\u201d')])
@pytest.mark.parametrize('reverse', [False,True])
def test_opening_punctuation_stays_with_its_sentence(opening, closing, reverse):
    before='Q '+FIRST+'  '+opening+LAST+closing+'\n'
    after='Q '+FIRST+'\n          '+opening+LAST+closing+'\n'
    if reverse:
        before,after=after,before
    old,new=revision(before),revision(after)
    changes=suggestions(old,new)
    assert len(changes)==1
    assert changes[0].kind=='structure'
    kept,pending=resolve(old,new,changes[0],True)
    assert kept.text==pending.text==after


def test_break_preview_shows_nearby_words_instead_of_the_whole_paragraph():
    from html import unescape
    import re
    from app.src.review_view import change_diff
    old=revision('Q '+FIRST+'  '+LAST+'\n')
    new=revision('Q '+FIRST+'\n          '+CORRECTED+'\n')
    change,=[c for c in suggestions(old,new) if c.kind=='structure']
    shown='\n'.join(unescape(re.sub(r'<[^>]+>', '', text)) for _,text in change_diff(change))
    assert 'Please describe the inspection' not in shown
    assert 'records that you reviewed.' in shown
    assert 'In your opinion' in shown
    assert 'left unresolved' not in shown


def test_accepting_only_split_preserves_unchanged_sentence_audio_anchors():
    from app.src.casecat.anchors import AnchoredSpan, Revision
    old=Revision((AnchoredSpan('first',(0,),('00:01',),'Q '+FIRST),
                  AnchoredSpan('boundary',(1,),('00:02',),'  '),
                  AnchoredSpan('last',(2,),('00:03',),LAST+'\n')))
    new=old.revise('Q '+FIRST+'\n          '+CORRECTED+'\n')
    change,=[c for c in suggestions(old,new) if c.kind=='structure']
    kept,pending=resolve(old,new,change,True)
    assert kept.text=='Q '+FIRST+'\n          '+LAST+'\n'
    assert old.spans[0] in kept.spans
    assert old.spans[2] in kept.spans
    assert CORRECTED in pending.text
