"""Apply a native edit against the decision that owns each visible character."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, replace

from app.src.review_model import model_from_edits
from app.src.suggestion_filter import track_decisions
from app.src.suggestions import Suggestion, distance_to_ranges, preview_ranges, resolve, resolve_all, same_passage


@dataclass
class _Piece:
    # Lengths on the side being edited and the opposite side. A painted piece
    # may initially be unchanged context around a raw character difference.
    length: int
    opposite: int
    owner: int | None
    raw: bool
    touched: bool = False


def _pieces(model, side):
    offset = 2 if side == 'incoming' else 0
    other = 2 - offset
    changes = model.edits
    visible = defaultdict(list)
    for i, change in enumerate(changes):
        for span in preview_ranges(change):
            a, b = span[offset:offset+2]
            if a < b:
                visible[a].append((i, 1))
                visible[b].append((i, -1))
    stops = sorted(visible)
    active, boundary = {}, 0

    def gap(a, b):
        nonlocal boundary
        while a < b:
            while boundary < len(stops) and stops[boundary] <= a:
                for owner, delta in visible[stops[boundary]]:
                    active[owner] = active.get(owner, 0) + delta
                    if not active[owner]:
                        del active[owner]
                boundary += 1
            end = min(stops[boundary], b) if boundary < len(stops) else b

            def nearest(position):
                return min(active, key=lambda i: (
                    distance_to_ranges(changes[i].ranges, side, position, position), i), default=None)

            owner = next(iter(active), None)
            if len(active) > 1:
                owner = nearest(a)
                if owner != nearest(end-1):
                    # In a raw common gap, the nearest candidate can switch
                    # only once, from the change on the left to the right.
                    lo, hi = a+1, end-1
                    while lo < hi:
                        mid = (lo+hi)//2
                        if nearest(mid) == owner:
                            lo = mid+1
                        else:
                            hi = mid
                    end = lo
            yield _Piece(end-a, end-a, owner, False)
            a = end

    last = 0
    # Sort by both sides, including a deletion anchored at the very same
    # caret as the start of a following change.
    raw = sorted((s[offset], s[other], s[offset+1], s[other+1], i)
                 for i, change in enumerate(changes) for s in change.ranges)
    for a, c, b, d, i in raw:
        yield from gap(last, a)
        yield _Piece(b-a, d-c, i, True)
        last = b
    yield from gap(last, len(getattr(model, side).text))


def field_edits(before, after):
    """A linked fill can change distant occurrences, including earlier ones."""
    changes = []
    if before.definitions == after.definitions:
        return changes
    values = dict(before.definitions)
    for name, value in after.definitions:
        if value == values.get(name):
            continue
        old = [e for e in before.elements if e.kind == 'field' and e.name == name]
        new = [e for e in after.elements if e.kind == 'field' and e.name == name]
        if old and len(old) == len(new):
            changes.extend((a.start, a.end, b.start, b.end) for a, b in zip(old, new))
    return sorted(changes)


def _place_edit(pieces, start, end, inserted, affinity):
    """Update paired lengths and return only the shared edits for the opposite side."""
    positions, opposites, a, c = [], [], 0, 0
    if not pieces:
        pieces.append(_Piece(0, 0, None, False))
    for piece in pieces:
        positions.append(a)
        opposites.append(c)
        a += piece.length
        c += piece.opposite
    if not 0 <= start <= end <= a:
        raise ValueError('Invalid native review edit range.')
    if start == end and start and (affinity == 'left' or start == a):
        glyph = start-1
    else:
        glyph = start
    index = bisect_right(positions, glyph)-1
    if not a:
        # With no glyph on this side a caret is shared. An insertion follows
        # hidden opposite-side deletions at that coordinate.
        if pieces[-1].raw:
            pieces.append(_Piece(0, 0, None, False))
            positions.append(0)
            opposites.append(c)
        index = len(pieces)-1
    first = min(index, bisect_right(positions, start)-1)
    shared = []
    for i in range(first, len(pieces)):
        p = pieces[i]
        x = positions[i]
        if x >= end and i > index:
            break
        lo, hi = max(x, start), min(x+p.length, end)
        removed = max(0, hi-lo)
        added = inserted if i == index else 0
        if not (removed or added):
            continue
        if p.owner is None:
            begin = opposites[i] + (lo-x)
            shared.append((begin, begin+removed, added))
            p.opposite += added-removed
        else:
            p.raw = True
            p.touched = True
        p.length += added-removed
    return pieces[index].owner, shared


def _split_at(pieces, position, *, inside_raw=None):
    """Find a boundary within unchanged text without splitting a native change."""
    offset = 0
    for i, piece in enumerate(pieces):
        if position == offset:
            return i
        stop = offset + piece.length
        if position < stop:
            if piece.raw:
                if inside_raw is not None:
                    return i + int(inside_raw == 'end')
                raise ValueError('This edit would split an unrelated review decision.')
            length = position-offset
            pieces[i:i+1] = [replace(piece, length=length, opposite=length),
                             replace(piece, length=stop-position, opposite=stop-position)]
            return i+1
        offset = stop
    if position != offset:
        raise ValueError('Invalid native review edit location.')
    return len(pieces)


def _append_range(spans, span):
    if spans and spans[-1][1] == span[0] and spans[-1][3] == span[2]:
        a, _, c, _ = spans[-1]
        spans[-1] = (a, span[1], c, span[3])
    else:
        spans.append(span)


def _field_still_linked(name, original, incoming, ranges):
    for offset, revision in ((0, original), (2, incoming)):
        occurrences = {(e.start, e.end) for e in revision.elements if e.kind == 'field' and e.name == name}
        if any(span[offset:offset+2] not in occurrences for span in ranges):
            return False
    return True


def _updated_model(model, pieces, side, edited, opposite):
    original, incoming = (opposite, edited) if side == 'incoming' else (edited, opposite)
    raw, visible, touched = defaultdict(list), defaultdict(list), set()
    a = c = 0
    for p in pieces:
        if p.touched:
            touched.add(p.owner)
        b, d = a+p.length, c+p.opposite
        span = (c, d, a, b) if side == 'incoming' else (a, b, c, d)
        if p.owner is not None and (a != b or c != d):
            _append_range(visible[p.owner], span)
            if p.raw:
                _append_range(raw[p.owner], span)
        a, c = b, d
    if (a, c) != (len(edited.text), len(opposite.text)):
        raise ValueError('The native edit changed text outside its selected ranges.')
    edits = []
    for i, change in enumerate(model.edits):
        ranges = tuple(raw[i])
        if change.kind != 'metadata':
            if not ranges or (i in touched and all(same_passage(original, incoming, span) for span in ranges)):
                continue
        elif original.elements == incoming.elements and original.definitions == incoming.definitions:
            continue
        field = change.field
        names = change.definitions
        if i in touched and field and not _field_still_linked(field, original, incoming, ranges):
            names = tuple(sorted(set(names).union((field,))))
            field = None
        edits.append(replace(change, original=original, incoming=incoming, field=field,
                             ranges=ranges, highlights=tuple(visible[i]), definitions=names))
    if not edits:
        if original.elements == incoming.elements and original.definitions == incoming.definitions:
            incoming = original
        else:
            edits.append(Suggestion(original, incoming, (), 'metadata', highlights=()))
    return model_from_edits(original, incoming, tuple(edits))


def _metadata(review, model):
    result = dict(review) if review is not None else {
        'version': 1, 'evidence': {'speakers': {}, 'occurrences': []}, 'overrides': {}, 'locations': []}
    result['locations'] = [dict(row) for row in result['locations']]
    result['overrides'] = dict(result['overrides'])
    result['pending_decisions'] = [
        {'kind': e.kind, 'field': e.field, 'ranges': e.ranges, 'highlights': preview_ranges(e),
         'definitions': e.definitions}
        for e in model.edits]
    return result


def restore_decisions(original, incoming, records):
    """Restore grouped decisions only when the saved ranges cover every difference."""
    if not isinstance(records, (list, tuple)):
        raise ValueError('Invalid saved review decisions.')

    def checked(spans):
        if not isinstance(spans, (list, tuple)):
            raise ValueError('Invalid saved review ranges.')
        result = []
        for span in spans:
            if (not isinstance(span, (list, tuple)) or len(span) != 4 or any(type(x) is not int for x in span)
                    or not 0 <= span[0] <= span[1] <= len(original.text)
                    or not 0 <= span[2] <= span[3] <= len(incoming.text)):
                raise ValueError('Invalid saved review range.')
            result.append(tuple(span))
        return tuple(result)

    edits = []
    for record in records:
        if not isinstance(record, dict) or record.get('kind') not in (
                'text', 'structure', 'field', 'metadata', 'speaker', 'quotation', 'word_join'):
            raise ValueError('Invalid saved review decision.')
        names, field = record.get('definitions', ()), record.get('field')
        if (not isinstance(names, (tuple, list)) or any(not isinstance(k, str) for k in names)
                or field is not None and not isinstance(field, str)):
            raise ValueError('Invalid saved review field.')
        ranges, highlights = checked(record.get('ranges')), checked(record.get('highlights'))
        if (not ranges or not highlights) and record['kind'] != 'metadata':
            raise ValueError('Missing saved review range.')
        edits.append(Suggestion(original, incoming, ranges, record['kind'], field, highlights, tuple(names)))
    a = c = 0
    for x, y, z, w in sorted(span for e in edits for span in e.ranges):
        if x < a or z < c or original.text[a:x] != incoming.text[c:z]:
            raise ValueError('Saved review ranges no longer match the transcript.')
        a, c = y, w
    if original.text[a:] != incoming.text[c:]:
        raise ValueError('Saved review ranges no longer match the transcript.')
    return tuple(edits)


def _field_owners(model, resolved=None):
    return {name: i for i, e in enumerate(model.edits) if i != resolved
            for name in (*e.definitions, e.field) if name}


def _link_inserted_fields(model, pieces, revision, fields, values, *, resolved=None):
    """A shared reference uses each revision's own pending definition."""
    from app.src.casecat.fields import rendered_value
    owners = _field_owners(model, resolved)
    corrections = []
    for field in fields:
        owner = owners.get(field.name)
        value = values.get(field.name)
        if owner is None or value is None or value == field.value:
            continue
        first = _split_at(pieces, field.start)
        last = _split_at(pieces, field.end)
        start = sum(p.opposite for p in pieces[:first])
        end = start + sum(p.opposite for p in pieces[first:last])
        element = next(e for e in revision.elements if e.kind == 'field'
                       and e.name == field.name and (e.start, e.end) == (start, end))
        display = rendered_value(revision.text[:start], value, field.name,
                                 all_caps=revision.all_caps or element.uppercase, wrap_caption=element.wrap_caption)
        updated = replace(element, value=value)
        revision = replace(revision, elements=tuple(updated if e is element else e for e in revision.elements))
        revision = revision._replace(start, end, display, preserve=updated)
        pieces[first:last] = [_Piece(field.end-field.start, len(display), owner, True, True)]
        corrections.append((0, len(display), start, end))
    return revision, corrections


