"""Review decisions over exact structured revision ranges, independent of Qt."""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
import re
from unicodedata import category
from app.src import advanced_diff
from app.src.casecat.elements import QA_SYMBOL

GROUPING_VERSION = 2


@dataclass(frozen=True)
class Suggestion:
    original: object
    incoming: object
    ranges: tuple  # (original start/end, incoming start/end), Python character offsets
    kind: str = 'text'
    field: str | None = None
    highlights: tuple | None = None  # Explicit display ownership after a manual edit.
    definitions: tuple = ()  # Field definitions introduced by this manual amendment.


def same_passage(left, right, span):
    """Compare wording and native elements relative to the start of each passage."""
    a, b, c, d = span
    if b-a != d-c or left.text[a:b] != right.text[c:d]:
        return False

    def elements(revision, start, end):
        return [replace(e, start=e.start-start, end=e.end-start)
                for e in revision.elements if e.start < end and start < e.end]
    return elements(left, a, b) == elements(right, c, d)


def preview_context(text, start, end):
    """Return the edit card's unescaped text on either side of a change."""
    left = text.rfind('\n', 0, start) + 1
    right = text.find('\n', end)
    if right < 0:
        right = len(text)
    before = list(re.finditer(r'\S+', text[left:start]))
    after = list(re.finditer(r'\S+', text[end:right]))
    prefix = '… ' + text[left + before[-8].start():start] if len(before) > 8 else text[left:start]
    suffix = text[end:end + after[7].end()] + ' …' if len(after) > 8 else text[end:right]
    return prefix, suffix


def word_context(text, start, end):
    """Count the characters needed on either side to include whole words."""
    def word_char(char):
        return char.isalnum() or char in "_'’‐‑-" or category(char).startswith('M')

    first, last = start, end
    if start < len(text) and word_char(text[start]):
        while first and word_char(text[first - 1]):
            first -= 1
    if end and word_char(text[end - 1]):
        while last < len(text) and word_char(text[last]):
            last += 1
    return start - first, last - end


def preview_ranges(change):
    """Include shared letters in replacement highlights without changing the decision."""
    if change.highlights is not None:
        return change.highlights
    if change.kind == 'word_join':
        a, _, c, _ = change.ranges[0]
        _, b, _, d = change.ranges[-1]
    elif len(change.ranges) == 1:
        (a, b, c, d), = change.ranges
    else:
        return change.ranges
    original, incoming = change.original.text, change.incoming.text
    left_a, right_a = word_context(original, a, b)
    left_b, right_b = word_context(incoming, c, d)
    if a == b or c == d:
        # Joining or splitting a word can be a one-sided character edit.
        left, right, changed = ((left_a, right_a, incoming[c:d]) if a == b else
                                (left_b, right_b, original[a:b]))
        if (not left or not right or '\n' in changed or '\r' in changed
                or not any(char.isspace() for char in changed)):
            return change.ranges
    for _ in range(max(left_a, left_b)):
        if not a or not c or original[a-1] != incoming[c-1]:
            break
        a, c = a-1, c-1
    for _ in range(max(right_a, right_b)):
        if b == len(original) or d == len(incoming) or original[b] != incoming[d]:
            break
        b, d = b+1, d+1
    return ((a, b, c, d),)


def preview_start(change, side):
    """Locate the first visible highlight, or the boundary of a one-sided edit."""
    offset = 0 if side == 'original' else 2
    text = getattr(change, side).text
    for span in preview_ranges(change):
        start, end = span[offset:offset + 2]
        while start < end and text[start] == '\n':
            start += 1
        if start < end:
            return start
    return change.ranges[0][offset]


def distance_to_ranges(ranges, side, start, end):
    """Distance from a row or caret to the decision's half-open source ranges."""
    offset = 0 if side == 'original' else 2
    closest = float('inf')
    for span in ranges:
        a, b = span[offset:offset + 2]
        if a == b:
            distance = max(start - a, a - end, 0)
        else:
            distance = max(start - (b - 1), a - max(start, end - 1), 0)
        closest = min(closest, distance)
    return closest


def _layout(line):
    match = re.match(r'^(\s*)([QA])([ \t]+)(.*)$', line)
    if match:
        return match[1], match[2], match[3], match[4]
    return line[:len(line)-len(line.lstrip(' \t'))], '', '', line.lstrip(' \t')


