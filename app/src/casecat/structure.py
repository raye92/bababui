"""Native text transactions and position-aware container serialization.

The serializer retains stroke and audio records and relocates the container.
Unsupported structures fail before publication. Playback verification remains
separate from byte preservation and structural validation.
"""
from bisect import bisect_right
from dataclasses import dataclass, replace
from copy import copy
from difflib import SequenceMatcher
import re
import struct
import xml.etree.ElementTree as ET

from .codec import records, u32, validate_job
from .rendering import TextRenderer, render_record


@dataclass(frozen=True)
class Token:
    offset: int
    raw: bytes
    text: str


def rendering_settings(job, bundle):
    speakers, all_caps = {}, False
    member = bundle.member(job.key + '.sgxml')
    if member:
        root = ET.fromstring(bundle.read(member))
        speakers = {node.tag.removeprefix('Speaker-'): node.get('sgpref-val', '')
                    for node in root.iter() if node.tag.startswith('Speaker-')}
        all_caps = any(node.tag == 'Capitalize-All-Text' and node.get('sgpref-val') == '1'
                       for node in root.iter())
    if any(e.kind == 'field' for e in job.baseline.elements):
        from .field_table import field_texts
        speakers.update(field_texts(job.native_bytes))
    return speakers, all_caps


def projected_groups(job, bundle):
    speakers, all_caps = rendering_settings(job, bundle)
    renderer = TextRenderer(all_caps=all_caps)
    start, length = u32(job.native_bytes, 532), u32(job.native_bytes, 536)
    groups, group = [], []
    for offset, raw in records(job.native_bytes, start, start + length):
        op = raw[0]
        if op == 0x13 and group:
            groups.append(group)
            group = []
        text = render_record(renderer, raw, speakers)
        group.append(Token(offset, raw, text))
    if group:
        groups.append(group)
    compounds = {e.source: len(bytes.fromhex(e.raw)) for e in job.baseline.elements
                 if e.name == 'By-line'}
    for index, group in enumerate(groups):
        compact, cursor = [], 0
        while cursor < len(group):
            token = group[cursor]
            stop = token.offset + compounds.get(token.offset, len(token.raw))
            items = [token]
            cursor += 1
            while cursor < len(group) and group[cursor].offset < stop:
                items.append(group[cursor])
                cursor += 1
            compact.append(Token(token.offset, b''.join(t.raw for t in items), ''.join(t.text for t in items)))
        groups[index] = compact
    if len(groups) != len(job.baseline.spans) or any(
            ''.join(t.text for t in group) != span.content
            for group, span in zip(groups, job.baseline.spans)):
        raise ValueError('Native source projection does not match its anchors.')
    return groups


def group_targets(job):
    """Keep unchanged text at its actual source anchor, including repetitions."""
    sources = {span.identity: index for index, span in enumerate(job.baseline.spans)}
    by_stroke = {ref: index for index, span in enumerate(job.baseline.spans) for ref in span.stroke_refs}
    result = [''] * len(sources)
    current = 0
    following, bound = {}, len(sources)-1
    for index in range(len(job.revision.spans)-1, -1, -1):
        span = job.revision.spans[index]
        following[index] = bound
        if span.content and span.identity in sources:
            bound = sources[span.identity]
    previous = 0
    for index, span in enumerate(job.revision.spans):
        if span.identity in sources:
            current = sources[span.identity]
            target = current
        elif span.stroke_refs:
            candidates = sorted({by_stroke[ref] for ref in span.stroke_refs})
            # Legacy whole-text edits can carry overly broad associations.
            # Retained source anchors bound the passage's physical location;
            # choose only an associated clock within that ordered interval.
            candidates = [n for n in candidates if previous <= n <= following[index]]
            if not candidates:
                raise ValueError('The revision requires native anchor reordering, which is not yet verified.')
            # The measured cross-anchor CATalyst replacement uses the final
            # affected stroke clock. Keeping wording at the first group makes
            # the unchanged suffix seek early at its leading word boundary.
            # A one-group insertion still uses its insertion-point association.
            target = candidates[-1]
        else:
            target = current
        if span.content:
            result[target] += span.content
            previous = target
    if ''.join(result) != job.text:
        raise ValueError('The revision requires native anchor reordering, which is not yet verified.')
    return result


