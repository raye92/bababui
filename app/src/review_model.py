"""One immutable source of review decisions and logical display sections."""
from dataclasses import dataclass

from app.src.suggestions import Suggestion, suggestions


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
    for group in related_groups(original, incoming, edits):
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
    return ReviewModel(original, incoming, edits, tuple(
        ReviewSection((a, b), (c, d), tuple(sorted(indices))) for a, b, c, d, indices in sections))