def _paragraph_ops(left, right):
    """Align transcript bodies with advanced diff, then place structural-only lines."""
    from app.src.off_record import is_off_record_note
    from app.src.suggestion_filter import _paragraphs
    notes_a = [i for i, line in enumerate(left) if is_off_record_note(line)]
    notes_b = [i for i, line in enumerate(right) if is_off_record_note(line)]
    if notes_a and len(notes_a) == len(notes_b):
        result, i, j = [], 0, 0
        for a, b in zip(notes_a, notes_b):
            result.extend((tag, x+i, y+i, z+j, w+j)
                          for tag, x, y, z, w in _paragraph_ops(left[i:a], right[j:b]))
            result.append(('equal' if left[a] == right[b] else 'replace', a, a+1, b, b+1))
            i, j = a+1, b+1
        result.extend((tag, x+i, y+i, z+j, w+j)
                      for tag, x, y, z, w in _paragraph_ops(left[i:], right[j:]))
        return result
    bodies = {line: _paragraphs(line, byline_context=False)[0][3]
              for line in set(left) | set(right)}
    substantive = {line: any(c.isalnum() for c in body) for line, body in bodies.items()}
    aa = [i for i, line in enumerate(left) if substantive[line]]
    bb = [i for i, line in enumerate(right) if substantive[line]]
    result, previous_a, previous_b = [], 0, 0

    def structure(a, b):
        result.extend((tag, i+previous_a, j+previous_a, k+previous_b, l+previous_b)
                      for tag, i, j, k, l in advanced_diff.paragraph_ops(
                          left[previous_a:a], right[previous_b:b]))

    for tag, i, j, k, l in advanced_diff.paragraph_ops(
            [bodies[left[x]] for x in aa], [bodies[right[x]] for x in bb]):
        runs = [('equal', x, x+1, y, y+1) for x, y in zip(range(i, j), range(k, l))] if tag == 'equal' else [(tag, i, j, k, l)]
        for op, x, y, z, w in runs:
            a = aa[x] if x < len(aa) else len(left)
            b = bb[z] if z < len(bb) else len(right)
            structure(a, b)
            end_a = aa[y-1]+1 if y > x else a
            end_b = bb[w-1]+1 if w > z else b
            result.append((op, a, end_a, b, end_b))
            previous_a, previous_b = end_a, end_b
    structure(len(left), len(right))
    return result


def _continuation_prefix(line, labels):
    """Separate a source turn marker from the literal whitespace before its first word."""
    question_or_answer = QA_SYMBOL.match(line)
    speaker = labels.match(line)
    prefix = 0
    if question_or_answer:
        prefix = question_or_answer.end()
    elif speaker and not speaker['prefix'].strip():
        prefix = speaker.end()
        prefix += min(2, len(line[prefix:]) - len(line[prefix:].lstrip(' ')))
    body = line[prefix:]
    return prefix, body[:len(body) - len(body.lstrip(' \t'))]


def _prepare_continuations(original, old, new, candidates, sources, labels):
    prefixes = [_continuation_prefix(line, labels) for line in old]
    unmatched = candidates - sources.keys()
    if unmatched:
        # A split or merge has no one-to-one paragraph pair. Follow the first
        # word through the character diff to keep an authored source indent.
        target = '\n'.join(new)
        edits = text_edits(original.text, target)
        ends = [b for _, b, _, _ in edits]
        starts = [0, *(m.end() for m in re.finditer('\n', target))]
        by_word = {starts[j] + 10: j for j in unmatched}
        by_break = {starts[j] - 1: j for j in unmatched}

        def retained(position):
            index = bisect_right(ends, position)
            if index < len(edits) and edits[index][0] <= position:
                return None
            return position + (edits[index-1][3] - ends[index-1] if index else 0)

        start = 0
        for i, (line, (prefix, indent)) in enumerate(zip(old, prefixes)):
            word = start + prefix + len(indent)
            if word < start + len(line):
                mapped = retained(word)
                j = by_word.get(mapped)
                if j is None and start:
                    boundary = by_break.get(retained(start - 1))
                    if mapped is None or bisect_right(starts, mapped) - 1 == boundary:
                        j = boundary
                if j is not None:
                    sources[j] = i
            start += len(line) + 1

    inherited = set()
    for j in candidates:
        source = sources.get(j)
        prefix, indent = prefixes[source] if source is not None else (0, '')
        new[j] = indent + new[j][10:]
        if source is None or prefix:
            inherited.add(j)
    return inherited


