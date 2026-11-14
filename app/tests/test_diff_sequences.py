import json
from pathlib import Path

import pytest

from app.src.diff_sequences import CharSequence, Diff, LineSequence, Range, dynamic_programming, myers


REFERENCE = json.loads((Path(__file__).parent / 'fixtures/advanced-sequences.json').read_text(encoding='utf-8'))


def tuples(diffs):
    return [[d.seq1_range.start, d.seq1_range.end_exclusive,
             d.seq2_range.start, d.seq2_range.end_exclusive] for d in diffs]


@pytest.mark.parametrize('case', REFERENCE['cases'])
def test_core_algorithms_match_pinned_upstream(case):
    a, b = LineSequence(case['a'], list(map(str, case['a']))), LineSequence(case['b'], list(map(str, case['b'])))
    score = (lambda i, j: case['weights'][i]) if case['weights'] is not None else None
    assert tuples(dynamic_programming(a, b, score)) == case['dp']
    assert tuples(myers(a, b)) == case['myers']


@pytest.mark.parametrize('case', REFERENCE['characters'])
def test_character_sequence_matches_pinned_upstream(case):
    sequence = CharSequence(case['lines'], tuple(case['span']), case['whitespace'])
    expected = case['expected']
    pair = lambda r: [r.start, r.end_exclusive] if r is not None else None
    assert [sequence.get_element(i) for i in range(sequence.length)] == expected['elements']
    assert [sequence.get_boundary_score(i) for i in range(sequence.length+1)] == expected['scores']
    assert [pair(sequence.find_word_containing(i)) for i in range(-1, sequence.length+1)] == expected['words']
    assert [pair(sequence.find_subword_containing(i)) for i in range(-1, sequence.length+1)] == expected['subwords']
    assert [list(sequence.translate_offset(i)) for i in range(sequence.length+1)] == expected['positions']
    assert [list(sequence.translate_offset(i, 'left')) for i in range(sequence.length+1)] == expected['leftPositions']


def test_diff_inverse_preserves_empty_equal_gaps_and_final_delta():
    changes = [Diff(Range(0, 1), Range(0, 2)), Diff(Range(3, 3), Range(4, 6))]
    assert tuples(Diff.invert(changes, 5)) == [[0, 0, 0, 0], [1, 3, 2, 4], [3, 5, 6, 8]]
