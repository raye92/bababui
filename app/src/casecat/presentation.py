"""Native presentation attributes projected onto editable logical text."""
from bisect import bisect_left
from dataclasses import replace
import struct
import re
from functools import lru_cache

from .structure import projected_groups, source_groups, group_targets, group_matches
from .layout import read_layouts, read_deltas, ParagraphStyle
from app.src.suggestion_filter import LABEL


QA_PREFIX = re.compile(r'^ *([QA]) {2,}')


def prepare_editor_presentation(job, bundle):
    try:
        return presentation(job, bundle)
    except ValueError:
        return job.text, {}, frozenset()


@lru_cache(maxsize=8)
def presentation(job, bundle):
    if job.revision != job.baseline:
        # Preview the same native controls that export will write. Matching
        # text fragments alone can carry a removed paragraph style or hard space
        # into a new passage, so it is not a faithful layout projection.
        from .codec import serialize_native, load_job
        from .fields import serialize_metadata
        try:
            native = serialize_native(job, bundle)
        except ValueError:
            # An unsupported container remains editable and visibly styled;
            # export still reports its validation error before publishing.
            return _presentation(job, source_groups(job.with_revision(job.baseline), bundle))
        metadata = serialize_metadata(job, bundle)

        class Overlay:
            jobs, digest = bundle.jobs, bundle.digest

            def member(self, name):
                return bundle.member(name)

            def read(self, name):
                if name == bundle.member(job.key + '.sgngl'):
                    return native
                if name == bundle.member(job.key + '.sgxml'):
                    return metadata
                return bundle.read(name)

        candidate = load_job(Overlay(), job.key)
        return _presentation(candidate, projected_groups(candidate, bundle))
    return _presentation(job, source_groups(job, bundle))


def _presentation(job, groups):
    text = job.text
    targets = ([span.content for span in job.baseline.spans] if job.revision == job.baseline
               else group_targets(job))
    layouts = read_layouts(job.native_bytes)
    definitions = layouts[0].paragraphs if layouts else ()
    result, styles, breaks, cursor = [], {}, set(), 0
    for group, target in zip(groups, targets):
        source = ''.join(t.text for t in group)
        hard, paragraphs, page_breaks, offset = set(), {}, [], 0
        for token in group:
            if token.raw == b'\x01':
                hard.add(offset)
            if token.raw == b'\x02':
                # Spaces displayed around a conflict separator do not exist
                # as native whitespace records. Only literal choice spaces
                # are break opportunities in CATalyst's line layout.
                hard.update(offset + i for i, char in enumerate(token.text) if char == ' ')
            if token.raw == b'\x0c':
                page_breaks.append(offset)
            if token.raw[0] == 0x16:
                # By-lines may combine the paragraph record with a label.
                style = int.from_bytes(token.raw[1:3], 'little')
                value = (replace(definitions[style - 1], prefix_length={2: 10, 3: 10, 4: 5}.get(style, 0))
                         if 1 <= style <= len(definitions) else style)
                if token.text:
                    # Match the control's newline. The paragraph it styles
                    # can start in the following stroke group.
                    paragraphs[offset] = int(token.text.startswith('\n')), value
                else:
                    # The initial paragraph control renders no text. Its
                    # indent still applies when the first letter is replaced.
                    styles[cursor + offset] = value
            if token.raw[:2] == b'\x15\x03':
                position = max(paragraphs) if paragraphs else max(styles, default=None)
                if position is not None:
                    skip, value = paragraphs[position] if paragraphs else (0, styles[position])
                    for kind, payload in read_deltas(token.raw[6:]):
                        if kind == 10 and isinstance(value, ParagraphStyle):
                            value = replace(value, first=struct.unpack('<H', payload)[0])
                    if paragraphs:
                        paragraphs[position] = skip, value
                    else:
                        styles[position] = value
            offset += len(token.text)
        display = list(target)
        if hard or paragraphs or page_breaks:
            matches = group_matches(source, target)
            for a, b, size in matches:
                for position in hard:
                    if a <= position < a + size:
                        display[b + position - a] = '\u00a0'
                for position, (skip, style) in paragraphs.items():
                    if a <= position < a + size:
                        styles[cursor + b + position - a + skip] = style
            for position in page_breaks:
                mapped = next((b + max(0, position - a) for a, b, size in matches
                               if position < a + size), len(target))
                breaks.add(cursor + mapped)
        result.append(''.join(display))
        cursor += len(target)
    if definitions:
        current = definitions[0]
        for group in groups:
            first = next((int.from_bytes(t.raw[1:3], 'little') for t in group if t.raw[0] == 0x16), None)
            if first is not None and 1 <= first <= len(definitions):
                current = definitions[first - 1]
                break
        position = 0
        for paragraph in text.split('\n'):
            style = styles.get(position)
            if re.fullmatch(r'(?:FURTHER )?EXAMINATION', paragraph) and len(definitions) >= 7:
                current = definitions[6]
                styles[position] = current
            elif isinstance(style, ParagraphStyle):
                current = style
            else:
                qa = QA_PREFIX.match(paragraph)
                speaker = LABEL.match(paragraph) if paragraph.startswith('     ') else None
                if qa and (label := 2 if qa[1] == 'Q' else 3) <= len(definitions):
                    current = replace(definitions[label - 1], prefix_length=qa.end())
                elif speaker and len(definitions) >= 4 and not speaker['prefix'].strip():
                    current = replace(definitions[3], prefix_length=speaker.start('name'))
                elif position:
                    current = replace(current, first=current.continuation, prefix_length=0)
                styles[position] = current
            position += len(paragraph) + 1
    # Page breaks decorate paragraph starts without changing logical offsets.
    starts = [0, *(match.end() for match in re.finditer('\n', text))]
    page_starts = set()
    for position in breaks:
        # A paragraph control immediately after the page break ends the
        # preceding block, even when that block is empty.
        if text[position:position + 1] == '\n':
            position += 1
        index = bisect_left(starts, position)
        if 0 < index < len(starts) and starts[index] < len(text):
            page_starts.add(starts[index])
    return ''.join(result), styles, frozenset(page_starts)