def encode_text(text, *, paragraph_start=False, atoms=None):
    """Encode editable wording and supported paragraph starts in Windows-1252."""
    if any(ord(c) < 32 and c != '\n' for c in text):
        raise ValueError('Native text contains an unsupported control character.')
    result = bytearray()
    atoms = atoms or {}
    # Prefixes are logical paragraph labels, never generated page/line numbers.
    for index, paragraph in enumerate(text.split('\n')):
        # A physical Enter in CATalyst emits 16 ff 00. Pasted LF emitted
        # 16 08 00. Whole-document pagination also depends on other controls;
        # neither record alone resolves that remaining compatibility gap.
        style, body = 255, paragraph
        if (index or paragraph_start) and re.fullmatch(r'(?:FURTHER )?EXAMINATION', paragraph):
            style = 7  # Native Centered Paragraph Style, not padding spaces.
        if paragraph_start and index == 1 and not text.split('\n', 1)[0]:
            style = 8
        for prefix, value in (('     Q    ', 2), ('     A    ', 3)):
            if (index or paragraph_start) and paragraph.startswith(prefix):
                style, body = value, paragraph[len(prefix):]
                break
        native_prefix = bool(paragraph and atoms.get(paragraph[0], b'')[:1] == b'\x16')
        if (index or style != 255) and not native_prefix:
            result += b'\x16' + struct.pack('<H', style)
        try:
            for char in body:
                result += atoms[char] if char in atoms else char.encode('cp1252')
        except UnicodeEncodeError as exc:
            raise ValueError('This CaseCAT format supports Windows-1252 characters; the edit contains another character.') from exc
    return bytes(result)


def rewrite_group(tokens, target, *, paragraph_start=False, atoms=None):
    old = ''.join(token.text for token in tokens)
    if old == target:
        return [(token, token.raw) for token in tokens]
    keep = [False] * len(old)
    insertions = {}
    if len(old) * len(target) > 2_000_000:
        operations = [('replace', 0, len(old), 0, len(target))]
    else:
        operations = SequenceMatcher(None, old, target, autojunk=False).get_opcodes()
    for tag, a, b, c, d in operations:
        if tag == 'equal':
            keep[a:b] = [True] * (b - a)
        elif tag in ('insert', 'replace'):
            insertions[a] = target[c:d]
    result, position = [], 0
    for token in tokens:
        if not token.text:
            result.append((token, token.raw))
            continue
        end = position + len(token.text)
        leading_text = insertions.pop(position, '')
        retained = all(keep[position:end]) and not any(i in insertions for i in range(position + 1, end))
        if retained and token.raw[:1] == b'\x16' and not token.text.startswith('\n') and leading_text.endswith('\n'):
            # A retained native paragraph control supplies this boundary itself.
            # Encoding both the inserted LF and the control adds an empty line.
            leading_text = leading_text[:-1]
        leading = encode_text(leading_text,
                              paragraph_start=paragraph_start and position == 0, atoms=atoms)
        if retained:
            rewritten = leading + token.raw
        else:
            visible = ''
            for index in range(position, end):
                if index != position:
                    visible += insertions.pop(index, '')
                if keep[index]:
                    visible += old[index]
            rewritten = leading + encode_text(visible, atoms=atoms)
        result.append((token, rewritten))
        position = end
    tail = encode_text(insertions.pop(len(old), ''), paragraph_start=paragraph_start and not old, atoms=atoms)
    if tail:
        offset = tokens[-1].offset + len(tokens[-1].raw)
        result.append((Token(offset, b'', ''), tail))
    if insertions:
        raise ValueError('Unmapped native text edit.')
    return result


