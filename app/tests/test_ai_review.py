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
    ('A track was there.', 'A tract was there.', []),
    ('I saw something.', 'I saw somethingz.', []),
    ('I saw a dog.', 'I saw a big red dog.', []),
    ('I saw a dog.', 'I saw a dog?', []),
    ('I saw it.', 'I saw IT.', []),
    ('THE MAN: Yes.', 'THE BOY: Yes.', []),
    ('First.\nThen.', 'First. Then.', []),
    ('Value 1000.', 'Value 1,000.', []),
    ('A long-term job.', 'A long-time job.', []),
])
def test_candidates_use_whole_words(before, after, words):
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


@pytest.mark.parametrize('testing', [False, True])
def test_review_resolves_both_sides_and_optionally_logs_one_batch(tmp_path, testing):
    original = revision('Last day of work.\nI saw a blue car.\nI left that day.')
    incoming = original.revise('Last date of work.\nI saw a red car.\nI left on that day.')
    calls = []

    def complete(payload, prompt):
        calls.append(json.loads(payload))
        return '{"1":"accept","2":"reject","3":"abstain"}'

    left, right, _, summary = review_edits(original, incoming, None, 'gemini-3.8-flash',
                                          complete, 'test-document', testing=testing, directory=tmp_path)
    assert len(calls) == 1
    assert calls[0][0]['original'] == 'Last day of work.'
    assert calls[0][0]['proposed'] == 'Last date of work.'
    assert left.text == 'Last date of work.\nI saw a blue car.\nI left that day.'
    assert right.text == 'Last date of work.\nI saw a blue car.\nI left on that day.'
    assert len(suggestions(left, right)) == 1
    assert summary == 'Total edits: 3, accepted: 1, rejected: 1, abstained: 1'
    if testing:
        log, = tmp_path.glob('*.txt')
        lines = log.read_text(encoding='utf-8').splitlines()
        assert lines[0] == summary
        assert [json.loads(line)['decision'] for line in lines[3:]] == ['accept', 'reject', 'abstain']
    else:
        assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('output', [
    'invalid JSON', '{}', '{"1":"accept","1":"reject"}', '{"1":"accept","99":"accept"}',
])
def test_invalid_model_output_leaves_edits_pending(tmp_path, output):
    original = revision('Last day of work.')
    incoming = original.revise('Last date of work.')
    left, right, _, summary = review_edits(original, incoming, None, 'gemini-3.8-flash',
                                          lambda *_: output, 'test', directory=tmp_path)
    assert (left, right) == (original, incoming)
    assert 'abstained: 1' in summary
