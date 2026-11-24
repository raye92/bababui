"""One immutable source of review decisions and logical display sections."""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from functools import cached_property

from app.src.suggestions import GROUPING_VERSION, Suggestion, preview_ranges, suggestions


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
    _sections: tuple[ReviewSection, ...] | None = None
    comparison_spans: tuple | None = None

    @cached_property
    def sections(self):
        if self._sections is not None:
            return self._sections
        pairs = self.compare_rows(_paragraph_rows(self.original.text), _paragraph_rows(self.incoming.text))
        sections = [section for _, _, section in pairs if section.edit_indices]
        sections.extend(ReviewSection((0, 0), (0, 0), (i,)) for i, edit in enumerate(self.edits) if not edit.ranges)
        return tuple(sections)

    def compare_rows(self, original_rows, incoming_rows):
        spans = self.comparison_spans
        if spans is None:
            spans = _display_spans(self.original, self.incoming, self.edits)
        return _compare_rows(self.original.text, self.incoming.text, spans, original_rows, incoming_rows)

    @property
    def ranges(self):
        return tuple(span for edit in self.edits for span in edit.ranges)

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


def _paragraph_rows(text):
    rows, start = [], 0
    for paragraph in text.split('\n'):
        end = start + len(paragraph)
        rows.append((start, end))
        start = end + 1
    return rows


def _display_spans(original, incoming, edits):
    """Keep exact decision owners, including both sides of a related passage."""
    from app.src.advanced_diff import paragraph_ops
    from app.src.related_suggestions import related_groups
    old, new = original.text, incoming.text
    entries = []
    for group in related_groups(original, incoming, edits):
        raw = [span for i in group for span in edits[i].ranges]
        visible = [span for i in group for span in preview_ranges(edits[i])]
        if len(group) > 1 or len(raw) != len(visible):
            raw = [(raw[0][0], raw[-1][1], raw[0][2], raw[-1][3])]
            visible = [(visible[0][0], visible[-1][1], visible[0][2], visible[-1][3])]
        for (a, b, c, d), (x, y, z, w) in zip(raw, visible):
            entries.append((a, b, c, d, group, max(a - x, c - z), max(y - b, w - d)))
    entries.sort()
    spans = []
    previous_b = previous_d = 0
    for index, (a, b, c, d, owners, front, back) in enumerate(entries):
        # Extend whole words only through the exact common gap. Matching
        # letters across a nearby insertion can belong to different words.
        front = max(0, min(front, a - previous_b, c - previous_d))
        if index + 1 < len(entries):
            following = entries[index + 1]
            back = max(0, min(back, following[0] - b, following[2] - d))
        previous_b, previous_d = max(previous_b, b), max(previous_d, d)
        a, b, c, d = a - front, b + back, c - front, d + back
        if spans and (a < spans[-1][1] or c < spans[-1][3]):
            x, y, z, w, others = spans.pop()
            spans.append((min(x, a), max(y, b), min(z, c), max(w, d), tuple(sorted(set(others + owners)))))
        else:
            spans.append((a, b, c, d, owners))
    if not any(len(owners) == 1 and '\n' in old[a:b] and '\n' in new[c:d] for a, b, c, d, owners in spans):
        return tuple(spans)

    # The inner diff can include a retained paragraph break in one decision.
    # Only split its display where both neighboring paragraphs have their
    # own counterpart according to the same alignment used by the importer.
    raw = sorted(span for edit in edits for span in edit.ranges)
    ops = paragraph_ops(old.split('\n'), new.split('\n'), edits=raw)
    old_rows, new_rows = _paragraph_rows(old), _paragraph_rows(new)
    matched = {(a, c) for _, a, b, c, d in ops if b - a == d - c == 1}
    boundaries = sorted((old_rows[i][1], new_rows[j][1]) for i, j in matched if (i + 1, j + 1) in matched)
    result = []
    for a, b, c, d, owners in spans:
        if len(owners) == 1:
            index = bisect_right(boundaries, (a, len(new)))
            while index < len(boundaries) and boundaries[index][0] < b - 1:
                x, y = boundaries[index]
                if c < y < d - 1:
                    result.append((a, x, c, y, owners))
                    a, c = x + 1, y + 1
                index += 1
        result.append((a, b, c, d, owners))
    return tuple(result)