def repair_history(stream):
    """Recompute the current-body length of paired translation-history records."""
    result, stack = bytearray(stream), []
    for offset, raw in records(stream, 0, len(stream)):
        if raw[0] == 0x18:
            stack.append((offset, offset + len(raw)))
        elif raw[0] == 0x19:
            if not stack:
                raise ValueError('Unpaired native translation history end.')
            header, start = stack.pop()
            length = offset - start
            if length > 65535:
                raise ValueError('An edited translation-history body exceeds the native 16-bit length.')
            struct.pack_into('<H', result, header + 6, length)
    if stack:
        raise ValueError('Unclosed native translation history.')
    return bytes(result)


def relocate(native, stream, positions):
    """Relocate the known section directory and every position-index entry.

    Counts are read from the file. Unresolved section kinds fail closed instead
    of pretending their opaque payloads cannot contain positions.
    """
    start, length = u32(native, 532), u32(native, 536)
    end, index, size = start + length, u32(native, 588), u32(native, 592)
    if start != 1024 or end > len(native) or index < end or index + size > len(native):
        raise ValueError('Unsupported native section layout.')
    if any(u32(native, field) for field in (596, 600, 608, 620)):
        raise ValueError('This job contains unresolved native sections.')
    # Header pairs written by the native 22.1 container writer. Their order on
    # disk is independent of their order in the header.
    section_fields = (540, 548, 556, 564, 572, 580, 588, 612, 632, 644)
    extents = [(0, end)]
    for field in section_fields:
        offset, section_size = u32(native, field), u32(native, field + 4)
        if not offset and section_size:
            raise ValueError('A native section has no address.')
        if offset and (offset < end or offset + section_size > len(native)):
            raise ValueError('Invalid native section bounds.')
        if section_size:
            extents.append((offset, offset + section_size))
    extended = index + size
    if native[extended:extended + 8] != b'2XSTRMZ\0':
        raise ValueError('Missing native extended-stream directory.')
    count = u32(native, extended + 8)
    if count > 4096:
        raise ValueError('Invalid native extended-stream count.')
    table, pointers = extended + 32, []
    directory_end = table + count * 8
    if directory_end > len(native):
        raise ValueError('Truncated extended native directory.')
    extents.append((extended, directory_end))
    for number in range(count):
        field = table + number * 8
        offset, section_size = u32(native, field), u32(native, field + 4)
        if offset < directory_end or offset + section_size > len(native):
            raise ValueError('Invalid extended native section.')
        pointers.append(field)
        if section_size:
            extents.append((offset, offset + section_size))
    cursor = 0
    for low, high in sorted(extents):
        if low != cursor:
            raise ValueError('Overlapping or unaccounted native section data.')
        cursor = high
    if cursor != len(native):
        raise ValueError('Unaccounted native trailing data.')
    old_starts = [entry[0] for entry in positions]

    def mapped(position):
        if not 0 <= position <= length:
            raise ValueError('Native position exceeds its stream.')
        if position == length:
            return len(stream)
        old, new, old_size, new_size = positions[max(0, bisect_right(old_starts, position) - 1)]
        return new + min(position - old, new_size)

    delta = len(stream) - length
    result = bytearray(native)
    struct.pack_into('<I', result, 512, mapped(u32(native, 512)))
    struct.pack_into('<I', result, 536, len(stream))
    for field in (*section_fields, *pointers):
        if u32(native, field):
            struct.pack_into('<I', result, field, u32(native, field) + delta)
    previous = -1
    from .layout import index_positions
    for field, primary in index_positions(native):
        position = u32(native, field)
        if primary and position < previous:
            raise ValueError('Unordered native position index.')
        if primary:
            previous = position
        struct.pack_into('<I', result, field, mapped(position))
    result[start:end] = stream
    return bytes(result)


