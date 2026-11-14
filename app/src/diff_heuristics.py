"""Python port of the upstream advanced diff sequence optimizations.

Copyright (c) Microsoft Corporation. All rights reserved.
Licensed under the MIT License. See app/licenses/advanced_diff/LICENSE.txt.
Ported from heuristicSequenceOptimizations.ts at commit
69047191fc427f2f92828279aae1d90d8eeda7ab. These are the upstream inner-change
heuristics, not Bababui review-decision or paragraph grouping rules.
"""
from collections import deque
import re

from app.src.diff_sequences import Diff, OffsetPair, Range, JS_WHITESPACE


_JS_WHITESPACE = JS_WHITESPACE
_WITHOUT_WHITESPACE = str.maketrans('', '', _JS_WHITESPACE)
_LINE_BREAK = re.compile(r'\r\n|\r|\n')
_MAX_SAFE_INTEGER = 9007199254740991


def optimize_sequence_diffs(sequence1, sequence2, sequence_diffs):
    result = join_sequence_diffs_by_shifting(sequence1, sequence2, sequence_diffs)
    result = join_sequence_diffs_by_shifting(sequence1, sequence2, result)
    return shift_sequence_diffs(sequence1, sequence2, result)


def join_sequence_diffs_by_shifting(sequence1, sequence2, sequence_diffs):
    if not sequence_diffs:
        return sequence_diffs
    result = [sequence_diffs[0]]
    for cur in sequence_diffs[1:]:
        previous = result[-1]
        if cur.seq1_range.is_empty or cur.seq2_range.is_empty:
            length = cur.seq1_range.start - previous.seq1_range.end_exclusive
            delta = 0
            while delta < length:
                candidate = delta + 1
                if (sequence1.get_element(cur.seq1_range.start-candidate)
                        != sequence1.get_element(cur.seq1_range.end_exclusive-candidate)
                        or sequence2.get_element(cur.seq2_range.start-candidate)
                        != sequence2.get_element(cur.seq2_range.end_exclusive-candidate)):
                    break
                delta = candidate
            if delta == length:
                result[-1] = Diff(
                    Range(previous.seq1_range.start, cur.seq1_range.end_exclusive-length),
                    Range(previous.seq2_range.start, cur.seq2_range.end_exclusive-length))
                continue
            cur = cur.delta(-delta)
        result.append(cur)

    shifted = []
    for index in range(len(result)-1):
        cur, following = result[index], result[index+1]
        if cur.seq1_range.is_empty or cur.seq2_range.is_empty:
            length = following.seq1_range.start - cur.seq1_range.end_exclusive
            delta = 0
            while delta < length:
                if (not sequence1.is_strongly_equal(cur.seq1_range.start+delta,
                                                    cur.seq1_range.end_exclusive+delta)
                        or not sequence2.is_strongly_equal(cur.seq2_range.start+delta,
                                                          cur.seq2_range.end_exclusive+delta)):
                    break
                delta += 1
            if delta == length:
                result[index+1] = Diff(
                    Range(cur.seq1_range.start+length, following.seq1_range.end_exclusive),
                    Range(cur.seq2_range.start+length, following.seq2_range.end_exclusive))
                continue
            if delta > 0:
                cur = cur.delta(delta)
        shifted.append(cur)
    shifted.append(result[-1])
    return shifted


def shift_sequence_diffs(sequence1, sequence2, sequence_diffs):
    if not getattr(sequence1, 'get_boundary_score', None) or not getattr(sequence2, 'get_boundary_score', None):
        return sequence_diffs
    for index, diff in enumerate(sequence_diffs):
        previous = sequence_diffs[index-1] if index else None
        following = sequence_diffs[index+1] if index+1 < len(sequence_diffs) else None
        valid1 = Range(previous.seq1_range.end_exclusive+1 if previous else 0,
                       following.seq1_range.start-1 if following else sequence1.length)
        valid2 = Range(previous.seq2_range.end_exclusive+1 if previous else 0,
                       following.seq2_range.start-1 if following else sequence2.length)
        if diff.seq1_range.is_empty:
            sequence_diffs[index] = shift_diff_to_better_position(diff, sequence1, sequence2, valid1, valid2)
        elif diff.seq2_range.is_empty:
            sequence_diffs[index] = shift_diff_to_better_position(
                diff.swap(), sequence2, sequence1, valid2, valid1).swap()
    return sequence_diffs


