"""Native presentation attributes projected onto editable logical text."""
from difflib import SequenceMatcher
from dataclasses import replace
import struct
import re
from functools import lru_cache

from .structure import projected_groups, source_groups, group_targets
from .layout import read_layouts, read_deltas, ParagraphStyle


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
    targets = ([span.content for span in job.baseline.spans] if job.revision == job.baseline
               else group_targets(job))
    layouts = read_layouts(job.native_bytes)
    definitions = layouts[0].paragraphs if layouts else ()
    result, styles, cursor = [], {}, 0
    for group, target in zip(groups, targets):
        source = ''.join(t.text for t in group)
        hard, paragraphs, offset = set(), {}, 0
        for token in group:
            if token.raw == b'\x01':
                hard.add(offset)
            if token.raw == b'\x02':
                # Spaces displayed around a conflict separator do not exist
                # as native whitespace records. Only literal choice spaces
                # are break opportunities in CATalyst's line layout.
                hard.update(offset + i for i, char in enumerate(token.text) if char == ' ')
            if token.raw[0] == 0x16:
                # By-lines may combine the paragraph record with a label.
                style = int.from_bytes(token.raw[1:3], 'little')
                paragraphs[offset + (1 if token.text.startswith('\n') else 0)] = (
                    replace(definitions[style - 1], prefix_length=10 if style in (2,3) else 5 if style == 4 else 0)
                    if 1 <= style <= len(definitions) else style)
            if token.raw[:2] == b'\x15\x03':
                destination = paragraphs if paragraphs else styles
                if destination:
                    position = max(destination)
                    value = destination[position]
                    for kind, payload in read_deltas(token.raw[6:]):
                        if kind == 10 and isinstance(value, ParagraphStyle):
                            value = replace(value, first=struct.unpack('<H', payload)[0])
                    destination[position] = value
            offset += len(token.text)
        display = list(target)
        if (hard or paragraphs) and len(source) * len(target) < 2_000_000:
            matches = ((0, 0, len(source)),) if source == target else SequenceMatcher(
                None, source, target, autojunk=False).get_matching_blocks()
            for a, b, size in matches:
                for position in hard:
                    if a <= position < a + size:
                        display[b + position - a] = '\u00a0'
                for position, style in paragraphs.items():
                    if a <= position < a + size:
                        styles[cursor + b + position - a] = style
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
        for paragraph in job.text.split('\n'):
            style = styles.get(position)
            if re.fullmatch(r'(?:FURTHER )?EXAMINATION', paragraph) and len(definitions) >= 7:
                current = definitions[6]
                styles[position] = current
            elif isinstance(style, ParagraphStyle):
                current = style
            else:
                label = 2 if paragraph.startswith('     Q    ') else 3 if paragraph.startswith('     A    ') else None
                if label and label <= len(definitions):
                    current = replace(definitions[label - 1], prefix_length=10)
                elif position:
                    current = replace(current, first=current.continuation, prefix_length=0)
                styles[position] = current
            position += len(paragraph) + 1
    return ''.join(result), styles
