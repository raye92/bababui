"""Upgrade generated decisions in a saved review without overwriting manual edits."""
from bisect import bisect_right
from dataclasses import replace
from itertools import accumulate

from app.src.suggestions import GROUPING_VERSION, Suggestion, preview_ranges, resolve, review_generations, suggestions


def _signature(edit):
    return edit.kind, edit.field, edit.ranges, preview_ranges(edit), edit.definitions


def _cells(saved, generated, original, incoming):
    """Find boundaries shared by both edit paths, including insertion carets."""
    paths = [sorted(s for e in edits for s in e.ranges) for edits in (saved, generated)]
    points = {(0, 0), (len(original.text), len(incoming.text))}
    for spans in paths:
        for a, b, c, d in spans:
            points.update(((a, c), (b, d)))
    for spans in paths:
        gaps = []
        a = c = 0
        for x, y, z, w in spans:
            gaps.append((a+c, x+z, a-c))
            a, c = y, w
        gaps.append((a+c, len(original.text)+len(incoming.text), a-c))
        starts = [g[0] for g in gaps]
        def in_gap(p):
            x, z = p
            _, end, delta = gaps[bisect_right(starts, x+z)-1]
            return x+z <= end and x-z == delta
        points = {p for p in points if in_gap(p)}
    return sorted(a+c for a, c in points)


def upgraded_edits(original, incoming, review):
    from app.src.review_editing import restore_decisions
    if review.get('grouping_version', 1) >= GROUPING_VERSION and 'pending_decisions' in review:
        saved = restore_decisions(original, incoming, review['pending_decisions'])
        generated = {_signature(e) for e in suggestions(original, incoming)}
        return saved, {_signature(e) for e in saved}.difference(generated)
    previous, fresh = review_generations(original, incoming)
    baseline = {_signature(e) for e in previous}
    prior = baseline if review.get('automatic_filter') == 1 else set()
    if 'pending_decisions' not in review:
        return fresh, prior
    saved = restore_decisions(original, incoming, review['pending_decisions'])
    custom = [e for e in saved if _signature(e) not in baseline]
    if not custom:
        return fresh, prior

    boundaries = _cells(saved, fresh, original, incoming)
    def cells(edit):
        return {bisect_right(boundaries, a+c)-1 for a, _, c, _ in edit.ranges}
    protected = set().union(*(cells(e) for e in custom))
    # Keep every occurrence of an affected linked field, move or quotation.
    groups = [cells(e) for e in (*saved, *fresh) if len(e.ranges) > 1]
    size = -1
    while size != len(protected):
        size = len(protected)
        for group in groups:
            if group & protected:
                protected.update(group)
    retained = [e for e in saved if cells(e) & protected or not e.ranges and e in custom]
    custom_metadata = any(not e.ranges for e in retained)
    result = [e for e in fresh if not cells(e) & protected and (e.ranges or not custom_metadata)]
    result.extend(retained)
    result.sort(key=lambda e: e.ranges[0] if e.ranges else (0, 0, 0, 0))
    return tuple(result), prior.union(_signature(e) for e in retained)


def _after_acceptance(span, accepted):
    """Move Original coordinates only. Incoming disambiguates insertion carets."""
    def position(p, q):
        shift = 0
        for a, b, c, d in accepted:
            if p < a or p == a == b and q <= c:
                break
            if a == b == p and q < d:
                return p + shift + q-c
            if p < b:
                return a + shift + min(p-a, d-c)
            shift += (d-c) - (b-a)
        return p + shift
    a, b, c, d = span
    return position(a, c), position(b, d), c, d