def propose(original, text, *, normalize_continuations=None, labels=None):
    """Keep existing paragraph indentation and generated Q/A label spacing."""
    from app.src.suggestion_filter import LABEL
    from shared.transcript_formatting import TranscriptFormatter

    old = original.text.split('\n')
    new = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    labels = labels or LABEL
    continuations = set()
    if normalize_continuations:
        continuations = {j for j, line in enumerate(new) if j and re.match(r'^ {10}\S', line)
                         and not labels.match(line) and not line[10:].startswith(('(', '['))
                         and not TranscriptFormatter.structural_line.fullmatch(line.strip())}
    sources = {}
    # Use normalized labels for matching, but never write normalized body text.
    aa = [(q + ' ' + body).strip() for _, q, _, body in map(_layout, old)]
    bb = [(q + ' ' + body).strip() for _, q, _, body in map(_layout, new)]
    for _, a, b, c, d in _paragraph_ops(aa, bb):
        if b-a == d-c:
            for i, j in zip(range(a, b), range(c, d)):
                if j in continuations:
                    sources[j] = i
                    continue
                indent, label, space, _ = _layout(old[i])
                new_indent, new_label, new_space, body = _layout(new[j])
                if normalize_continuations and not new_indent and body and not labels.match(new[j]):
                    prefix, literal_indent = _continuation_prefix(old[i], labels)
                    if prefix:
                        source_body = old[i][prefix + len(literal_indent):]
                        # An initial "A " can be part of the testimony or a shorthand answer label.
                        marker = new_label + new_space
                        if (not new_label or new[j] == source_body or
                                (new_space == ' ' and source_body.startswith(marker) and not body.startswith(marker))):
                            new[j] = literal_indent + new[j]
                            continue
                new[j] = indent + new_label + (space if label and new_label else new_space) + body
    if continuations:
        continuations = _prepare_continuations(original, old, new, continuations, sources, labels)
    text = '\n'.join(new)
    raw = text_edits(original.text, text, labels=labels)
    revision = original.revise(text, edits=raw)
    return normalize_continuations(revision, continuations) if continuations else revision


def _token_edits(a, b, start, end, ns, ne):
    """Compatibility adapter for callers comparing an exact source slice."""
    return [(i+start, j+start, k+ns, l+ns)
            for i, j, k, l in advanced_diff.text_edits(a[start:end], b[ns:ne])]


def _inner_edits(original, incoming):
    """Keep equivalent wording edits outside unchanged native Q/A symbols."""
    edits = advanced_diff.text_edits(original, incoming)
    for index, (a, b, c, d) in enumerate(edits):
        if (a == b) == (c == d):
            continue
        line_start = original.rfind('\n', 0, a) + 1
        symbol = QA_SYMBOL.match(original, line_start)
        if not symbol:
            continue
        padding = original[a:symbol.end()]
        if not padding.isspace():
            continue
        incoming_start = c - (a - line_start)
        if incoming_start < 0 or not incoming.startswith(symbol[0], incoming_start):
            continue
        if incoming_start > 0 and incoming[incoming_start-1] != '\n':
            continue
        # Slide the edit over identical spaces without crossing the next edit.
        shift = len(padding)
        next_a, next_c = edits[index+1][::2] if index+1 < len(edits) else (len(original), len(incoming))
        if (b+shift <= next_a and d+shift <= next_c
                and original[b:b+shift] == incoming[d:d+shift] == padding):
            edits[index] = (a+shift, b+shift, c+shift, d+shift)
    return edits


def text_edits(original, incoming, *, labels=None):
    from app.src.spoken_edits import isolate_bylines, passage_edits, refine
    from app.src.suggestion_filter import LABEL
    labels = labels or LABEL
    raw = passage_edits(original, incoming, labels, _inner_edits)
    raw, _ = refine(original, incoming, raw, labels, _inner_edits)
    return isolate_bylines(original, incoming, raw)


