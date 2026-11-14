"""Structural-only paragraphs must follow testimony, not anchor distant turns."""
import pytest

from app.src.suggestion_filter import _paragraphs, aligned_paragraphs
from app.src.suggestions import _paragraph_ops, suggestions, resolve, propose
from app.tests.test_suggestions import revision


OLD = [
    'Q What factors affect a persons ability to travel?',
    'A Transportation could affect their ability to travel.',
    'Q Did the patient describe any problems with vision?',
    'A The patient described some problems with vision.',
    'Q Would you discuss these issues during the next visit?',
    'A I would discuss those issues during the next visit.',
]
NEW = [
    "Q What factors affect a person's ability to travel?",
    'A Transportation might affect their ability to travel.',
    'Q Did the patient describe any problems with eyesight?',
    'A The patient described some problems with eyesight.',
    'Q Would you discuss these issues during the upcoming visit?',
    'A I would discuss those issues during the upcoming visit.',
]


@pytest.mark.parametrize('marker', ['', '  ', 'A', '     A    ', 'Q',
                                    'BY MS. COUNSEL:', 'THE WITNESS:', 'SPEAKER 3:', '--'])
@pytest.mark.parametrize('reverse', [False, True])
def test_structural_paragraphs_cannot_move_changed_testimony(marker, reverse):
    old = [marker] + OLD
    new = NEW[:4] + [marker] + NEW[4:]
    if reverse:
        old, new = new, old
    # Exercise both the complete paragraphs used in proposal preparation and
    # the label-free bodies used when generating review decisions.
    for aa, bb in ((old, new),
                   ([p[3] for p in _paragraphs('\n'.join(old), byline_context=False)],
                    [p[3] for p in _paragraphs('\n'.join(new), byline_context=False)])):
        ops = _paragraph_ops(aa, bb)
        pairs = {(a, c) for _, a, b, c, d in ops if b-a == d-c == 1}
        expected = {(i+1, i+(i >= 4)) for i in range(6)}
        if reverse:
            expected = {(b, a) for a,b in expected}
        assert expected <= pairs
        # The alignment must cover both texts in order without losing a line.
        a = c = 0
        for _, start, end, ns, ne in ops:
            assert (start, ns) == (a, c)
            a, c = end, ne
        assert (a, c) == (len(old), len(new))


def test_speaker_evidence_uses_context_without_anchoring_on_borrowed_body():
    old = 'A\n' + '\n'.join(OLD)
    new = '\n'.join(NEW[:4] + ['BY MS. COUNSEL:'] + NEW[4:])
    _, _, pairs = aligned_paragraphs(old, new)
    assert {(i+1, i+(i >= 4)) for i in range(6)} <= set(pairs)


@pytest.mark.parametrize('accept', [False, True])
def test_review_preserves_local_word_changes_and_independent_structure(accept):
    old = revision('     A    \n' + '\n'.join(OLD) + '\n')
    incoming = old.revise('\n'.join(NEW[:4] + ['BY MS. COUNSEL:'] + NEW[4:]) + '\n')
    changes = suggestions(old, incoming)
    assert changes
    assert all(max(b-a, d-c) < 80 for change in changes for a,b,c,d in change.ranges)
    expected = incoming.text if accept else old.text
    for _ in range(50):
        changes = suggestions(old, incoming)
        if not changes:
            break
        old, incoming = resolve(old, incoming, changes[0], accept)
    assert old.text == incoming.text == expected
    assert not suggestions(old, incoming)


def test_propose_keeps_each_matched_paragraphs_indentation():
    old = revision('A\n' + '\n'.join(' '*i + line for i,line in enumerate(OLD, 1)))
    result = propose(old, '\n'.join(NEW[:4] + ['BY MS. COUNSEL:'] + NEW[4:]))
    assert [line for line in result.text.splitlines() if 'COUNSEL' not in line] == [
        ' '*i + line for i,line in enumerate(NEW, 1)]


def test_repeated_empty_markers_do_not_split_similar_paragraphs_apart():
    a = [''] + OLD[:2] + ['', ''] + OLD[2:]
    b = NEW[:4] + ['', '', ''] + NEW[4:]
    pairs = {(i,k) for _,i,j,k,l in _paragraph_ops(a,b) if j-i == l-k == 1}
    assert {(1,0), (2,1), (5,2), (6,3), (7,7), (8,8)} <= pairs


@pytest.mark.parametrize('count', [12, 120])
def test_long_reviews_ignore_structural_density(count):
    left, right, expected = [], [], set()
    for i in range(count):
        left.extend(['', 'A', 'BY MS. COUNSEL:'] if i % 2 == 0 else [])
        right.extend(['THE WITNESS:', 'Q', ''] if i % 3 == 0 else [])
        expected.add((len(left), len(right)))
        left.append(f'Q Describe item {i} from the previous inspection.')
        right.append(f'Q Describe item {i} from the earlier inspection.')
    pairs = {(a,c) for _,a,b,c,d in _paragraph_ops(left,right) if b-a == d-c == 1}
    assert expected <= pairs


@pytest.mark.parametrize('before,after', [
    ('A\n\nBY MS. COUNSEL:\n', 'Q\nBY MR. OTHER:\n'),
    ('', 'A\n'),
    ('THE WITNESS:\n', ''),
])
def test_structural_only_changes_remain_reviewable(before, after):
    old, new = revision(before), revision(after)
    assert suggestions(old, new)
    for accept in (False, True):
        a, b = old, new
        for _ in range(20):
            pending = suggestions(a, b)
            if not pending:
                break
            a, b = resolve(a, b, pending[0], accept)
        assert a.text == b.text == (after if accept else before)
        assert not suggestions(a, b)
