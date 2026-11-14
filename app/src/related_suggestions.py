"""Find related display contexts without merging native review decisions."""
from difflib import SequenceMatcher
import re

from app.src.off_record import NOTE


def _words(text):
    from app.src.suggestion_filter import _paragraphs
    text = re.sub(r'(?m)^[ \t]*[QA][ \t]*$', '', text)
    body = ' '.join(p[3] for p in _paragraphs(text, byline_context=False))
    return re.findall(r'[^\W_]+', body.casefold(), re.UNICODE)


def _has_note(text):
    return any(NOTE.fullmatch(line) for line in text.splitlines())


def _related(left, right):
    if min(len(left), len(right)) < 5:
        return False
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    blocks = matcher.get_matching_blocks()
    shared = [word for block in blocks for word in left[block.a:block.a+block.size]]
    return (len(shared) >= 5 and len(set(shared)) >= 4
            and max(block.size for block in blocks) >= 4
            and len(shared)/min(len(left), len(right)) >= .7)


def related_groups(original, incoming, changes):
    """Only mutually unique, adjacent partners share a visual context.

    Ignore punctuation/case/labels for evidence, never for application. A gap
    containing testimony or a note is a barrier. Large mixed insertions remain
    separate rather than pulling unrelated material into a replacement card.
    """
    data = []
    for change in changes:
        if change.field or len(change.ranges) != 1:
            data.append(None)
            continue
        a, b, c, d = change.ranges[0]
        old, new = original.text[a:b], incoming.text[c:d]
        aa, bb = _words(old), _words(new)
        direction = 1 if len(bb)-len(aa) >= 5 else -1 if len(aa)-len(bb) >= 5 else 0
        if (not direction or max(len(aa), len(bb)) > 150
                or max(old.count('\n'), new.count('\n')) > 6
                or _has_note(old) or _has_note(new)):
            data.append(None)
        else:
            data.append((direction, aa if direction < 0 else bb))

    links = [set() for _ in changes]
    for i, item in enumerate(data):
        if item is None:
            continue
        for j in range(i+1, min(len(changes), i+5)):
            if data[j] is None:
                break
            _, b, _, d = changes[j-1].ranges[-1]
            a, _, c, _ = changes[j].ranges[0]
            old_gap, new_gap = original.text[b:a], incoming.text[d:c]
            if (a < b or c < d or max(len(old_gap), len(new_gap)) > 160
                    or _has_note(old_gap) or _has_note(new_gap)
                    or _words(old_gap) or _words(new_gap)):
                break
            if item[0] != data[j][0] and _related(item[1], data[j][1]):
                links[i].add(j)
                links[j].add(i)

    result, i = [], 0
    while i < len(changes):
        if links[i] == {i+1} and links[i+1] == {i}:
            result.append((i, i+1))
            i += 2
        else:
            result.append((i,))
            i += 1
    return tuple(result)