def _attribution_span(text, start, end):
    from app.src.suggestion_filter import LABEL
    line_start = text.rfind('\n', 0, start) + 1
    line_end = text.find('\n', start)
    label = LABEL.match(text[line_start:line_end if line_end >= 0 else len(text)])
    if label:
        a, b = (line_start + i for i in label.span('name'))
        if a <= start <= end <= b:
            return a, b
    return None


_DOUBLE_QUOTES = tuple(re.compile(pattern) for pattern in (
    r'(?<!\w)"(?=[^\s"])[^"\r\n]+(?<!\s)"(?!\w)',
    r'“(?=[^\s”])[^“”\r\n]+(?<!\s)”',
))
_SINGLE_QUOTES = ((re.compile("['\r\n]"), "'", "'"), (re.compile('[‘’\r\n]'), '‘', '’'))
_LEADING_APOSTROPHE = re.compile(r"(?:\d{2}s|bout|cause|em|round|til|tis|twas)\b(?!['’])", re.I)


def _change_owner(changes, side):
    spans = sorted((span[side], span[side + 1], index)
                   for index, change in enumerate(changes) if change.kind == 'text'
                   for span in change.ranges if span[side] < span[side + 1])
    starts = [start for start, _, _ in spans]

    def owner(position):
        index = bisect_right(starts, position) - 1
        if index >= 0 and position < spans[index][1]:
            return spans[index][2]

    return owner


def _quotation_pairs(text, owner):
    for pattern in _DOUBLE_QUOTES:
        for quote in pattern.finditer(text):
            yield quote.start(), quote.end() - 1
    for pattern, opening_mark, closing_mark in _SINGLE_QUOTES:
        if opening_mark not in text:
            continue
        opening = None
        for match in pattern.finditer(text):
            mark = match[0]
            position = match.start()
            if mark in '\r\n':
                opening = None
                continue
            before = text[position-1:position] if position else ''
            after = text[position+1:position+2]
            if (mark == opening_mark and not before.isalnum() and after
                    and not after.isspace() and after != closing_mark):
                if not _LEADING_APOSTROPHE.match(text, position+1):
                    opening = position
            elif (mark == closing_mark and opening is not None and before
                  and not before.isspace() and not after.isalnum()):
                # An unchanged possessive inside a newly quoted phrase is not
                # its closing delimiter when there is a changed one later.
                if before.lower() == 's' and owner(opening) is not None and owner(position) is None:
                    continue
                yield opening, position
                opening = None


def _split_at_unchanged(change, start, end, new_start, new_end):
    """Separate two edits on either side of an exact, intact separator."""
    (a, b, c, d), = change.ranges
    left, right = change.original.text, change.incoming.text
    if (not (a <= start < end <= b and c <= new_start < new_end <= d)
            or left[start:end] != right[new_start:new_end]):
        return (change,)
    for revision, first, last in ((change.original, a, b), (change.incoming, c, d)):
        if any(first < element.end and last > element.start for element in revision.elements):
            return (change,)
    return tuple(replace(change, ranges=(span,))
                 for span in ((a, start, c, new_start), (end, b, new_end, d))
                 if left[span[0]:span[1]] != right[span[2]:span[3]])


def _separate_adjacent_quotes(changes, left_pairs, right_pairs):
    """Keep a shared gap between a closing quote and the next opening quote."""
    if not left_pairs and not right_pairs:
        return changes
    left_starts, left_ends = zip(*left_pairs) if left_pairs else ((), ())
    right_starts, right_ends = zip(*right_pairs) if right_pairs else ((), ())
    left_starts, left_ends = set(left_starts), set(left_ends)
    right_starts, right_ends = set(right_starts), set(right_ends)
    result = []
    for change in changes:
        if change.kind != 'text':
            result.append(change)
            continue
        (a, b, c, d), = change.ranges
        left_quotes = a in left_ends and b-1 in left_starts
        right_quotes = c in right_ends and d-1 in right_starts
        if left_quotes or right_quotes:
            start, end = (a+1, b-1) if left_quotes else (a, b)
            new_start, new_end = (c+1, d-1) if right_quotes else (c, d)
            separator = change.original.text[start:end]
            if separator and not separator.strip(' ,;:'):
                result.extend(_split_at_unchanged(change, start, end, new_start, new_end))
                continue
        result.append(change)
    return result