def edit_review(model, review, side, start, end, replacement, *, affinity=None, native_revision=None):
    """Replace Python character offsets on one side of an immutable native review.

    A selection inherits its first glyph. A caret inherits the clicked or
    approached glyph. Explicit native actions supply their resulting revision.
    """
    if side not in ('incoming', 'original') or affinity not in (None, 'left', 'right'):
        raise ValueError('Invalid native review edit target.')
    start, end = sorted((start, end))
    before = getattr(model, side)
    opposite = model.original if side == 'incoming' else model.incoming
    changed = native_revision if native_revision is not None else before.replace(start, end, replacement)
    if changed is before:
        return model, review
    linked = field_edits(before, changed)
    if linked:
        operations = linked
    else:
        if start != end:
            start, end = before.atomic_range(start, end)
        else:
            symbol = next((e for e in before.elements if e.kind == 'symbol' and e.start < start < e.end), None)
            if symbol and (before.text != changed.text or before.elements != changed.elements):
                start, end = symbol.start, symbol.end
        length = end-start + len(changed.text)-len(before.text)
        operations = [(start, end, start, start+length)]
    if native_revision is not None:
        left = right = 0
        for a, b, c, d in operations:
            if (not left <= a <= b <= len(before.text) or not right <= c <= d <= len(changed.text)
                    or before.text[left:a] != changed.text[right:c]):
                raise ValueError('The native edit changed text outside its selected ranges.')
            left, right = b, d
        if before.text[left:] != changed.text[right:]:
            raise ValueError('The native edit changed text outside its selected ranges.')
    pieces = list(_pieces(model, side))
    opposite_ops = []
    shared_definition = False
    inserted_fields = []
    definition_owner = None
    opposite_values = dict(opposite.definitions)
    for a, b, c, d in reversed(operations):
        owner, shared = _place_edit(pieces, a, b, d-c, affinity)
        if owner is not None:
            definition_owner = owner
        for lo, hi, size in reversed(shared):
            if size:
                # Adopt only the inserted fragment and its elements. Keep the
                # destination audio and defer linked definitions until all
                # earlier occurrences have been applied in their old coordinates.
                opposite = opposite.adopt(lo, hi, changed, c, d, at_destination=True,
                                          update_fields=False, exact_position=True)
                shared_definition = True
                inserted_fields.extend(e for e in changed.elements if e.kind == 'field' and c <= e.start and e.end <= d)
            elif lo != hi:
                opposite = opposite._replace(lo, hi, '')
            opposite_ops.append((lo, hi, size))
    old_values, new_values = dict(before.definitions), dict(changed.definitions)
    names = {name for name in old_values.keys() | new_values.keys() if old_values.get(name) != new_values.get(name)}
    if names and (shared_definition or not field_edits and before.elements == changed.elements
                  and before.text == changed.text):
        values = dict(opposite.definitions)
        for key in names:
            if key in new_values:
                values[key] = new_values[key]
            else:
                values.pop(key, None)
        opposite = replace(opposite, definitions=tuple(sorted(values.items())))
    elif names and definition_owner is not None:
        edits = list(model.edits)
        edit = edits[definition_owner]
        edits[definition_owner] = replace(edit, definitions=tuple(sorted(names.union(edit.definitions))))
        model = replace(model, edits=tuple(edits))
    corrections = []
    if inserted_fields:
        opposite, corrections = _link_inserted_fields(model, pieces, opposite, inserted_fields, opposite_values)
    result = _updated_model(model, pieces, side, changed, opposite)
    metadata = _metadata(review, result)
    affected = [(a, b, d-c) for a, b, c, d in operations] if side == 'incoming' else opposite_ops
    # Speaker evidence describes the original analysis. Live locations track
    # changes in incoming coordinates. A directly edited attribution is final.
    for loc in metadata['locations']:
        if any(a == b and loc['start'] < a < loc['end'] for a, b, _ in affected):
            loc['resolved'] = True
    track_decisions(metadata, [(0, size, a, b) for a, b, size in affected], incoming_changed=True)
    if side == 'original':
        for correction in corrections:
            track_decisions(metadata, [correction], incoming_changed=True)
    return result, metadata