def serialize_candidate(job, bundle):
    validate_job(bundle, job)
    if job.revision == job.baseline:
        return job.native_bytes
    text = job.text
    groups = projected_groups(job, bundle)
    targets = group_targets(job)
    # A surviving symbol owns its paragraph break, even if range deletion left
    # that break anchored to the preceding source group.
    for index in range(1, len(targets)):
        if targets[index].startswith(('     Q    ', '     A    ')):
            previous = next((i for i in range(index-1, -1, -1) if targets[i]), None)
            if previous is not None and targets[previous].endswith('\n'):
                targets[previous] = targets[previous][:-1]
                targets[index] = '\n' + targets[index]
    stream, positions = bytearray(), []
    start = u32(job.native_bytes, 532)
    speakers, all_caps = rendering_settings(job, bundle)
    from .fields import field_values
    values = field_values(job.revision)
    baseline_values = field_values(job.baseline)
    speakers.update(values)
    # Match native elements by identity, not by the letters displayed inside
    # them. A field value edit must never turn its reference into literal text.
    original_elements = {e.source: e for e in job.baseline.elements}
    current_elements = {e.source: e for e in job.revision.elements if e.source is not None}
    markers, atoms = {}, {}
    for element in (*job.baseline.elements, *job.revision.elements):
        key = element.source if element.source is not None else element
        if key not in markers:
            markers[key] = chr(0xf0000 + len(markers))
        atoms[markers[key]] = bytes.fromhex(element.raw)
    cursor = 0
    renderer, visible = TextRenderer(all_caps=all_caps), 0
    for group, target in zip(groups, targets):
        stop = cursor + len(target)
        for element in reversed(job.revision.elements):
            if cursor <= element.start and element.end <= stop and (element.start < stop or element.start == element.end == cursor):
                key = element.source if element.source is not None else element
                target = target[:element.start-cursor] + markers[key] + target[element.end-cursor:]
        masked = []
        for token in group:
            element = original_elements.get(token.offset)
            if element:
                updated = current_elements.get(token.offset, element)
                prefix = '\n' if element.kind == 'symbol' and token.text.startswith('\n') else ''
                token = replace(token, text=prefix + markers[element.source], raw=bytes.fromhex(updated.raw))
            masked.append(token)
        cursor = stop
        for token, rewritten in rewrite_group(masked, target, paragraph_start=visible == 0, atoms=atoms):
            encoded = bytearray()
            for _, raw in records(rewritten, 0, len(rewritten)):
                if (raw[0] == 0x16 and int.from_bytes(raw[1:], 'little') not in (8, 255)
                        and not renderer.has_content and text.startswith('\n', visible)):
                    encoded += b'\x16\xff\x00'
                    renderer.paragraph(255)
                trial = copy(renderer)
                rendered = render_record(trial, raw, speakers)
                if rendered and not text.startswith(rendered, visible) and raw[0] >= 32:
                    literal = raw.decode('cp1252')
                    marker = None
                    if literal.islower() and not all_caps:
                        if text.startswith(literal, visible):
                            marker = b'\x12\x8e'
                        elif text.startswith(literal.upper(), visible):
                            marker = b'\x12\x0e'
                    if marker:
                        encoded += marker
                        renderer.control(marker)
                        trial = copy(renderer)
                        rendered = render_record(trial, raw, speakers)
                if not text.startswith(rendered, visible):
                    raise ValueError(f'Native rendering cannot preserve the edit at character {visible}.')
                visible += len(rendered)
                renderer = trial
                encoded += raw
            positions.append((token.offset - start, len(stream), len(token.raw), len(encoded)))
            stream += encoded
    if visible != len(text):
        raise ValueError('Native serialization lost displayed content.')
    stream = repair_history(bytes(stream))
    result = relocate(job.native_bytes, stream, positions)
    original_records = list(records(job.native_bytes, start, start + u32(job.native_bytes, 536)))
    new_records = list(records(result, start, start + len(stream)))
    for predicate in (lambda raw: raw[0] == 0x13,
                      lambda raw: raw[:2] == b'\x15\x08'):
        if [raw for _, raw in original_records if predicate(raw)] != [raw for _, raw in new_records if predicate(raw)]:
            raise ValueError('Native serialization changed original stroke or audio records.')
    from .field_table import rewrite_fields
    return rewrite_fields(result, {name: value for name, value in values.items()
                                  if value != baseline_values.get(name)})