def _split_word_bounds(split, start, end, joined, point):
    """Identify a space edit between two fragments of a single resulting word."""
    if (start == end or split[start:end].strip(' ')
            or not (0 < start < end < len(split) and 0 < point < len(joined))
            or not (split[start-1] + split[end] + joined[point-1:point+1]).isalpha()):
        return None
    head, _ = word_context(split, start-1, start)
    _, tail = word_context(split, end, end+1)
    left, right = word_context(joined, point, point)
    x, y = start-1-head, end+1+tail
    z, w = point-left, point+right
    if split[x:start].isalpha() and split[end:y].isalpha() and joined[z:w].isalpha():
        return (x, y), (z, w)


def _word_join_bounds(left, right, change):
    if change.kind != 'text':
        return None
    (a, b, c, d), = change.ranges
    if c == d:
        return _split_word_bounds(left, a, b, right, c)
    if a == b:
        reverse = _split_word_bounds(right, c, d, left, a)
        if reverse:
            return reverse[::-1]


def _separate_edits_after_join(left, right, changes):
    result = []
    for change in changes:
        bounds = _word_join_bounds(left, right, result[-1]) if result else None
        if bounds and change.kind == 'text':
            (a, b, c, d), = change.ranges
            (first, end), (new_first, new_end) = bounds
            if first <= a <= end < b and new_first <= c <= new_end < d:
                # The engine can absorb a short shared separator into a larger
                # replacement. Split only at the same space or punctuation on
                # both sides, between the joined word and the following text.
                gap = re.match(r'[.!?,;:]? +', left[end:b])
                if gap and left[a:end] != right[c:new_end]:
                    size = len(gap[0])
                    result.extend(_split_at_unchanged(change, end, end+size, new_end, new_end+size))
                    continue
        result.append(change)
    return result


def _word_join_links(left, right, changes):
    def within_word(text, start, end, bounds):
        first, last = bounds
        if not first <= start <= last:
            return False
        # A letter correction at the end may already include punctuation.
        return end <= last or (end == last + 1 and text[last:end] in ',.;:!?')

    for index, change in enumerate(changes):
        bounds = _word_join_bounds(left, right, change)
        if bounds is None:
            continue
        for step in (-1, 1):
            neighbor = index + step
            while 0 <= neighbor < len(changes) and changes[neighbor].kind == 'text':
                (x, y, z, w), = changes[neighbor].ranges
                if not (within_word(left, x, y, bounds[0]) and within_word(right, z, w, bounds[1])):
                    break
                old_letters = [ch for ch in left[x:y] if ch.isalpha()]
                new_letters = [ch for ch in right[z:w] if ch.isalpha()]
                if old_letters == new_letters:
                    break
                yield index, neighbor
                neighbor += step


def _group_decisions(left, right, changes):
    """Group dependent edits while preserving the original native ranges."""
    if not any(change.kind == 'text' for change in changes):
        return changes
    changes = _separate_edits_after_join(left, right, changes)
    left_pairs = tuple(_quotation_pairs(left, _change_owner(changes, 0)))
    right_pairs = tuple(_quotation_pairs(right, _change_owner(changes, 2)))
    changes = _separate_adjacent_quotes(changes, left_pairs, right_pairs)
    parents = list(range(len(changes)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    grouped = False
    for a, b in _word_join_links(left, right, changes):
        parents[root(b)] = root(a)
        grouped = True
    quotations = set()
    for pairs, side in ((left_pairs, 0), (right_pairs, 2)):
        if not pairs:
            continue
        owner = _change_owner(changes, side)
        for start, end in pairs:
            a, b = owner(start), owner(end)
            if a is not None and b is not None:
                quotations.update((a, b))
                parents[root(b)] = root(a)
    if not grouped and not quotations:
        return changes

    groups = {}
    for index in range(len(changes)):
        groups.setdefault(root(index), []).append(index)
    result = []
    for indices in groups.values():
        change = changes[indices[0]]
        if len(indices) > 1 or indices[0] in quotations:
            ranges = tuple(span for index in indices for span in changes[index].ranges)
            kind = 'word_join' if quotations.isdisjoint(indices) else 'quotation'
            change = replace(change, kind=kind, ranges=ranges)
        result.append(change)
    return result


def _atomic_intervals(revision, labels, start, end):
    spans = set(labels)
    spans.update((e.start, e.end) for e in revision.elements if e.start < end and start < e.end)
    intervals = []
    for a, b in sorted(spans):
        a, b = max(start, a), min(end, b)
        if a >= b:
            continue
        if intervals and a < intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], b))
        else:
            intervals.append((a, b))
    return intervals