def _reanchor_field_occurrences(model, side, operations):
    """Account for linked fills inside other decisions on the destination side."""
    pieces = list(_pieces(model, side))
    edits = list(model.edits)
    for a, b, c, d in reversed(operations):
        first = _split_at(pieces, a, inside_raw='start')
        last = _split_at(pieces, b, inside_raw='end')
        affected = pieces[first:last]
        if any(p.owner is None for p in affected):
            # The other revision can have plain text that used to read exactly
            # like this reference. Its new difference needs its own decision.
            owner = next((p.owner for p in affected if p.raw), None)
            if owner is None:
                owner = len(edits)
                edits.append(Suggestion(model.original, model.incoming, ()))
            for p in affected:
                if p.owner is None:
                    p.owner = owner
        _place_edit(pieces, a, b, d-c, None)
    # The rest of resolution works in the unchanged source's coordinates.
    for piece in pieces:
        piece.length, piece.opposite = piece.opposite, piece.length
    return replace(model, edits=tuple(edits)), pieces


def resolve_review(model, review, index, accept):
    """Resolve existing ranges, retaining the ownership of every other decision."""
    ranges = model.ranges if index is None else model.edits[index].ranges
    corrections = []
    if index is None:
        original, incoming = resolve_all(model.original, model.incoming, ranges, accept)
        result = model_from_edits(original, incoming, ())
    else:
        change = model.edits[index]
        original, incoming = resolve(model.original, model.incoming, change, accept, defer_fields=True)
        side = 'incoming' if accept else 'original'
        source, target = (incoming, original) if accept else (original, incoming)
        target_side = 'original' if accept else 'incoming'
        extra = []
        if change.field:
            before = getattr(model, target_side)
            target_offset = 0 if accept else 2
            covered = {span[target_offset:target_offset+2] for span in ranges}
            extra = [(a, b, c, d) for a, b, c, d in field_edits(before, target)
                     if (a, b) not in covered and before.text[a:b] != target.text[c:d]]
        if extra:
            model, pieces = _reanchor_field_occurrences(model, target_side, extra)
        else:
            pieces = list(_pieces(model, side))
        for p in pieces:
            if p.owner == index:
                p.opposite = p.length
                p.owner, p.raw = None, False
        offset = 2 if accept else 0
        fields = [e for span in ranges for e in source.elements if e.kind == 'field'
                  and span[offset] <= e.start and e.end <= span[offset+1]]
        pending = _field_owners(model, index)
        if fields and pending:
            target, corrections = _link_inserted_fields(model, pieces, target, fields, dict(target.definitions),
                                                        resolved=index)
        names = set(change.definitions).union(e.name for e in fields).difference(pending)
        if names:
            from app.src.casecat.fields import field_values
            values, chosen = dict(target.definitions), field_values(source)
            for name in names:
                if name in chosen:
                    values[name] = chosen[name]
                elif not any(e.kind == 'field' and e.name == name for e in target.elements):
                    values.pop(name, None)
            target = replace(target, definitions=tuple(sorted(values.items())))
        result = _updated_model(model, pieces, side, source, target)
        if extra and not accept:
            ranges = list(ranges) + [(0, d-c, a, b) for a, b, c, d in extra]
    metadata = _metadata(review, result)
    track_decisions(metadata, ranges, incoming_changed=not accept and
                    (bool(corrections) or model.incoming.text != result.incoming.text))
    if not accept:
        for correction in corrections:
            track_decisions(metadata, [correction], incoming_changed=True)
    return result, metadata


def remap_speaker_decisions(original, before, after, review, locations):
    """Replace the affected attribution ranges and retain manual wording groups."""
    edits = list(restore_decisions(original, before, review['pending_decisions']))
    from app.src.review_model import ReviewModel
    model = ReviewModel(original, before, tuple(edits), ())
    pieces = list(_pieces(model, 'incoming'))
    for old, new in reversed(sorted(locations)):
        a, b = old
        c, d = new
        if same_passage(before, after, (a, b, c, d)):
            continue
        first = _split_at(pieces, a, inside_raw='start')
        last = _split_at(pieces, b, inside_raw='end')
        selected = pieces[first:last]
        owner = next((p.owner for p in selected if p.raw), None)
        if owner is None:
            owner = len(edits)
            edits.append(Suggestion(original, before, (), 'speaker'))
        for p in selected:
            if not p.raw:
                p.owner = owner
                p.raw = True
        _place_edit(pieces, a, b, d-c, None)
    result = _updated_model(replace(model, edits=tuple(edits)), pieces, 'incoming', after, original)
    return _metadata(review, result)['pending_decisions']
