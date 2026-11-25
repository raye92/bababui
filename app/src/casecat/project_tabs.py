"""Restore the source tabs concealed by older working projects."""
from bisect import bisect_left, bisect_right
from dataclasses import replace
from itertools import accumulate
from uuid import uuid4

from .structure import group_matches, group_targets, projected_groups


def source_tabs(job, bundle):
    groups = []
    for index, tokens in enumerate(projected_groups(job, bundle, legacy_projection=True)):
        offset, positions = 0, []
        for token in tokens:
            if token.raw == b'\x09' and not token.text:
                positions.append(offset)
            offset += len(token.text)
        if positions:
            groups.append((index, positions))
    return groups


def _mapped_tab(position, matches):
    old_end = new_end = 0
    for old, new, size in matches:
        if position <= old:
            # A zero-width native control precedes an insertion at the same
            # source boundary. If a replacement began earlier, it follows it.
            return new_end if position == old_end else new
        if position <= old + size:
            return new + position - old
        old_end, new_end = old + size, new + size
    return new_end


def _saved_group_targets(job, revision):
    try:
        return group_targets(job.with_revision(revision))
    except ValueError:
        # Older projects could contain edits too broad for native export.
        # They still open, using the saved order of their source anchors.
        indexes = {span.identity: index for index, span in enumerate(job.baseline.spans)}
        targets = [''] * len(indexes)
        current = 0
        for span in revision.spans:
            current = indexes.get(span.identity, current)
            targets[current] += span.content
        return targets


def restore_tabs(job, revision, groups):
    targets = _saved_group_targets(job, revision)
    starts = tuple(accumulate(map(len, targets), initial=0))
    elements = revision.elements
    element_starts = [element.start for element in elements]
    inserts = []
    for index, tabs in groups:
        span = job.baseline.spans[index]
        target = targets[index]
        matches = (*group_matches(span.content, target), (len(span.content), len(target), 0))
        for tab in tabs:
            position = starts[index] + _mapped_tab(tab, matches)
            preceding = bisect_left(element_starts, position) - 1
            if preceding >= 0 and position < elements[preceding].end:
                # A source tab cannot bisect the text of a relocated field.
                position = elements[preceding].start
            inserts.append((position, span))
    inserts.sort(key=lambda item: item[0])
    positions = [position for position, _ in inserts]

    def mapped(position, *, before=False):
        return position + (bisect_left if before else bisect_right)(positions, position)

    # Move saved atom offsets separately so a tab touching an element cannot
    # change its identity or cause it to absorb the new whitespace.
    result = replace(revision, elements=())
    for position, span in reversed(inserts):
        tab = replace(span, identity=uuid4().hex, content='\t')
        result = result._replace(position, position, '\t', adopted=(tab,))
        if not span.stroke_refs:
            # An unrecorded prefix belongs before the first steno, even if
            # a saved edit left empty stroke anchors at the same position.
            spans = list(result.spans)
            tab_index = spans.index(tab)
            prefix_index = tab_index
            while (prefix_index and not spans[prefix_index - 1].content
                   and spans[prefix_index - 1].identity != span.identity):
                prefix_index -= 1
            if prefix_index != tab_index:
                spans.insert(prefix_index, spans.pop(tab_index))
                result = replace(result, spans=tuple(spans))
    result = replace(result, elements=tuple(replace(
        e, start=mapped(e.start, before=e.start == e.end),
        end=mapped(e.end, before=True)) for e in elements))
    return result, mapped


def restore_notice_start(job, groups, body_start):
    starts = tuple(accumulate((len(span.content) for span in job.baseline.spans), initial=0))
    return body_start + sum(starts[index] + position < body_start
                            for index, positions in groups for position in positions)


def restore_tab_review(review, original, incoming, original_map, incoming_map):
    from app.src.notice_review import remap_review
    result = remap_review(review, original_map, incoming_map)
    if not result:
        return result
    for saved_rows, restored_rows in ((review['locations'], result['locations']),
                                     (review['evidence']['occurrences'], result['evidence']['occurrences'])):
        for saved, restored in zip(saved_rows, restored_rows):
            # Speaker evidence still describes the original label. A tab at
            # the trailing boundary must stay outside that label's range.
            restored['end'] = max(restored['start'], incoming_map(saved['end'], before=True))
    if 'pending_decisions' not in result:
        return result
    records = result['pending_decisions']
    ranges = sorted(span for record in records for span in record['ranges'])
    a = b = 0
    for end_a, next_a, end_b, next_b in (*ranges, (len(original.text), 0, len(incoming.text), 0)):
        left, right = original.text[a:end_a], incoming.text[b:end_b]
        if left != right:
            # Edits can move a retained tab across a pending range on one
            # side. Record the newly visible difference in the shared gap.
            tab_edits, x, y = [], 0, 0
            for i, j, size in (*group_matches(left, right), (len(left), len(right), 0)):
                if (x, y) != (i, j):
                    tab_edits.append([a + x, a + i, b + y, b + j])
                x, y = i + size, j + size
            records.append({'kind': 'structure', 'ranges': tab_edits, 'highlights': tab_edits})
        a, b = next_a, next_b
    return result
