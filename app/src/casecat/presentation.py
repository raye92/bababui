"""Native presentation attributes projected onto editable logical text."""
from difflib import SequenceMatcher
from dataclasses import replace
import struct

from .structure import projected_groups, group_targets
from .layout import read_layouts, read_deltas, ParagraphStyle


def presentation(job, bundle):
    groups = projected_groups(job, bundle)
    targets = group_targets(job)
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
                style = int.from_bytes(token.raw[1:], 'little')
                paragraphs[offset + (1 if token.text.startswith('\n') else 0)] = (
                    definitions[style - 1] if 1 <= style <= len(definitions) else style)
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
        if len(source) * len(target) < 2_000_000:
            for match in SequenceMatcher(None, source, target, autojunk=False).get_matching_blocks():
                for position in hard:
                    if match.a <= position < match.a + match.size:
                        display[match.b + position - match.a] = '\u00a0'
                for position, style in paragraphs.items():
                    if match.a <= position < match.a + match.size:
                        styles[cursor + match.b + position - match.a] = style
        result.append(''.join(display))
        cursor += len(target)
    if definitions:
        current = definitions[0]
        for group in groups:
            first = next((int.from_bytes(t.raw[1:], 'little') for t in group if t.raw[0] == 0x16), None)
            if first is not None and 1 <= first <= len(definitions):
                current = definitions[first - 1]
                break
        position = 0
        for paragraph in job.text.split('\n'):
            style = styles.get(position)
            if isinstance(style, ParagraphStyle):
                current = style
            else:
                label = 2 if paragraph.startswith('     Q    ') else 3 if paragraph.startswith('     A    ') else None
                if label and label <= len(definitions):
                    current = definitions[label - 1]
                elif position:
                    current = replace(current, first=current.continuation)
                styles[position] = current
            position += len(paragraph) + 1
    return ''.join(result), styles
