"""Python port of the upstream advanced line and inner-change pipeline.

Derived from Microsoft’s implementation (MIT). See licenses/advanced_diff/LICENSE.txt.
Only the options used by transcript review are implemented: whitespace counts,
no move detection, and no subword extension. Display hunks are not decisions.
"""
from math import log
from time import monotonic

from app.src.diff_sequences import Range, Diff, LineSequence, CharSequence, dynamic_programming, myers, js_trim
from app.src.diff_heuristics import (
    optimize_sequence_diffs, remove_very_short_matching_lines_between_diffs,
    extend_diffs_to_entire_word_if_appropriate, remove_short_matches,
    remove_very_short_matching_text_between_long_diffs,
)


def _width(text):
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def _slice_ranges(diff, original, incoming):
    """Convert half-open line ranges using VS Code's end-of-document rules."""
    a, b = diff.seq1_range, diff.seq2_range
    if a.end_exclusive < len(original) and b.end_exclusive < len(incoming):
        return ((a.start, 0, a.end_exclusive, 0),
                (b.start, 0, b.end_exclusive, 0))
    if a.start < a.end_exclusive and b.start < b.end_exclusive:
        return ((a.start, 0, a.end_exclusive-1, _width(original[a.end_exclusive-1])),
                (b.start, 0, b.end_exclusive-1, _width(incoming[b.end_exclusive-1])))
    if a.start > 0 and b.start > 0:
        return ((a.start-1, _width(original[a.start-1]), a.end_exclusive-1, _width(original[a.end_exclusive-1])),
                (b.start-1, _width(incoming[b.start-1]), b.end_exclusive-1, _width(incoming[b.end_exclusive-1])))
    raise ValueError('Invalid advanced diff line ranges.')


def _refine(original, incoming, diff, check_timeout):
    left_range, right_range = _slice_ranges(diff, original, incoming)
    left, right = CharSequence(original, left_range), CharSequence(incoming, right_range)
    changes = dynamic_programming(left, right, check_timeout=check_timeout) if left.length + right.length < 500 else myers(left, right, check_timeout=check_timeout)
    changes = optimize_sequence_diffs(left, right, changes)
    changes = extend_diffs_to_entire_word_if_appropriate(left, right, changes, lambda seq, pos: seq.find_word_containing(pos))
    changes = remove_short_matches(left, right, changes)
    changes = remove_very_short_matching_text_between_long_diffs(left, right, changes)
    return [(*left.translate_offset(change.seq1_range.start, 'right'),
             *left.translate_offset(change.seq1_range.end_exclusive, 'left'),
             *right.translate_offset(change.seq2_range.start, 'right'),
             *right.translate_offset(change.seq2_range.end_exclusive, 'left')) for change in changes]


def compute_inner_changes(original, incoming):
    """Return paired, zero-based UTF-16 ranges from the advanced diff pipeline."""
    deadline = monotonic() + 30
    def check_timeout():
        if monotonic() >= deadline:
            raise TimeoutError('Advanced diff exceeded its computation limit.')
    if len(original) <= 1 and original == incoming:
        return ()
    if original == ('',) or incoming == ('',):
        return ((0, 0, len(original)-1, _width(original[-1]),
                 0, 0, len(incoming)-1, _width(incoming[-1])),)
    hashes = {}
    def hashed(lines):
        return [hashes.setdefault(js_trim(line), len(hashes)) for line in lines]
    left, right = LineSequence(hashed(original), original), LineSequence(hashed(incoming), incoming)
    exact_scores = [1 + log(1 + _width(line)) if line else 0.1 for line in incoming]
    def equality_score(i, j):
        return exact_scores[j] if original[i] == incoming[j] else 0.99
    changes = dynamic_programming(left, right, equality_score, check_timeout=check_timeout) if left.length + right.length < 1700 else myers(left, right, check_timeout=check_timeout)
    changes = optimize_sequence_diffs(left, right, changes)
    changes = remove_very_short_matching_lines_between_diffs(left, right, changes)
    mappings = []
    last_a = last_b = 0
    for change in changes + [Diff(Range(len(original), len(original)), Range(len(incoming), len(incoming)))]:
        assert change.seq1_range.start-last_a == change.seq2_range.start-last_b
        for offset in range(change.seq1_range.start-last_a):
            i, j = last_a+offset, last_b+offset
            if original[i] != incoming[j]:
                mappings.extend(_refine(original, incoming, Diff(Range(i, i+1), Range(j, j+1)), check_timeout))
        if change.seq1_range.start < len(original) or change.seq2_range.start < len(incoming):
            mappings.extend(_refine(original, incoming, change, check_timeout))
        last_a, last_b = change.seq1_range.end_exclusive, change.seq2_range.end_exclusive
    return tuple(mappings)