def _trim_saved(state, edits, protected, metadata):
    """Project existing owners through the first trailing-whitespace cleanup."""
    from app.src.suggestion_filter import _delete_trailing
    from app.src.suggestions import _inner_edits
    records, revisions, maps = [], [], []
    for side, offset in (('original', 0), ('incoming', 2)):
        source = getattr(state, side)
        keep = [s[offset:offset+2] for e in edits if _signature(e) in protected
                for s in (*e.ranges, *preview_ranges(e))]
        revisions.append(_delete_trailing(source, side, metadata, records,
                                          start_at=state.body_position(source), protected=keep))
        removed = [r['range'] for r in records if r['side'] == side]
        ends = [b for _, b in removed]
        totals = [0, *accumulate(b-a for a, b in removed)]
        def mapped(p, ranges=removed, ends=ends, totals=totals):
            i = bisect_right(ends, p)
            return p-totals[i] - (max(0, p-ranges[i][0]) if i < len(ranges) else 0)
        maps.append(mapped)
    original, incoming = revisions
    if not records:
        return original, incoming, edits, protected, records
    def remap(spans):
        return tuple((maps[0](a), maps[0](b), maps[1](c), maps[1](d)) for a, b, c, d in spans)
    result, kept = [], set()
    for edit in edits:
        ranges = tuple(s for s in remap(edit.ranges) if s[0] != s[1] or s[2] != s[3])
        if not ranges and edit.kind != 'metadata':
            continue
        updated = replace(edit, original=original, incoming=incoming, ranges=ranges,
                          highlights=remap(preview_ranges(edit)))
        result.append(updated)
        if _signature(edit) in protected:
            kept.add(_signature(updated))
    # Spaces shared in the old diff can be terminal on just one side of an
    # inserted paragraph. Keep the resulting difference independently editable.
    a = c = 0
    spans = sorted(s for e in edits for s in e.ranges)
    for x, y, z, w in [*remap(spans), (len(original.text),)*2 + (len(incoming.text),)*2]:
        left, right = original.text[a:x], incoming.text[c:z]
        if left != right:
            for i, j, k, l in _inner_edits(left, right):
                result.append(Suggestion(original, incoming, ((a+i, a+j, c+k, c+l),)))
        a, c = y, w
    result.sort(key=lambda e: e.ranges[0] if e.ranges else (0, 0, 0, 0))
    return original, incoming, tuple(result), kept, records


def upgrade_automatic(state, disabled_rules, remember_undo):
    """Apply only newly exposed punctuation to a previously filtered proposal."""
    from app.src.review_editing import _metadata
    from app.src.review_model import model_from_edits
    from app.src.suggestion_filter import PUNCTUATION, automatic_reason, track_decisions
    original, incoming, review = state.original, state.incoming, state.review
    edits, existing = upgraded_edits(original, incoming, review)
    model = model_from_edits(original, incoming, edits)
    metadata = _metadata(review, model)
    metadata['automatic_filter'] = 1
    audit = review.get('automatic_changes', review.get('off_record_changes', []))
    metadata['automatic_changes'] = list(audit)
    undo = original, incoming, metadata
    first_pass = review.get('automatic_filter') != 1
    whitespace = []
    if first_pass and 'trailing_whitespace' not in disabled_rules:
        metadata = _metadata(metadata, model)
        original, incoming, edits, existing, whitespace = _trim_saved(state, edits, existing, metadata)
        if whitespace:
            model = model_from_edits(original, incoming, edits)
            metadata = _metadata(metadata, model)
    candidates = []
    if first_pass or audit and 'punctuation' not in disabled_rules:
        body = state.body_position(original)
        for i, edit in enumerate(edits):
            if edit.kind != 'text' or len(edit.ranges) != 1 or _signature(edit) in existing:
                continue
            a, b, c, d = edit.ranges[0]
            old, new = original.text[a:b], incoming.text[c:d]
            punctuation = (old+new).strip() and set(old+new) <= PUNCTUATION.union(" '’")
            if (a >= body and (first_pass or punctuation)
                    and (reason := automatic_reason(edit, disabled_rules=disabled_rules))):
                candidates.append((i, {'ranges': [list(edit.ranges[0])], 'before': old, 'after': new, 'rule': reason}))
    if (candidates or whitespace) and remember_undo:
        remember_undo(undo)
    if candidates:
        chosen = {i for i, _ in candidates}
        accepted = sorted(edits[i].ranges[0] for i in chosen)
        for i, _ in reversed(candidates):
            change = replace(edits[i], original=original, incoming=incoming)
            original, incoming = resolve(original, incoming, change, True)
        remaining = tuple(replace(e, original=original, incoming=incoming,
                                  ranges=tuple(_after_acceptance(s, accepted) for s in e.ranges),
                                  highlights=tuple(_after_acceptance(s, accepted) for s in preview_ranges(e)))
                          for i, e in enumerate(edits) if i not in chosen)
        model = model_from_edits(original, incoming, remaining)
        metadata = _metadata(metadata, model)
        track_decisions(metadata, accepted, incoming_changed=False)
    if not model.edits:
        if original.elements == incoming.elements and original.definitions == incoming.definitions:
            model = model_from_edits(original, original, ())
        else:
            model = model_from_edits(original, incoming, (Suggestion(original, incoming, (), 'metadata', highlights=()),))
        metadata = _metadata(metadata, model)
    records = [*whitespace, *(record for _, record in candidates)]
    metadata['automatic_changes'] = [*audit, *records]
    state.original, state.incoming, state.review = model.original, model.incoming, metadata
    return records
