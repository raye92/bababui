"""Review decisions over exact structured revision ranges, independent of Qt."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from app.src.transcript_diff import Block, align_blocks


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
    """Trim shared ends, anchor paragraphs, and bound similarity alignment work."""
    from app.src.off_record import NOTE
    aa = [i for i, line in enumerate(left) if NOTE.fullmatch(line)]
    bb = [i for i, line in enumerate(right) if NOTE.fullmatch(line)]
    if aa and len(aa) == len(bb):
        # Confirmed notes separate alignment domains, even if distant repeated
        # testimony would otherwise win the global paragraph matching.
        result, i, j = [], 0, 0
        for a, b in zip(aa, bb):
            result.extend((tag, x+i, y+i, z+j, w+j)
                          for tag, x, y, z, w in _paragraph_ops(left[i:a], right[j:b]))
            result.append(('equal' if left[a] == right[b] else 'replace', a, a+1, b, b+1))
            i, j = a+1, b+1
        result.extend((tag, x+i, y+i, z+j, w+j)
                      for tag, x, y, z, w in _paragraph_ops(left[i:], right[j:]))
        return result
    prefix = 0
    while prefix < min(len(left), len(right)) and left[prefix] == right[prefix]:
        prefix += 1
    a, b = len(left), len(right)
    while a > prefix and b > prefix and left[a-1] == right[b-1]:
        a -= 1
        b -= 1
    result = [('equal', 0, prefix, 0, prefix)] if prefix else []
    for tag, i, j, k, l in SequenceMatcher(None, left[prefix:a], right[prefix:b],
                                          autojunk=(a-prefix)*(b-prefix) > 1_000_000).get_opcodes():
        i, j, k, l = i+prefix, j+prefix, k+prefix, l+prefix
        if tag == 'replace' and (j-i)*(l-k) <= 10_000:
            aa = [Block(text, 'paragraph') for text in left[i:j]]
            bb = [Block(text, 'paragraph') for text in right[k:l]]
            result.extend((op, x+i, y+i, z+k, w+k) for op, x, y, z, w in align_blocks(aa, bb))
        elif tag == 'replace' and j-i == l-k:
            result.extend(('replace', x, x+1, z, z+1) for x, z in zip(range(i, j), range(k, l)))
        else:
            result.append((tag, i, j, k, l))
    if a < len(left):
        result.append(('equal', a, len(left), b, len(right)))
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
    return original.revise('\n'.join(new))


def suggestions(original, incoming):
    if original == incoming:
        return []
    a, b = original.text, incoming.text
    tokens = lambda s: list(re.finditer(r'\n|[^\S\n]+|\w+|[^\w\s]', s))
    lines_a, lines_b = a.splitlines(keepends=True), b.splitlines(keepends=True)
    def offsets(lines):
        result = [0]
        for line in lines:
            result.append(result[-1] + len(line))
        return result
    oa, ob = offsets(lines_a), offsets(lines_b)
    ops = []
    # Speaker labels and Q/A prefixes must not steer wording alignment toward
    # a different repeated turn. Still compare the complete paragraph tokens.
    from app.src.suggestion_filter import _paragraphs
    bodies_a = [p[3] for p in _paragraphs(a, byline_context=False)][:len(lines_a)]
    bodies_b = [p[3] for p in _paragraphs(b, byline_context=False)][:len(lines_b)]
    for tag, i, j, k, l in _paragraph_ops(bodies_a, bodies_b):
        if tag == 'equal' and a[oa[i]:oa[j]] == b[ob[k]:ob[l]]:
            continue
        aa, bb = tokens(a[oa[i]:oa[j]]), tokens(b[ob[k]:ob[l]])
        for subtag, x, y, z, w in SequenceMatcher(None, [m.group() for m in aa], [m.group() for m in bb],
                                                autojunk=len(aa)*len(bb) > 1_000_000).get_opcodes():
            if subtag == 'equal':
                continue
            start = oa[i] + (aa[x].start() if x < len(aa) else oa[j]-oa[i])
            end = oa[i] + (aa[y-1].end() if y > x else start-oa[i])
            ns = ob[k] + (bb[z].start() if z < len(bb) else ob[l]-ob[k])
            ne = ob[k] + (bb[w-1].end() if w > z else ns-ob[k])
            ops.append((start, end, ns, ne))
    gaps = []
    for start, end, ns, ne in ops:
        if gaps and a[gaps[-1][1]:start].strip() == b[gaps[-1][3]:ns].strip() == '' and '\n' not in a[gaps[-1][1]:start]:
            gaps[-1][1], gaps[-1][3] = end, ne
        else:
            gaps.append([start, end, ns, ne])
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