def _compare_rows(original, incoming, spans, old_rows, new_rows):
    """Pair logical paragraphs or printed rows using the same source correspondence.

    Each result gives the row slices and source section. An ownerless section
    is one fully retained original row. Only untouched incoming rows may be
    clipped to preserve the original wrapping of shared context.
    """
    old_starts = [a for a, _ in old_rows] + [len(original)]
    new_starts = [c for c, _ in new_rows] + [len(incoming)]
    old_ends = [b for _, b in old_rows]
    new_ends = [d for _, d in new_rows]
    new_empty = {c for c, d in new_rows if c == d}

    def anchors():
        a = c = 0
        for k, (b, next_a, d, next_c, _) in enumerate(
                [*spans, (len(original), len(original), len(incoming), len(incoming), ())]):
            # [a,b) and [c,d) are the unchanged gap between consecutive edits.
            first = bisect_left(new_starts, c)
            stop = bisect_right(new_ends, d)
            shared = False
            if first < stop:
                lo = bisect_left(old_starts, a + new_starts[first] - c)
                hi = bisect_right(old_ends, a + new_ends[stop - 1] - c)
                for i in range(lo, hi):
                    start, end = old_rows[i]
                    mapped = c + start - a
                    if start == end:
                        at_document_end = end == len(original) and mapped == len(incoming)
                        if mapped not in new_empty or (end == b and not at_document_end):
                            continue
                    # A removed or inserted paragraph separator belongs to
                    # its edit even when the preceding text survives intact.
                    if end < b and original[end] == '\n':
                        end += 1
                    yield k, i, start, mapped, end
                    shared = True
            if not shared and 0 < k < len(spans):
                i, j = bisect_left(old_starts, a), bisect_left(new_starts, c)
                if old_starts[i] <= b and new_starts[j] <= d:
                    # Wraps can move inside the gap. A boundary on both sides
                    # still separates the previous comparison from the next.
                    yield k, i, old_starts[i], new_starts[j], None
            a, c = next_a, next_c
        yield len(spans), len(old_rows), len(original), len(incoming), None

    old_i = new_i = old_pos = new_pos = consumed = 0
    for k, i, x, y, shared_end in anchors():
        if i < old_i or x < old_pos or y < new_pos:
            continue
        j = bisect_left(new_starts, y)
        if y == new_pos:
            j = max(j, new_i)
        if k > consumed:
            if k == len(spans) and i == len(old_rows):
                j = len(new_rows)
            owners = tuple(sorted({index for *_, indices in spans[consumed:k] for index in indices}))
            section = ReviewSection((old_pos, x), (new_pos, y), owners)
            yield slice(old_i, i), slice(new_i, j), section
        old_i, new_i, old_pos, new_pos, consumed = i, j, x, y, k
        if shared_end is not None:
            old_pos, new_pos = shared_end, y + shared_end - x
            old_i = i + 1
            length = old_rows[i][1] - x
            first = bisect_right(new_ends, y) if length else bisect_left(new_starts, y)
            stop = bisect_left(new_starts, y + length) if length else first + 1
            new_i = stop - int(new_pos < new_ends[stop - 1])
            yield slice(i, old_i), slice(first, stop), ReviewSection((x, old_pos), (y, new_pos), ())


def build_review(original, incoming, review=None):
    """Build fine native decisions once; visual sections never merge decisions."""
    if review and 'pending_decisions' in review:
        from app.src.review_editing import restore_decisions
        if review.get('grouping_version', 1) < GROUPING_VERSION:
            from app.src.review_upgrade import upgraded_edits
            edits, _ = upgraded_edits(original, incoming, review)
        else:
            edits = restore_decisions(original, incoming, review['pending_decisions'])
    else:
        edits = tuple(suggestions(original, incoming))
    return model_from_edits(original, incoming, edits)


def model_from_edits(original, incoming, edits):
    if all(edit.highlights is not None for edit in edits):
        # Manual transactions already partitioned the colored passages. No
        # paragraph alignment or whole-document diff is needed to render them.
        spans = tuple(sorted((*span, (i,)) for i, edit in enumerate(edits)
                             for span in edit.highlights))
    else:
        spans = _display_spans(original, incoming, edits)
    # Print all original rows of a quotation together, then all incoming
    # rows. Each endpoint and intervening wording edit keeps its own ranges.
    quotations = {i for i, edit in enumerate(edits) if edit.kind == 'quotation' and len(edit.ranges) > 1}
    if quotations:
        last = {owner: j for j, (*_, owners) in enumerate(spans) for owner in owners if owner in quotations}
        combined = []
        end = -1
        for j, (a, b, c, d, owners) in enumerate(spans):
            if j <= end:
                x, y, z, w, pending = combined.pop()
                a, b, c, d = min(a, x), max(b, y), min(c, z), max(d, w)
                owners = tuple(sorted(set(owners + pending)))
            end = max((last.get(i, end) for i in owners), default=end)
            combined.append((a, b, c, d, owners))
        spans = tuple(combined)
    return ReviewModel(original, incoming, edits, comparison_spans=spans)
