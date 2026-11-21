"""One immutable source of review decisions and logical display sections."""
from dataclasses import dataclass, field, replace
import re

from app.src.suggestions import Suggestion, suggestions

# A suggestion that removes at least this many of the rough's words, and keeps at
# most half of them, is a passage missing from the AI draft. Real testimony is
# rarely deleted: such a gap almost always means the transcription missed audio.
MISSING_WORDS = 25
_WORD = re.compile(r'[^\W_]+')


def missing_passage(edit):
    """Whether a suggestion would remove a passage of the rough that the AI draft lacks."""
    if edit.kind in ('field', 'metadata') or edit.field or not edit.ranges:
        return False
    original, incoming = edit.original.text, edit.incoming.text
    old = sum(len(_WORD.findall(original[a:b])) for a, b, _, _ in edit.ranges)
    new = sum(len(_WORD.findall(incoming[c:d])) for _, _, c, d in edit.ranges)
    return old - new >= MISSING_WORDS and 2 * new <= old


def _grams(text):
    words = [word.lower() for word in _WORD.findall(text)]
    return {tuple(words[i:i + 4]) for i in range(len(words) - 3)}


def _moved(edits, index):
    """Whether another suggestion adds most of this one's removed words: the draft moved them."""
    edit = edits[index]
    removed = _grams(' '.join(edit.original.text[a:b] for a, b, _, _ in edit.ranges))
    added = set().union(*(_grams(' '.join(other.incoming.text[c:d] for _, _, c, d in other.ranges))
                          for i, other in enumerate(edits) if i != index))
    return 2 * len(removed & added) >= len(removed)


@dataclass(frozen=True)
class ReviewSection:
    original_range: tuple[int, int]
    incoming_range: tuple[int, int]
    edit_indices: tuple[int, ...]


@dataclass(frozen=True)
class ReviewModel:
    original: object
    incoming: object
    edits: tuple[Suggestion, ...]
    sections: tuple[ReviewSection, ...]
    # Edits that would remove a passage the AI draft lacks. Accept All leaves them.
    missing: frozenset[int] = field(default=frozenset())

    @property
    def ranges(self):
        return tuple(span for edit in self.edits for span in edit.ranges)

    @property
    def accept_all_ranges(self):
        """The ranges Accept All decides: every edit but a missing passage."""
        return tuple(span for index, edit in enumerate(self.edits) if index not in self.missing
                     for span in edit.ranges)

    def accept_all_positions(self):
        """(c, d, c2, d2): where each kept passage's incoming range lands in the Accept All text."""
        spans, shift = [], 0
        for index in sorted(self.missing, key=lambda i: self.edits[i].ranges[0][2]):
            for a, b, c, d in self.edits[index].ranges:
                spans.append((c, d, c + shift, c + shift + b - a))
                shift += (b - a) - (d - c)
        return tuple(spans)

    def position_on(self, side, position, target):
        if side == target:
            return position
        ranges = self.ranges
        if side == 'incoming':
            ranges = ((c, d, a, b) for a, b, c, d in ranges)
        return map_position(position, sorted(ranges))


def map_position(position, ranges):
    """Map a reading position through ordered old and new text ranges."""
    shift = 0
    for a, b, c, d in ranges:
        if position < a:
            break
        if position < b:
            return c + min(position - a, d - c)
        shift = d - b
    return position + shift


def _paragraph_bounds(text, start, end):
    first = text.rfind('\n', 0, start) + 1
    last = text.find('\n', max(start, end - 1))
    return first, len(text) if last < 0 else last + 1


def build_review(original, incoming):
    """Build fine native decisions once; visual sections never merge decisions."""
    edits = tuple(suggestions(original, incoming))
    windows = []
    entries = sorted((*span, index) for index, edit in enumerate(edits) for span in edit.ranges)
    for position, (a, b, c, d, index) in enumerate(entries):
        first, last = _paragraph_bounds(original.text, a, b)
        ns, ne = _paragraph_bounds(incoming.text, c, d)
        previous_a, previous_c = (entries[position-1][1], entries[position-1][3]) if position else (0, 0)
        following_a, following_c = (entries[position+1][0], entries[position+1][2]) if position+1 < len(entries) else (len(original.text), len(incoming.text))
        # Expand both sides by the same unchanged context. Independent paragraph
        # slicing would duplicate retained text beside a whole-paragraph insert.
        front = min(a-previous_a, c-previous_c, max(a-first, c-ns))
        back = min(following_a-b, following_c-d, max(last-b, ne-d))
        windows.append((a-front, b+back, c-front, d+back, {index}))
    for index, edit in enumerate(edits):
        if not edit.ranges:
            windows.append((0, 0, 0, 0, {index}))
    # Related displaced passages can share context without sharing a decision.
    from app.src.related_suggestions import related_groups
    groups = list(related_groups(original, incoming, edits))
    for group in groups:
        if len(group) < 2:
            continue
        contexts = [window for window in windows if window[4].intersection(group)]
        windows.append((min(window[0] for window in contexts), max(window[1] for window in contexts),
                        min(window[2] for window in contexts), max(window[3] for window in contexts), set(group)))
    sections = []
    for a, b, c, d, indices in sorted(windows, key=lambda window: (window[0], window[2])):
        if sections and (a < sections[-1][1] or c < sections[-1][3]
                         or (a, b, c, d) == tuple(sections[-1][:4])):
            previous = sections[-1]
            previous[1], previous[3] = max(previous[1], b), max(previous[3], d)
            previous[4].update(indices)
        else:
            sections.append([a, b, c, d, set(indices)])
    # A passage moved elsewhere in the draft is not missing from it.
    displaced = {index for group in groups if len(group) > 1 for index in group}
    missing = frozenset(index for index, edit in enumerate(edits)
                        if index not in displaced and missing_passage(edit) and not _moved(edits, index))
    return ReviewModel(original, incoming, edits, tuple(
        ReviewSection((a, b), (c, d), tuple(sorted(indices))) for a, b, c, d, indices in sections), missing)


def accept_all(model):
    """(original, incoming) after Accept All.

    Every suggestion is accepted except a passage missing from the AI draft. The
    rough keeps that passage, and its card stays pending for the reporter.
    """
    from app.src.suggestions import resolve, resolve_all
    if not model.missing:
        return resolve_all(model.original, model.incoming, model.ranges, True)
    original, kept = model.original, model.incoming
    # Put the rough's passage back into a copy of the draft, last first so
    # earlier offsets stay valid, then accept everything else in that copy.
    for index in sorted(model.missing, key=lambda i: model.edits[i].ranges[0][2], reverse=True):
        _, kept = resolve(original, kept, replace(model.edits[index], original=original, incoming=kept), False)
    ranges = tuple(span for edit in suggestions(original, kept) for span in edit.ranges)
    accepted, _ = resolve_all(original, kept, ranges, True)
    return accepted, model.incoming
