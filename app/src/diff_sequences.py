"""Sequence primitives and solvers ported from the upstream advanced diff.

Copyright (c) Microsoft Corporation. Licensed under the MIT License.
Source revision: 69047191fc427f2f92828279aae1d90d8eeda7ab,
defaultLinesDiffComputer/{algorithms,lineSequence,linesSliceCharSequence}.
The port retains the original scoring and tie-breaking behavior.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import struct


# ECMAScript WhiteSpace and LineTerminator, rather than Python's broader set.
JS_WHITESPACE = '\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def js_trim(text):
    return text.strip(JS_WHITESPACE)


def utf16_units(text):
    """Represent every UTF-16 code unit as one Python character."""
    if text.isascii():
        return text
    data = text.encode('utf-16-le', errors='surrogatepass')
    return ''.join(map(chr, struct.unpack(f'<{len(data)//2}H', data)))


@dataclass(frozen=True, slots=True)
class Range:
    start: int
    end_exclusive: int

    def __post_init__(self):
        if self.start > self.end_exclusive:
            raise ValueError('Invalid diff range.')

    @property
    def length(self):
        return self.end_exclusive - self.start

    @property
    def is_empty(self):
        return self.start == self.end_exclusive

    def delta(self, offset):
        return Range(self.start + offset, self.end_exclusive + offset)

    def delta_start(self, offset):
        return Range(self.start + offset, self.end_exclusive)

    def delta_end(self, offset):
        return Range(self.start, self.end_exclusive + offset)

    def join(self, other):
        return Range(min(self.start, other.start), max(self.end_exclusive, other.end_exclusive))

    def intersect(self, other):
        start, end = max(self.start, other.start), min(self.end_exclusive, other.end_exclusive)
        return Range(start, end) if start <= end else None

    def intersects(self, other):
        return max(self.start, other.start) < min(self.end_exclusive, other.end_exclusive)

    def intersects_or_touches(self, other):
        return max(self.start, other.start) <= min(self.end_exclusive, other.end_exclusive)

    def contains(self, offset):
        return self.start <= offset < self.end_exclusive

    def contains_range(self, other):
        return self.start <= other.start and other.end_exclusive <= self.end_exclusive

    def clip(self, offset):
        if self.is_empty:
            raise ValueError('Cannot clip to an empty diff range.')
        return max(self.start, min(self.end_exclusive - 1, offset))


@dataclass(frozen=True, slots=True)
class OffsetPair:
    offset1: int
    offset2: int

    def delta(self, offset):
        return OffsetPair(self.offset1 + offset, self.offset2 + offset)

    def equals(self, other):
        return self == other


OffsetPair.zero = OffsetPair(0, 0)
OffsetPair.max = OffsetPair(2**53 - 1, 2**53 - 1)


@dataclass(frozen=True, slots=True)
class Diff:
    seq1_range: Range
    seq2_range: Range

    def swap(self):
        return Diff(self.seq2_range, self.seq1_range)

    def delta(self, offset):
        return Diff(self.seq1_range.delta(offset), self.seq2_range.delta(offset))

    def delta_start(self, offset):
        return Diff(self.seq1_range.delta_start(offset), self.seq2_range.delta_start(offset))

    def delta_end(self, offset):
        return Diff(self.seq1_range.delta_end(offset), self.seq2_range.delta_end(offset))

    def join(self, other):
        return Diff(self.seq1_range.join(other.seq1_range), self.seq2_range.join(other.seq2_range))

    def intersects_or_touches(self, other):
        return self.seq1_range.intersects_or_touches(other.seq1_range) or self.seq2_range.intersects_or_touches(other.seq2_range)

    def intersect(self, other):
        a, b = self.seq1_range.intersect(other.seq1_range), self.seq2_range.intersect(other.seq2_range)
        return Diff(a, b) if a is not None and b is not None else None

    def get_starts(self):
        return OffsetPair(self.seq1_range.start, self.seq2_range.start)

    def get_end_exclusives(self):
        return OffsetPair(self.seq1_range.end_exclusive, self.seq2_range.end_exclusive)

    @staticmethod
    def from_offset_pairs(start, end):
        return Diff(Range(start.offset1, end.offset1), Range(start.offset2, end.offset2))

    @staticmethod
    def invert(diffs, original_length):
        result = []
        previous = None
        for following in list(diffs) + [None]:
            start = previous.get_end_exclusives() if previous else OffsetPair.zero
            delta = previous.seq2_range.end_exclusive - previous.seq1_range.end_exclusive if previous else 0
            end = following.get_starts() if following else OffsetPair(original_length, original_length + delta)
            result.append(Diff.from_offset_pairs(start, end))
            previous = following
        return result


def dynamic_programming(sequence1, sequence2, equality_score=None, check_timeout=None):
    """Upstream weighted LCS, including its consecutive-match bonus and ties."""
    n, m = sequence1.length, sequence2.length
    if not n or not m:
        return [Diff(Range(0, n), Range(0, m))]
    a = [sequence1.get_element(i) for i in range(n)]
    b = [sequence2.get_element(i) for i in range(m)]
    # Only the traceback directions need the complete matrix. Scores and run
    # lengths depend on the preceding row and the preceding cell in this row.
    directions = bytearray(n * m)
    previous_scores, previous_runs = [0] * m, [0] * m
    for i in range(n):
        if check_timeout:
            check_timeout()
        scores, runs = [0] * m, [0] * m
        base = i * m
        for j in range(m):
            horizontal = previous_scores[j] if i else 0
            vertical = scores[j-1] if j else 0
            if a[i] == b[j]:
                extended = previous_scores[j-1] if i and j else 0
                if i and j and directions[base-m+j-1] == 3:
                    extended += previous_runs[j-1]
                extended += equality_score(i, j) if equality_score else 1
            else:
                extended = -1
            best = horizontal if horizontal >= vertical else vertical
            if extended > best:
                best = extended
            if best == extended:
                runs[j] = (previous_runs[j-1] if i and j else 0) + 1
                directions[base+j] = 3
            elif best == horizontal:
                directions[base+j] = 1
            else:
                directions[base+j] = 2
            scores[j] = best
        previous_scores, previous_runs = scores, runs
    result = []
    last_a, last_b = n, m
    i, j = n-1, m-1
    while i >= 0 and j >= 0:
        direction = directions[i*m+j]
        if direction == 3:
            if i+1 != last_a or j+1 != last_b:
                result.append(Diff(Range(i+1, last_a), Range(j+1, last_b)))
            last_a, last_b = i, j
            i, j = i-1, j-1
        elif direction == 1:
            i -= 1
        else:
            j -= 1
    if last_a or last_b:
        result.append(Diff(Range(0, last_a), Range(0, last_b)))
    result.reverse()
    return result


@dataclass(slots=True)
class _Snake:
    previous: object
    x: int
    y: int
    length: int


def myers(sequence1, sequence2, check_timeout=None):
    """Upstream Myers implementation with the same diagonal/path tie choices."""
    n, m = sequence1.length, sequence2.length
    if not n or not m:
        return [Diff(Range(0, n), Range(0, m))]
    a = [sequence1.get_element(i) for i in range(n)]
    b = [sequence2.get_element(i) for i in range(m)]

    def snake(x, y):
        while x < n and y < m and a[x] == b[y]:
            x, y = x+1, y+1
        return x

    initial = snake(0, 0)
    furthest = {0: initial}
    paths = {0: _Snake(None, 0, 0, initial) if initial else None}
    distance = 0
    complete = False
    while not complete:
        distance += 1
        if check_timeout:
            check_timeout()
        lower = -min(distance, m + distance % 2)
        upper = min(distance, n + distance % 2)
        for diagonal in range(lower, upper+1, 2):
            top = -1 if diagonal == upper else furthest.get(diagonal+1, 0)
            left = -1 if diagonal == lower else furthest.get(diagonal-1, 0) + 1
            x = top if top >= left else left
            if x > n:
                x = n
            y = x - diagonal
            if x > n or y > m:
                continue
            end = snake(x, y)
            furthest[diagonal] = end
            previous = paths.get(diagonal+1) if x == top else paths.get(diagonal-1)
            paths[diagonal] = _Snake(previous, x, y, end-x) if end != x else previous
            if end == n and end-diagonal == m:
                complete = True
                break
    path = paths.get(diagonal)
    last_a, last_b = n, m
    result = []
    while True:
        end_a, end_b = (path.x + path.length, path.y + path.length) if path else (0, 0)
        if end_a != last_a or end_b != last_b:
            result.append(Diff(Range(end_a, last_a), Range(end_b, last_b)))
        if path is None:
            break
        last_a, last_b = path.x, path.y
        path = path.previous
    result.reverse()
    return result


class LineSequence:
    def __init__(self, trimmed_hash, lines):
        self.trimmed_hash = trimmed_hash
        self.lines = [utf16_units(line) for line in lines]

    @property
    def length(self):
        return len(self.trimmed_hash)

    def get_element(self, offset):
        return self.trimmed_hash[offset] if 0 <= offset < self.length else None

    def get_boundary_score(self, offset):
        def indent(line):
            return len(line) - len(line.lstrip(' \t'))
        before = indent(self.lines[offset-1]) if offset else 0
        after = indent(self.lines[offset]) if offset < len(self.lines) else 0
        return 1000 - before - after

    def get_text(self, span):
        return '\n'.join(self.lines[span.start:span.end_exclusive])

    def is_strongly_equal(self, a, b):
        left = self.lines[a] if 0 <= a < len(self.lines) else None
        right = self.lines[b] if 0 <= b < len(self.lines) else None
        return left == right


def _word(char):
    return 97 <= char <= 122 or 65 <= char <= 90 or 48 <= char <= 57


def _upper(char):
    return 65 <= char <= 90


def _category(char):
    if char == 10:
        return 8
    if char == 13:
        return 7
    if char in (32, 9):
        return 6
    if 97 <= char <= 122:
        return 0
    if 65 <= char <= 90:
        return 1
    if 48 <= char <= 57:
        return 2
    if char == -1:
        return 3
    if char in (44, 59):
        return 5
    return 4


class CharSequence:
    def __init__(self, lines, span, consider_whitespace_changes=True):
        self.range = span
        self.elements = []
        self.first_element_offset_by_line_idx = [0]
        self.line_start_offsets = []
        self.trimmed_ws_lengths_by_line_idx = []
        start_row, start_column, end_row, end_column = span
        for row in range(start_row, end_row+1):
            line = utf16_units(lines[row])
            line_start = start_column if row == start_row else 0
            line = line[line_start:]
            self.line_start_offsets.append(line_start)
            trim = 0
            if not consider_whitespace_changes:
                trimmed = line.lstrip(JS_WHITESPACE)
                trim = len(line) - len(trimmed)
                line = trimmed.rstrip(JS_WHITESPACE)
            self.trimmed_ws_lengths_by_line_idx.append(trim)
            length = min(end_column-line_start-trim, len(line)) if row == end_row else len(line)
            self.elements.extend(ord(line[i]) for i in range(max(0, length)))
            if row < end_row:
                self.elements.append(10)
                self.first_element_offset_by_line_idx.append(len(self.elements))

    @property
    def length(self):
        return len(self.elements)

    def get_element(self, offset):
        return self.elements[offset] if 0 <= offset < self.length else None

    def get_text(self, span):
        return ''.join(map(chr, self.elements[span.start:span.end_exclusive]))

    def get_boundary_score(self, offset):
        previous = _category(self.elements[offset-1] if offset > 0 else -1)
        following = _category(self.elements[offset] if offset < self.length else -1)
        if previous == 7 and following == 8:
            return 0
        if previous == 8:
            return 150
        score = 0
        if previous != following:
            score += 10
            if previous == 0 and following == 1:
                score += 1
        scores = (0, 0, 0, 10, 2, 30, 3, 10, 10)
        return score + scores[previous] + scores[following]

    def translate_offset(self, offset, preference='right'):
        index = bisect_right(self.first_element_offset_by_line_idx, offset) - 1
        line_offset = offset - self.first_element_offset_by_line_idx[index]
        trim = 0 if line_offset == 0 and preference == 'left' else self.trimmed_ws_lengths_by_line_idx[index]
        return self.range[0] + index, self.line_start_offsets[index] + line_offset + trim

    def translate_range(self, span):
        start = self.translate_offset(span.start, 'right')
        end = self.translate_offset(span.end_exclusive, 'left')
        if end < start:
            start = end
        return (*start, *end)

    def find_word_containing(self, offset):
        if not 0 <= offset < self.length or not _word(self.elements[offset]):
            return None
        start, end = offset, offset
        while start > 0 and _word(self.elements[start-1]):
            start -= 1
        while end < self.length and _word(self.elements[end]):
            end += 1
        return Range(start, end)

    def find_subword_containing(self, offset):
        if not 0 <= offset < self.length or not _word(self.elements[offset]):
            return None
        start, end = offset, offset
        while start > 0 and _word(self.elements[start-1]) and not _upper(self.elements[start]):
            start -= 1
        while end < self.length and _word(self.elements[end]) and not _upper(self.elements[end]):
            end += 1
        return Range(start, end)

    def count_lines_in(self, span):
        return self.translate_offset(span.end_exclusive)[0] - self.translate_offset(span.start)[0]

    def is_strongly_equal(self, a, b):
        return self.get_element(a) == self.get_element(b)

    def extend_to_full_lines(self, span):
        starts = self.first_element_offset_by_line_idx
        index = bisect_right(starts, span.start) - 1
        end_index = bisect_left(starts, span.end_exclusive)
        return Range(starts[index] if index >= 0 else 0,
                     starts[end_index] if end_index < len(starts) else self.length)
