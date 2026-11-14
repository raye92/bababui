import pytest

from app.tests.test_related_suggestions import EXAMPLES
from app.tests.test_suggestions import revision
from app.src.suggestions import suggestions, resolve


@pytest.mark.parametrize('answer', ['Correct.', 'That is my understanding.', 'No, I disagree.'])
@pytest.mark.parametrize('labels', [('Q ', 'A '), ('     Q    ', '     A    '), ('MS. SIEMENS: ', 'THE WITNESS: ')])
def test_join_removes_intervening_turn_without_bundling_wording(answer, labels):
    question, response = labels
    # Use different wording from the reported transcript to exercise the rule.
    first = 'Please describe the documents you examined before preparing the assessment of the equipment and its maintenance history?'
    second = 'I would like you to inspect the maintenance records before arranging another examination of the equipment next month.'
    corrected = 'I would like you to inspect the service records before arranging another examination of the equipment next week.'
    before = question+first+'\n'+response+answer+'\n'+question+second+'\n'+response+'Agreed.\n'
    after = question+first[:-1]+'. '+corrected+'\n'+response+'Agreed.\n'
    old, new = revision(before), revision(after)
    changes = suggestions(old, new)
    assert all(c.kind != 'group' for c in changes)
    structural = [c for c in changes if c.kind == 'structure']
    assert len(structural) == 1
    change = structural[0]
    a,b,c,d = change.ranges[0]
    assert old.text[a:b] == '?\n'+response+answer+'\n'+question[:-1]
    assert new.text[c:d] == '.'
    accepted, pending = resolve(old, new, change, True)
    assert second in accepted.text
    assert answer not in accepted.text
    assert 'maintenance records' in accepted.text
    assert len(suggestions(accepted, pending)) >= 2
    kept, rejected = resolve(old, new, change, False)
    assert '\n'+response+answer+'\n'+question in rejected.text
    assert corrected in rejected.text
    assert kept.text == before


def test_transcript_review_join_keeps_contraction_and_name_edits_separate():
    before, after = EXAMPLES[5]
    old, new = revision(before), revision(after)
    changes = suggestions(old, new)
    assert all(c.kind != 'group' for c in changes)
    structural = [c for c in changes if c.kind == 'structure']
    assert len(structural) == 1
    a,b,c,d = structural[0].ranges[0]
    assert before[a:b] == '?\nA Correct.\nQ'
    assert after[c:d] == '.'
    wording = [before[a:b] for change in changes if change.kind == 'text' for a,b,_,_ in change.ranges]
    assert 'W' in wording
    assert any('would' in text for text in wording)
    for accept in (True, False):
        kept, pending = old, new
        for _ in range(30):
            remaining = suggestions(kept, pending)
            if not remaining:
                break
            # Resolve wording first as well as allowing structure first.
            kept, pending = resolve(kept, pending, remaining[-1], accept)
        assert not suggestions(kept, pending)
        assert kept.text == pending.text == (after if accept else before)


def test_adjacent_paragraphs_join_without_an_intervening_answer():
    before, after = EXAMPLES[5]
    before = before.replace('A Correct.\n', '')
    changes = suggestions(revision(before), revision(after))
    structural = [c for c in changes if c.kind == 'structure']
    assert all(c.kind != 'group' for c in changes)
    assert len(structural) == 1
    a,b,c,d = structural[0].ranges[0]
    assert before[a:b] == '?\nQ'
    assert after[c:d] == '.'


@pytest.mark.parametrize('bridge', ['(A discussion was held off the record.)', 'A Correct.'])
def test_repeated_return_or_off_record_note_is_not_reinterpreted_as_a_simple_join(bridge):
    before, after = EXAMPLES[5]
    before = before.replace('A Correct.', bridge)
    if bridge.startswith('A '):
        tail = after[after.index('I would like'):after.index('\nA Absolutely.')]
        after = after.replace('\nA Absolutely.', ' '+tail+'\nA Absolutely.')
    changes = suggestions(revision(before), revision(after))
    assert not any(before[a:b] == '\n'+bridge+'\nQ ' for change in changes for a,b,_,_ in change.ranges)