def _expanded_text_edits(original, incoming, left_start, left_end, right_start, right_end, raw):
    old, new = original.text, incoming.text
    if not raw:
        return []
    old_labels, new_labels = set(), set()
    for a, b, c, d in raw:
        left, right = _attribution_span(old, a, b), _attribution_span(new, c, d)
        if left and right:
            old_labels.add(left)
            new_labels.add(right)
    atoms = (_atomic_intervals(original, old_labels, left_start, left_end),
             _atomic_intervals(incoming, new_labels, right_start, right_end))
    if not any(atoms):
        return raw

    def padding(a, c, direction, available):
        distance = 0
        while distance <= available:
            step = 0
            for position, spans in zip((a, c), atoms):
                index = bisect_left(spans, (position,)) - 1
                if index >= 0 and position < spans[index][1]:
                    first, last = spans[index]
                    step = max(step, last-position if direction == 1 else position-first)
            if not step:
                break
            distance += step
            a += direction * step
            c += direction * step
        return distance

    # Only an unchanged gap can separate two decisions. Keep its boundaries
    # aligned on both sides and merge changes when no cut leaves atoms intact.
    expanded = []
    first = None
    old_end, new_end = left_start, right_start
    for a, b, c, d in [*raw, (left_end, left_end, right_end, right_end)]:
        gap = a-old_end
        front = padding(old_end, new_end, 1, gap)
        back = padding(a, c, -1, gap)
        if front + back <= gap:
            if first is not None:
                expanded.append((first[0], old_end+front, first[1], new_end+front))
            first = (a-back, c-back)
        old_end, new_end = b, d
    return expanded


def _initial_edits(original, incoming):
    from app.src.suggestion_filter import speaker_replacements
    speakers = tuple(speaker_replacements(original, incoming))
    # Diff the text between speaker decisions so even a completely rewritten
    # answer can be accepted independently of its attribution.
    a, b = original.text, incoming.text
    raw = []
    previous_a = previous_c = 0
    for start, end, ns, ne in (*speakers, (len(a), len(a), len(b), len(b))):
        raw.extend((x+previous_a, y+previous_a, z+previous_c, w+previous_c) for x,y,z,w in
                   _inner_edits(a[previous_a:start], b[previous_c:ns]))
        if (start, end, ns, ne) in speakers:
            raw.append((start, end, ns, ne))
        previous_a, previous_c = end, ne
    return speakers, raw


def suggestions(original, incoming, *, legacy=False):
    if original == incoming:
        return []
    return _decisions(original, incoming, *_initial_edits(original, incoming), legacy=legacy)


def review_generations(original, incoming):
    """Share the original paragraph diff when upgrading saved decisions."""
    if original == incoming:
        return (), ()
    speakers, raw = _initial_edits(original, incoming)
    return tuple(tuple(_decisions(original, incoming, speakers, raw, legacy=legacy)) for legacy in (True, False))