def shift_diff_to_better_position(diff, sequence1, sequence2, valid1, valid2):
    delta_before = 1
    while (diff.seq1_range.start-delta_before >= valid1.start
           and diff.seq2_range.start-delta_before >= valid2.start
           and sequence2.is_strongly_equal(diff.seq2_range.start-delta_before,
                                          diff.seq2_range.end_exclusive-delta_before)
           and delta_before < 100):
        delta_before += 1
    delta_before -= 1
    delta_after = 0
    while (diff.seq1_range.start+delta_after < valid1.end_exclusive
           and diff.seq2_range.end_exclusive+delta_after < valid2.end_exclusive
           and sequence2.is_strongly_equal(diff.seq2_range.start+delta_after,
                                          diff.seq2_range.end_exclusive+delta_after)
           and delta_after < 100):
        delta_after += 1
    if delta_before == delta_after == 0:
        return diff
    best_delta, best_score = 0, -1
    for delta in range(-delta_before, delta_after+1):
        score = (sequence1.get_boundary_score(diff.seq1_range.start+delta)
                 + sequence2.get_boundary_score(diff.seq2_range.start+delta)
                 + sequence2.get_boundary_score(diff.seq2_range.end_exclusive+delta))
        if score > best_score:
            best_score, best_delta = score, delta
    return diff.delta(best_delta)


def remove_short_matches(sequence1, sequence2, sequence_diffs):
    result = []
    for diff in sequence_diffs:
        if result and (diff.seq1_range.start-result[-1].seq1_range.end_exclusive <= 2
                       or diff.seq2_range.start-result[-1].seq2_range.end_exclusive <= 2):
            result[-1] = result[-1].join(diff)
        else:
            result.append(diff)
    return result


def extend_diffs_to_entire_word_if_appropriate(sequence1, sequence2, sequence_diffs, find_parent, force=False):
    equal_mappings = deque(Diff.invert(sequence_diffs, sequence1.length))
    additional = []
    last_point = OffsetPair(0, 0)

    def scan_word(pair, equal_mapping):
        nonlocal last_point
        if pair.offset1 < last_point.offset1 or pair.offset2 < last_point.offset2:
            return
        word1 = find_parent(sequence1, pair.offset1)
        word2 = find_parent(sequence2, pair.offset2)
        if word1 is None or word2 is None:
            return
        word = Diff(word1, word2)
        equal_part = word.intersect(equal_mapping)
        equal_chars1 = equal_part.seq1_range.length
        equal_chars2 = equal_part.seq2_range.length
        while equal_mappings:
            following = equal_mappings[0]
            if not (following.seq1_range.intersects(word.seq1_range)
                    or following.seq2_range.intersects(word.seq2_range)):
                break
            next_word = Diff(find_parent(sequence1, following.seq1_range.start),
                             find_parent(sequence2, following.seq2_range.start))
            next_equal = next_word.intersect(following)
            equal_chars1 += next_equal.seq1_range.length
            equal_chars2 += next_equal.seq2_range.length
            word = word.join(next_word)
            if word.seq1_range.end_exclusive >= following.seq1_range.end_exclusive:
                equal_mappings.popleft()
            else:
                break
        equal_chars = equal_chars1+equal_chars2
        total = word.seq1_range.length+word.seq2_range.length
        if (force and equal_chars < total) or equal_chars < total*2/3:
            additional.append(word)
        last_point = word.get_end_exclusives()

    while equal_mappings:
        following = equal_mappings.popleft()
        if following.seq1_range.is_empty:
            continue
        scan_word(following.get_starts(), following)
        scan_word(following.get_end_exclusives().delta(-1), following)
    return merge_sequence_diffs(sequence_diffs, additional)


