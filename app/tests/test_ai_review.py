import json

import pytest

from app.src.ai_review import candidates, review_edits
from app.src.casecat.anchors import AnchoredSpan, Revision
from app.src.suggestions import suggestions


def revision(text):
    return Revision((AnchoredSpan('root', (0,), (12,), text),))


@pytest.mark.parametrize('before,after,words', [
    ('The last day of work.', 'The last date of work.', [('day', 'date')]),
    ('I saw a dog.', 'I saw a big dog.', [('', 'big')]),
    ('I saw a big dog.', 'I saw a dog.', [('big', '')]),
    ('A track was there.', 'A tract was there.', [('track', 'tract')]),
    ('I saw something.', 'I saw somethingz.', [('something', 'somethingz')]),
    ('I saw a dog.', 'I saw a big red dog.', [('', 'big red')]),
    ('I saw a big red dog.', 'I saw a dog.', [('big red', '')]),
    ('Our old dog slept.', 'His new dog slept.', [('Our old', 'His new')]),
    ('The work restrictions by Dr. Pelton.', 'The work restriction for Dr. Pelton.',
     [('restrictions by', 'restriction for')]),
    ('Who is providing the treatment?', "Who's providing the treatment?", [('Who is', "Who's")]),
    ("Who's providing the treatment?", 'Who is providing the treatment?', [("Who's", 'Who is')]),
    ('I saw a dog.', 'I saw a big red old dog.', []),
    ('I saw a dog.', 'I saw a brown dog.', []),
    ('I saw a dog.', 'I saw a big brown dog.', []),
    ('Our old red dog slept.', 'His new tan dog slept.', []),
    ('Who is providing the treatment?', "Who's actually providing the treatment?", []),
    ('I saw a dog.', 'I saw a dog?', []),
    ('I saw it,', 'I saw that.', [('it,', 'that.')]),
    ('I saw it by noon.', 'I saw it, at noon.', [('by', ', at')]),
    ("Who's in?", 'Who is out?', [("Who's in", 'Who is out')]),
    ('I saw a dog.', 'I saw a brown dog?', []),
    ('I saw it.', 'I saw IT.', []),
    ('THE MAN: Yes.', 'THE BOY: Yes.', []),
    ('First.\nThen.', 'First. Then.', []),
    ('Value 1000.', 'Value 1,000.', []),
    ('A long-term job.', 'A long-time job.', [('long-term', 'long-time')]),
])
def test_candidates_limit_affected_words_and_changed_letters(before, after, words):
    original = revision(before)
    assert [(item['original_word'], item['proposed_word'])
            for _, item in candidates(original, original.revise(after))] == words


def test_candidates_use_same_truncated_excerpt_as_edit_card():
    from html import unescape
    import re

    from app.src.review_view import change_diff

    original = revision('a b c d e f g h i j day k l m n o p q r s t')
    incoming = original.revise(original.text.replace('day', 'date'))
    (edit, item), = candidates(original, incoming)
    assert item['original'] == '… c d e f g h i j day k l m n o p q r …'
    assert item['proposed'] == item['original'].replace('day', 'date')
    assert unescape(re.sub(r'<[^>]+>', '', change_diff(edit)[0][1])) == (
        item['original'].replace('day', 'daydate'))


def test_review_resolves_both_sides_in_one_batch():
    original = revision('Last day of work.\nI saw a blue car.\nI left that day.')
    incoming = original.revise('Last date of work.\nI saw a red car.\nI left on that day.')
    calls = []

    def complete(payload, prompt):
        calls.append(json.loads(payload))
        return '{"1":"accept","2":"reject","3":"abstain"}'

    left, right, _, summary = review_edits(original, incoming, None, complete)
    assert len(calls) == 1
    assert calls[0][0]['original'] == 'Last day of work.'
    assert calls[0][0]['proposed'] == 'Last date of work.'
    assert left.text == 'Last date of work.\nI saw a blue car.\nI left that day.'
    assert right.text == 'Last date of work.\nI saw a blue car.\nI left on that day.'
    assert len(suggestions(left, right)) == 1
    assert summary == 'Total edits: 3, accepted: 1, rejected: 1, abstained: 1'


@pytest.mark.parametrize('output', [
    'invalid JSON', '{}', '{"1":"accept","1":"reject"}', '{"1":"accept","99":"accept"}',
])
def test_invalid_model_output_leaves_edits_pending(output):
    original = revision('Last day of work.')
    incoming = original.revise('Last date of work.')
    left, right, _, summary = review_edits(original, incoming, None, lambda *_: output)
    assert (left, right) == (original, incoming)
    assert 'abstained: 1' in summary