def _decisions(original, incoming, speakers, raw, *, legacy):
    from app.src.suggestion_filter import _label_pattern
    from app.src.casecat.elements import speaker_number
    from app.src.spoken_edits import atomic_boundaries, byline_moves, isolate_bylines, refine

    a, b = original.text, incoming.text
    roles, moves = set(), []
    if not legacy:
        labels = _label_pattern(e for rev in (original, incoming) for e in rev.elements
                                if e.kind == 'field' and speaker_number(e.name))
        raw, roles = refine(a, b, raw, labels, _inner_edits, speakers)
        raw = isolate_bylines(a, b, raw)
        moves = byline_moves(original, incoming, raw)
    specials = {s: 'speaker' for s in speakers}
    specials.update((s, 'turn_label') for s in roles if atomic_boundaries(original, incoming, s))
    specials.update((s, 'byline_move') for move in moves for s in move)
    result = [Suggestion(original, incoming, move, 'byline_move') for move in moves]
    expanded, ordinary, fields = [], [], {}
    previous_a = previous_c = 0
    for span in (*raw, (len(a), len(a), len(b), len(b))):
        start, end, ns, ne = span
        if span not in specials and span != (len(a), len(a), len(b), len(b)):
            ordinary.append(span)
            continue
        expanded.extend(_expanded_text_edits(original, incoming, previous_a, start, previous_c, ns, ordinary))
        if span in specials and specials[span] != 'byline_move':
            result.append(Suggestion(original, incoming, (span,), specials[span]))
        previous_a, previous_c = end, ne
        ordinary = []
    left_fields = [e for e in original.elements if e.kind == 'field']
    right_fields = {(e.start, e.name): e for e in incoming.elements if e.kind == 'field'}
    for span in expanded:
        start, end, ns, ne = span
        # A diff can align a space inside a field name with the space before
        # the field. Keep a pure rename linked across all its occurrences.
        first = bisect_left(left_fields, start, key=lambda e: e.start)
        last = bisect_left(left_fields, end, key=lambda e: e.start)
        for left in left_fields[first:last]:
            right = right_fields.get((ns + (left.start - start), left.name))
            if right is None or left.end > end or right.end > ne:
                continue
            field = (left.start, left.end, right.start, right.end)
            if field == span or (same_passage(original, incoming, (start, left.start, ns, right.start))
                                 and same_passage(original, incoming, (left.end, end, right.end, ne))):
                fields.setdefault(left.name, []).append(field)
                break
        else:
            kind = 'structure' if '\n' in a[start:end] + b[ns:ne] else 'text'
            result.append(Suggestion(original, incoming, (span,), kind))
    result += [Suggestion(original, incoming, tuple(ranges), 'field', name) for name, ranges in fields.items()]
    if not result and (original.elements != incoming.elements or original.definitions != incoming.definitions):
        result.append(Suggestion(original, incoming, (), 'metadata'))
    result.sort(key=lambda s: s.ranges[0] if s.ranges else (0, 0, 0, 0))
    return _group_decisions(a, b, result)


def resolve(original, incoming, change, accept, *, defer_fields=False):
    if change.original != original or change.incoming != incoming:
        raise ValueError('This suggestion is stale. Refresh the review.')
    if change.kind == 'metadata':
        chosen = incoming if accept else original
        return chosen, chosen
    target, source = (original, incoming) if accept else (incoming, original)
    # A linked definition updates every occurrence atomically.
    if change.field:
        from app.src.casecat.fields import field_values
        value = field_values(source).get(change.field)
        if value is not None and change.field in field_values(target):
            target = target.set_field(change.field, value)
        else:
            for a, b, c, d in reversed(change.ranges):
                start, end, x, y = (a, b, c, d) if accept else (c, d, a, b)
                target = target.adopt(start, end, source, x, y, at_destination=True, exact_position=not accept)
    else:
        for a, b, c, d in reversed(change.ranges):
            start, end, x, y = (a, b, c, d) if accept else (c, d, a, b)
            # Both revisions have their own ordered stroke stream. A saved
            # proposal can place a surviving turn at a different source clock.
            target = target.adopt(start, end, source, x, y, at_destination=True,
                                  exact_position=not accept, update_fields=not defer_fields)
    original, incoming = (target, incoming) if accept else (original, target)
    if original.text == incoming.text and original.elements == incoming.elements and original.definitions == incoming.definitions:
        incoming = original
    return original, incoming


def resolve_all(original, incoming, ranges, accept):
    if not accept:
        return original, original
    if not ranges:
        return incoming, incoming
    target = original
    # Keep native audio at the destination. Apply ranges right to left and
    # defer linked field updates so they cannot shift other pending ranges.
    for a, b, c, d in sorted(ranges, reverse=True):
        target = target.adopt(a, b, incoming, c, d, at_destination=True, update_fields=False)
    chosen = replace(incoming, spans=target.spans) if target.text == incoming.text else incoming
    return chosen, chosen