def merge_sequence_diffs(sequence_diffs1, sequence_diffs2):
    left, right = deque(sequence_diffs1), deque(sequence_diffs2)
    result = []
    while left or right:
        if left and (not right or left[0].seq1_range.start < right[0].seq1_range.start):
            following = left.popleft()
        else:
            following = right.popleft()
        if result and result[-1].seq1_range.end_exclusive >= following.seq1_range.start:
            result[-1] = result[-1].join(following)
        else:
            result.append(following)
    return result


def remove_very_short_matching_lines_between_diffs(sequence1, sequence2, sequence_diffs):
    diffs = sequence_diffs
    if not diffs:
        return diffs
    # The upstream do/while permits eleven passes, including its initial pass.
    for _ in range(11):
        repeat = False
        result = [diffs[0]]
        for cur in diffs[1:]:
            previous = result[-1]
            unchanged = Range(previous.seq1_range.end_exclusive, cur.seq1_range.start)
            text = sequence1.get_text(unchanged).translate(_WITHOUT_WHITESPACE)
            if len(text) <= 4 and (previous.seq1_range.length+previous.seq2_range.length > 5
                                   or cur.seq1_range.length+cur.seq2_range.length > 5):
                repeat = True
                result[-1] = previous.join(cur)
            else:
                result.append(cur)
        diffs = result
        if not repeat:
            break
    return diffs


def remove_very_short_matching_text_between_long_diffs(sequence1, sequence2, sequence_diffs):
    diffs = sequence_diffs
    if not diffs:
        return diffs

    def should_join(before, after):
        unchanged = Range(before.seq1_range.end_exclusive, after.seq1_range.start)
        if sequence1.count_lines_in(unchanged) > 5 or unchanged.length > 500:
            return False
        text = sequence1.get_text(unchanged).strip(_JS_WHITESPACE)
        if len(text) > 20 or len(_LINE_BREAK.split(text)) > 1:
            return False

        def weight(diff):
            size1 = min(sequence1.count_lines_in(diff.seq1_range)*40+diff.seq1_range.length, 130)
            size2 = min(sequence2.count_lines_in(diff.seq2_range)*40+diff.seq2_range.length, 130)
            return (size1**1.5 + size2**1.5)**1.5

        return weight(before)+weight(after) > (130**1.5)**1.5 * 1.3

    for _ in range(11):
        repeat = False
        result = [diffs[0]]
        for cur in diffs[1:]:
            if should_join(result[-1], cur):
                repeat = True
                result[-1] = result[-1].join(cur)
            else:
                result.append(cur)
        diffs = result
        if not repeat:
            break

    result = []
    for index, cur in enumerate(diffs):
        previous = diffs[index-1] if index else None
        following = diffs[index+1] if index+1 < len(diffs) else None
        new_diff = cur

        def should_mark(text):
            return len(text) > 0 and len(text.strip(_JS_WHITESPACE)) <= 3 and cur.seq1_range.length+cur.seq2_range.length > 100

        full = sequence1.extend_to_full_lines(cur.seq1_range)
        prefix = sequence1.get_text(Range(full.start, cur.seq1_range.start))
        if should_mark(prefix):
            new_diff = new_diff.delta_start(-len(prefix))
        suffix = sequence1.get_text(Range(cur.seq1_range.end_exclusive, full.end_exclusive))
        if should_mark(suffix):
            new_diff = new_diff.delta_end(len(suffix))
        start = previous.get_end_exclusives() if previous else OffsetPair(0, 0)
        end = following.get_starts() if following else OffsetPair(_MAX_SAFE_INTEGER, _MAX_SAFE_INTEGER)
        available = Diff(Range(start.offset1, end.offset1), Range(start.offset2, end.offset2))
        current = new_diff.intersect(available)
        if result and current.get_starts() == result[-1].get_end_exclusives():
            result[-1] = result[-1].join(current)
        else:
            result.append(current)
    return result
