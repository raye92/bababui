"""Restore native tabs and cover line breaks hidden in older working projects."""
from bisect import bisect_left, bisect_right
from dataclasses import replace
from itertools import accumulate
from uuid import uuid4

from .caption import cover_end, is_cell
from .fields import rendered_value
from .structure import group_matches, group_targets, projected_groups, source_groups


def projection_changes(job, current_job, bundle, version):
    end = cover_end(current_job.native_bytes) or 0
    visible = {token.offset: token.text for group in source_groups(current_job, bundle) for token in group
               if token.text and (token.raw == b'\x09' or token.offset < end)}
    old_fields = {e.source: e for e in job.baseline.elements if e.kind == 'field'}
    field_formats = {e.source: e for e in current_job.baseline.elements if e.source in old_fields
                     and (e.uppercase, e.wrap_caption) != (old_fields[e.source].uppercase, old_fields[e.source].wrap_caption)}
    groups = []
    uppercase = False
    for index, tokens in enumerate(projected_groups(job, bundle, projection_version=version)):
        offset, positions, casing = 0, [], []
        for token in tokens:
            if token.offset < end and token.raw == b'\x12\x08':
                uppercase = True
                casing.append((offset, True))
            elif uppercase and token.raw == b'\x12\x88':
                uppercase = False
                casing.append((offset, False))
            new = visible.get(token.offset)
            if new and new != token.text and token.offset not in field_formats:
                if ((not token.text and (token.raw in (b'\x09', b'\x0a') or is_cell(token.raw)))
                        or new.casefold() == token.text.casefold()):
                    positions.append((offset, token.text, new))
            offset += len(token.text)
        if positions or casing:
            groups.append((index, positions, casing))
    return groups, field_formats


def _mapped_control(position, matches):
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


def restore_controls(job, revision, groups, field_formats):
    from app.src.review_model import map_position
    targets = _saved_group_targets(job, revision)
    starts = tuple(accumulate(map(len, targets), initial=0))
    elements = revision.elements
    element_starts = [element.start for element in elements]
    changes, case_positions, case_states = [], [], []
    for index, controls, casing in groups:
        span = job.baseline.spans[index]
        target = targets[index]
        matches = (*group_matches(span.content, target), (len(span.content), len(target), 0))
        for offset, uppercase in casing:
            case_positions.append(starts[index] + _mapped_control(offset, matches))
            case_states.append(uppercase)
        for offset, old, text in controls:
            if old:
                # Preserve a reviewer's replacement at this source position.
                matched = next((b + offset - a for a, b, size in matches
                                if a <= offset and offset + len(old) <= a + size), None)
                if matched is None:
                    continue
                position = starts[index] + matched
            else:
                position = starts[index] + _mapped_control(offset, matches)
                preceding = bisect_left(element_starts, position) - 1
                if preceding >= 0 and position < elements[preceding].end:
                    position = elements[preceding].start
            changes.append((position, position + len(old), text, span))

    formatted = []
    for element in elements:
        source = field_formats.get(element.source)
        if element.kind == 'field' and (source or case_positions):
            # A pasted occurrence can share a field reference with the cover
            # while sitting outside its uppercase formatting.
            i = bisect_right(case_positions, element.start) - 1
            uppercase = case_states[i] if i >= 0 else False
            wrap = source.wrap_caption if source else element.wrap_caption
            if (uppercase, wrap) == (element.uppercase, element.wrap_caption):
                formatted.append(element)
                continue
            element = replace(element, uppercase=uppercase, wrap_caption=wrap)
            old = revision.text[element.start:element.end]
            value = old if element.value is None else element.value
            text = rendered_value(revision.text[:element.start], value, element.name,
                                  all_caps=revision.all_caps or element.uppercase, wrap_caption=element.wrap_caption)
            if text != old:
                changes.append((element.start, element.end, text, None))
        formatted.append(element)

    changes.sort(key=lambda item: item[:2])
    ranges, insert_starts, shift = [], {}, 0
    for start, end, text, _ in changes:
        if start == end:
            insert_starts.setdefault(start, start + shift)
        ranges.append((start, end, start + shift, start + shift + len(text)))
        shift += len(text) - (end - start)

    def mapped(position, *, before=False):
        if before and position in insert_starts:
            return insert_starts[position]
        return map_position(position, ranges)

    # Move saved atom offsets separately so a control touching an element cannot
    # change its identity or cause it to absorb the new whitespace.
    result = replace(revision, elements=())
    for position, end, text, span in reversed(changes):
        if position != end or span is None:
            result = result._replace(position, end, text)
            continue
        control = replace(span, identity=uuid4().hex, content=text)
        result = result._replace(position, position, text, adopted=(control,))
        if not span.stroke_refs:
            # An unrecorded prefix belongs before the first steno, even if
            # a saved edit left empty stroke anchors at the same position.
            spans = list(result.spans)
            control_index = spans.index(control)
            prefix_index = control_index
            while (prefix_index and not spans[prefix_index - 1].content
                   and spans[prefix_index - 1].identity != span.identity):
                prefix_index -= 1
            if prefix_index != control_index:
                spans.insert(prefix_index, spans.pop(control_index))
                result = replace(result, spans=tuple(spans))
    result = replace(result, elements=tuple(replace(
        e, start=mapped(e.start, before=e.start == e.end),
        end=mapped(e.end, before=True)) for e in formatted))
    return result, mapped


def restore_control_review(review, original, incoming, original_map, incoming_map):
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
