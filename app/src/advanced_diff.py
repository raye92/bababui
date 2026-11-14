"""Pure Python advanced diff with exact source-range adapters.

The MIT-derived Python pipeline preserves inner changes as review decisions.
No JavaScript engine or external process is required.
"""
from bisect import bisect_right
from functools import lru_cache
import re

from app.src.diff_algorithm import compute_inner_changes

UPSTREAM_REVISION = '69047191fc427f2f92828279aae1d90d8eeda7ab'


class DiffError(ValueError):
    """The authoritative diff could not be computed safely."""


@lru_cache(maxsize=16)
def _diff_lines(original, incoming):
    try:
        return compute_inner_changes(original or ('',), incoming or ('',))
    except (TimeoutError, MemoryError) as error:
        raise DiffError(f'Advanced diff failed: {error}') from error


def _normalized(text):
    """Return LF text and its boundary map to the exact original string."""
    if '\r' not in text:
        return text, range(len(text) + 1)
    parts, boundaries = [], [0]
    position = 0
    for match in re.finditer(r'\r\n|\r', text):
        parts.append(text[position:match.start()])
        boundaries.extend(range(position + 1, match.start() + 1))
        parts.append('\n')
        boundaries.append(match.end())
        position = match.end()
    parts.append(text[position:])
    boundaries.extend(range(position + 1, len(text) + 1))
    return ''.join(parts), boundaries


def _line_starts(text):
    return [0] + [match.end() for match in re.finditer('\n', text)]


def _position(lines, starts, row, column, *, end=False):
    line = lines[row]
    units = 0
    for index, char in enumerate(line):
        if units == column:
            return starts[row] + index
        width = 2 if ord(char) > 0xffff else 1
        if units < column < units + width:
            return starts[row] + index + int(end)
        units += width
    if units != column:
        raise DiffError('advanced diff returned an invalid UTF-16 column.')
    return starts[row] + len(line)


def _normalized_edits(a, b):
    left, right = a.split('\n'), b.split('\n')
    starts_a, starts_b = _line_starts(a), _line_starts(b)
    edits = []
    for ar, ac, br, bc, cr, cc, dr, dc in _diff_lines(tuple(left), tuple(right)):
        span = (_position(left, starts_a, ar, ac), _position(left, starts_a, br, bc, end=True),
                _position(right, starts_b, cr, cc), _position(right, starts_b, dr, dc, end=True))
        # JavaScript can locate a change between the two UTF-16 units of one
        # Unicode character. Expand only those overlapping character atoms.
        if edits and (span[0] < edits[-1][1] or span[2] < edits[-1][3]):
            previous = edits[-1]
            edits[-1] = (previous[0], max(previous[1], span[1]), previous[2], max(previous[3], span[3]))
        else:
            edits.append(span)
    return edits


def text_edits(original, incoming):
    """Return authoritative inner changes as paired Python character ranges."""
    if original == incoming:
        return []
    a, map_a = _normalized(original)
    b, map_b = _normalized(incoming)
    edits = _normalized_edits(a, b)
    result = []
    previous_a = previous_b = 0
    for x, y, z, w in edits + [(len(a), len(a), len(b), len(b))]:
        if a[previous_a:x] != b[previous_b:z]:
            raise DiffError('advanced diff inner changes do not preserve the unchanged text.')
        if '\r' in original or '\r' in incoming:
            # EOL styles are outside advanced diff's line model. Preserve them using
            # its unchanged correspondence, without another text diff.
            for match in re.finditer('\n', a[previous_a:x]):
                ai, bi = previous_a + match.start(), previous_b + match.start()
                if original[map_a[ai]:map_a[ai+1]] != incoming[map_b[bi]:map_b[bi+1]]:
                    result.append((map_a[ai], map_a[ai+1], map_b[bi], map_b[bi+1]))
        if (x, y, z, w) != (len(a), len(a), len(b), len(b)):
            result.append((map_a[x], map_a[y], map_b[z], map_b[w]))
        previous_a, previous_b = y, w
    return result


def paragraph_ops(left, right):
    """Map paragraphs using the advanced engine's inner correspondence.

    Paragraphs connected by an inner change or surviving text share one span.
    This retains split/join spans while exposing independent neighboring turns
    even when advanced diff displays them in the same outer comparison hunk.
    """
    if not left:
        return [('insert', 0, 0, 0, len(right))] if right else []
    if not right:
        return [('delete', 0, len(left), 0, 0)]
    a, b = '\n'.join(left), '\n'.join(right)
    starts_a, starts_b = _line_starts(a), _line_starts(b)
    parents = list(range(len(left) + len(right)))
    connected = set()

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    def connect(i, j):
        j += len(left)
        parents[root(j)] = root(i)
        connected.update((i, j))

    def equal(x, y, z):
        while x < y:
            i, j = bisect_right(starts_a, x) - 1, bisect_right(starts_b, z) - 1
            take = min(y-x, starts_a[i+1]-x if i+1 < len(starts_a) else len(a)-x,
                       starts_b[j+1]-z if j+1 < len(starts_b) else len(b)-z)
            # Punctuation shared with an inserted turn does not establish a
            # second paragraph partner. Exact punctuation-only rows still map.
            if any(char.isalnum() for char in a[x:x+take]) or left[i] == right[j]:
                connect(i, j)
            x, z = x + take, z + take

    edits = text_edits(a, b)
    previous_a = previous_b = 0
    for x, y, z, w in edits + [(len(a), len(a), len(b), len(b))]:
        equal(previous_a, x, previous_b)
        previous_a, previous_b = y, w
    for x, y, z, w in edits:
        if x < y and z < w:
            # A fine replacement can include punctuation from an established
            # turn plus a wholly added turn. Surviving text establishes those
            # partners first; only wholly rewritten rows need this fallback.
            rows_a = [i for i in range(bisect_right(starts_a, x)-1, bisect_right(starts_a, y-1))
                      if i not in connected]
            rows_b = [j for j in range(bisect_right(starts_b, z)-1, bisect_right(starts_b, w-1))
                      if j + len(left) not in connected]
            if not rows_a or not rows_b:
                continue
            for i in rows_a:
                connect(i, rows_b[0])
            for j in rows_b:
                connect(rows_a[0], j)
    # The terminal empty paragraph has no characters, but survives when both
    # inputs end in a newline (or are the same empty document).
    if left[-1] == right[-1] == '':
        connect(len(left)-1, len(right)-1)
    groups = {}
    for index in connected:
        group = groups.setdefault(root(index), ([], []))
        group[0 if index < len(left) else 1].append(index if index < len(left) else index-len(left))
    spans = sorted((min(aa), max(aa)+1, min(bb), max(bb)+1) for aa, bb in groups.values())
    result, i, j = [], 0, 0
    for x, y, z, w in spans + [(len(left), len(left), len(right), len(right))]:
        if x > i or z > j:
            result.append(('replace' if x > i and z > j else 'delete' if x > i else 'insert', i, x, j, z))
        if x < y or z < w:
            result.append(('equal' if left[x:y] == right[z:w] else 'replace', x, y, z, w))
        i, j = y, w
    return result
