"""Review decisions over exact structured revision ranges, independent of Qt."""
from dataclasses import dataclass
import re
from app.src import advanced_diff


@dataclass(frozen=True)
class Suggestion:
    original: object
    incoming: object
    ranges: tuple  # (original start/end, incoming start/end), Python character offsets
    kind: str = 'text'
    field: str | None = None


def _layout(line):
    match = re.match(r'^(\s*)([QA])([ \t]+)(.*)$', line)
    if match:
        return match[1], match[2], match[3], match[4]
    return line[:len(line)-len(line.lstrip(' \t'))], '', '', line.lstrip(' \t')


def _paragraph_ops(left, right):
    """Align transcript bodies with advanced diff, then place structural-only lines."""
    from app.src.off_record import NOTE
    from app.src.suggestion_filter import _paragraphs
    notes_a = [i for i, line in enumerate(left) if NOTE.fullmatch(line)]
    notes_b = [i for i, line in enumerate(right) if NOTE.fullmatch(line)]
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


def propose(original, text):
    """Keep existing paragraph indentation and generated Q/A label spacing."""
    old = original.text.split('\n')
    new = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    # Use normalized labels for matching, but never write normalized body text.
    aa = [(q + ' ' + body).strip() for _, q, _, body in map(_layout, old)]
    bb = [(q + ' ' + body).strip() for _, q, _, body in map(_layout, new)]
    for _, a, b, c, d in _paragraph_ops(aa, bb):
        if b-a == d-c:
            for i, j in zip(range(a, b), range(c, d)):
                indent, label, space, _ = _layout(old[i])
                _, new_label, new_space, body = _layout(new[j])
                new[j] = indent + new_label + (space if label and new_label else new_space) + body
    text = '\n'.join(new)
    return original.revise(text, edits=text_edits(original.text, text))


def _token_edits(a, b, start, end, ns, ne):
    """Compatibility adapter for callers comparing an exact source slice."""
    return [(i+start, j+start, k+ns, l+ns)
            for i, j, k, l in advanced_diff.text_edits(a[start:end], b[ns:ne])]


def text_edits(a, b):
    """advanced diff inner changes, without whitespace or proximity regrouping."""
    return advanced_diff.text_edits(a, b)


def suggestions(original, incoming):
    if original == incoming:
        return []
    a, b = original.text, incoming.text
    gaps = text_edits(a, b)
    # Expand both sides together so adopting a field/symbol cannot cut it in half.
    expanded = []
    for start, end, ns, ne in gaps:
        left_field = next((e for e in original.elements if e.kind == 'field'
                           and e.start <= start <= end <= e.end and start < e.end), None)
        right_field = next((e for e in incoming.elements if e.kind == 'field'
                            and e.start <= ns <= ne <= e.end and ns < e.end), None)
        if left_field and right_field:
            # Field values need not have equal lengths. Expanding both by the
            # same number of characters can swallow the following colon.
            start, end = left_field.start, left_field.end
            ns, ne = right_field.start, right_field.end
        changed = True
        while changed:
            before = (start, end, ns, ne)
            for rev, left in ((original, True), (incoming, False)):
                x, y = (start, end) if left else (ns, ne)
                for e in rev.elements:
                    if (x < e.end and y > e.start) or (x == y and e.start < x < e.end):
                        front, back = max(0, x-e.start), max(0, e.end-y)
                        start, ns = max(0, start-front), max(0, ns-front)
                        end, ne = min(len(a), end+back), min(len(b), ne+back)
            changed = before != (start, end, ns, ne)
        if expanded and (start < expanded[-1][1] or ns < expanded[-1][3]):
            expanded[-1][1] = max(end, expanded[-1][1]); expanded[-1][3] = max(ne, expanded[-1][3])
        else:
            expanded.append([start, end, ns, ne])
    result, fields = [], {}
    for span in expanded:
        start, end, ns, ne = span
        left = next((e for e in original.elements if e.kind == 'field' and (e.start, e.end) == (start, end)), None)
        right = next((e for e in incoming.elements if e.kind == 'field' and (e.start, e.end) == (ns, ne)), None)
        # Only a pure value change is a linked-definition decision. Removing or
        # replacing an occurrence must adopt the actual structural range.
        name = left.name if left and right and left.name == right.name else None
        kind = 'structure' if '\n' in a[start:end] + b[ns:ne] else 'text'
        if name:
            fields.setdefault(name, []).append(tuple(span))
        else:
            result.append(Suggestion(original, incoming, (tuple(span),), kind))
    result += [Suggestion(original, incoming, tuple(ranges), 'field', name) for name, ranges in fields.items()]
    if not result and (original.elements != incoming.elements or original.definitions != incoming.definitions):
        result.append(Suggestion(original, incoming, (), 'metadata'))
    return sorted(result, key=lambda s: s.ranges[0][0] if s.ranges else 0)


def resolve(original, incoming, change, accept):
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
                target = target.adopt(a, b, source, c, d, at_destination=True) if accept else target.adopt(c, d, source, a, b)
    else:
        for a, b, c, d in reversed(change.ranges):
            target = target.adopt(a, b, source, c, d, at_destination=True) if accept else target.adopt(c, d, source, a, b)
    original, incoming = (target, incoming) if accept else (original, target)
    if original.text == incoming.text and original.elements == incoming.elements and original.definitions == incoming.definitions:
        incoming = original
    return original, incoming
