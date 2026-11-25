"""Native text transactions and position-aware container serialization.

The serializer retains stroke and audio records and relocates the container.
Unsupported structures fail before publication. Playback verification remains
separate from byte preservation and structural validation.
"""
from bisect import bisect_left, bisect_right
from copy import copy
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import accumulate, chain, pairwise
from pathlib import PureWindowsPath
import re
import struct
import unicodedata
import xml.etree.ElementTree as ET

from app.src.suggestion_filter import LABEL

from .codec import records, u32, validate_job
from .layout import read_layouts, read_deltas
from .elements import CENTERED_STYLE, CENTER_JUSTIFY
from .rendering import CONFLICT_STARTS, TextRenderer, render_record
from .caption import caption_display, caption_value, cover_end


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
        speakers.update(field_texts(job.native_bytes, display=True))
    return speakers, all_caps


def projected_groups(job, bundle, *, legacy_projection=False):
    speakers, all_caps = rendering_settings(job, bundle)
    end_cover = cover_end(job.native_bytes)
    renderer = TextRenderer(all_caps=all_caps, cover_tables=bool(end_cover), legacy_projection=legacy_projection)
    start, length = u32(job.native_bytes, 532), u32(job.native_bytes, 536)
    groups, group = [], []
    for offset, raw in records(job.native_bytes, start, start + length):
        if renderer.cover_tables and offset >= end_cover:
            renderer.cover_tables = False
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
    if compounds:
        for index, group in enumerate(groups):
            compact, cursor = [], 0
            while cursor < len(group):
                token = group[cursor]
                cursor += 1
                if token.offset not in compounds:
                    compact.append(token)
                    continue
                stop = token.offset + compounds[token.offset]
                items = [token]
                while cursor < len(group) and group[cursor].offset < stop:
                    items.append(group[cursor])
                    cursor += 1
                compact.append(Token(token.offset, b''.join(t.raw for t in items), ''.join(t.text for t in items)))
            groups[index] = compact
    if len(groups) != len(job.baseline.spans) or any(
            ''.join(t.text for t in group) != span.content
            for group, span in zip(groups, job.baseline.spans)):
        raise ValueError('Native source projection does not match its anchors.')
    return tuple(tuple(group) for group in groups)


# The source stream is immutable and every edited revision rewrites from it.
source_groups = lru_cache(maxsize=2)(projected_groups)


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
        elif not span.content:
            # Deleted edit fragments have no text to place. Empty source
            # anchors above still locate later unassociated insertions.
            continue
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


def native_group_targets(job):
    """Place each indivisible native element at one physical stroke."""
    targets = group_targets(job)
    text = job.text
    ends = list(accumulate(map(len, targets)))
    for element in job.export_elements:
        first = bisect_right(ends, element.start)
        last = bisect_left(ends, element.end)
        if first < last:
            # Native records cannot span strokes. Use the final affected one,
            # as range replacements do, and leave wording outside the element.
            ends[first:last] = [element.start] * (last - first)
    targets = [text[start:end] for start, end in pairwise(chain((0,), ends))]

    # A surviving symbol owns its paragraph break, even if range deletion left
    # that break anchored to the preceding source group.
    paragraph_symbols = {e.start for e in job.export_elements
                         if e.kind == 'symbol' and e.raw.startswith('16')}
    boundary = 0
    for index, target in enumerate(targets):
        owns_break = boundary in paragraph_symbols or target.startswith(('     Q    ', '     A    '))
        boundary += len(target)
        if index and target and owns_break:
            previous = next((i for i in range(index-1, -1, -1) if targets[i]), None)
            if previous is not None and targets[previous].endswith('\n'):
                targets[previous] = targets[previous][:-1]
                targets[index] = '\n' + targets[index]
    return targets


def encode_text(text, *, paragraph_start=False, atoms=None):
    """Encode editable wording and supported paragraph starts in Windows-1252."""
    if any(ord(c) < 32 and c not in '\n\t' for c in text):
        raise ValueError('Native text contains an unsupported control character.')
    result = bytearray()
    atoms = atoms or {}
    if atoms and text:
        # Each native paragraph symbol owns its break in the encoded stream.
        text = ''.join('\n' + char if atoms.get(char, b'').startswith(b'\x16') else char
                       for char in text)
    # Prefixes are logical paragraph labels, never generated page/line numbers.
    for index, paragraph in enumerate(text.split('\n')):
        # A physical Enter in CATalyst emits 16 ff 00. Pasted LF emitted
        # 16 08 00. Whole-document pagination also depends on other controls;
        # neither record alone resolves that remaining compatibility gap.
        style, body = 255, paragraph
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


def group_matches(before, after):
    """Keep matching text inside one native stroke, including long front matter."""
    if before == after:
        return [(0, 0, len(before))]
    if len(before) * len(after) <= 2_000_000:
        return SequenceMatcher(None, before, after, autojunk=False).get_matching_blocks()[:-1]

    from app.src.advanced_diff import text_edits

    # Anchor exact edges before the line-based diff can move a boundary in
    # repeated text. A local edit must not move the surrounding controls.
    shared = min(len(before), len(after))
    prefix = next((i for i, (a, b) in enumerate(zip(before, after)) if a != b), shared)
    suffix = next((i for i, (a, b) in enumerate(zip(reversed(before[prefix:]), reversed(after[prefix:])))
                   if a != b), shared - prefix)
    edits = text_edits(before[prefix:len(before) - suffix], after[prefix:len(after) - suffix])
    matches = [(0, 0, prefix)] if prefix else []
    end_a, end_b = len(before) - prefix, len(after) - prefix
    previous_a = previous_b = 0
    for a, b, c, d in (*edits, (end_a, end_a, end_b, end_b)):
        if a > previous_a:
            matches.append((prefix + previous_a, prefix + previous_b, a - previous_a))
        previous_a, previous_b = b, d
    return matches


def rewrite_group(tokens, target, *, paragraph_start=False, atoms=None):
    """Return each source token with generated bytes and a retained suffix."""
    old = ''.join(token.text for token in tokens)
    if old == target:
        return [(token, b'', token.raw) for token in tokens]
    keep = [False] * len(old)
    insertions = {}
    previous_a = previous_b = 0
    for a, b, size in (*group_matches(old, target), (len(old), len(target), 0)):
        if b > previous_b:
            insertions[previous_a] = target[previous_b:b]
        keep[a:a + size] = [True] * size
        previous_a, previous_b = a + size, b + size
    result, position = [], 0
    for token in tokens:
        if not token.text:
            result.append((token, b'', token.raw))
            continue
        end = position + len(token.text)
        leading_text = insertions.pop(position, '')
        retained = all(keep[position:end]) and not any(i in insertions for i in range(position + 1, end))
        if (retained and leading_text.endswith('\n') and token.raw.startswith(b'\x16')
                and not token.text.startswith('\n') and token.text not in (atoms or {})):
            # An unmasked legacy prefix still displays as ordinary spaces.
            # Its retained control supplies the boundary after an insertion.
            leading_text = leading_text[:-1]
        leading = encode_text(leading_text,
                              paragraph_start=paragraph_start and position == 0, atoms=atoms)
        if retained:
            result.append((token, leading, token.raw))
        else:
            visible = ''
            for index in range(position, end):
                if index != position:
                    visible += insertions.pop(index, '')
                if keep[index]:
                    visible += old[index]
            result.append((token, leading + encode_text(visible, atoms=atoms), b''))
        position = end
    tail = encode_text(insertions.pop(len(old), ''), paragraph_start=paragraph_start and not old, atoms=atoms)
    if tail:
        offset = tokens[-1].offset + len(tokens[-1].raw)
        result.append((Token(offset, b'', ''), tail, b''))
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


def relink_wave(native, old_name, new_name):
    """Update the bundled WAV filename in the known CATalyst audio section."""
    if len(native) < 1024 or not native.startswith(b'SGCAT32\0'):
        return native
    start, size = struct.unpack_from('<II', native, 556)
    path_width = 260
    if start < u32(native, 532) + u32(native, 536) or size < path_width + 4 or start + size > len(native):
        return native
    path_end = start + path_width
    if size != path_width + 4 + 12 * u32(native, path_end):
        return native
    paths, terminator, padding = native[start:path_end].partition(b'\0\0')
    if not terminator or any(padding):
        return native
    old_key = unicodedata.normalize('NFC', old_name).casefold()
    paths = paths.split(b'\0')
    matches = [index for index, path in enumerate(paths)
               if unicodedata.normalize('NFC', PureWindowsPath(path.decode('cp1252', errors='replace')).name).casefold() == old_key]
    if not matches:
        return native
    try:
        name = new_name.encode('cp1252')
    except UnicodeEncodeError as exc:
        raise ValueError('The exported WAV filename must use Windows-1252 characters.') from exc
    # A local filename follows the job when restored into another case.
    for index in matches:
        paths[index] = name
    linked = b'\0'.join(paths)
    if len(linked) > path_width - 2:
        raise ValueError('The exported WAV filenames are too long for CaseCAT.')
    return native[:start] + linked.ljust(path_width, b'\0') + native[path_end:]


def _colloquy_indents(text, elements, element_starts):
    """Locate the plain five-space prefixes of speaker paragraphs."""
    indents, start = {}, 0
    for line in text.split('\n'):
        label = LABEL.match(line) if line.startswith('     ') else None
        if label and label['prefix'] == '     ':
            end = start + label.start('name')
            last = bisect_left(element_starts, end) - 1
            if last < 0 or elements[last].end <= start:
                indents[start] = end
        start += len(line) + 1
    return indents


def _word_gap(text, position):
    """Identify the word boundary at a control, excluding surrounding punctuation."""
    left = right = position
    while left and text[left - 1] == ' ':
        left -= 1
    while right < len(text) and text[right] == ' ':
        right += 1
    if (left == right or left == 0 or right == len(text)
            or text[left - 1].isspace() or text[right].isspace()):
        return None
    start, stop = left - 1, right + 1
    while start and text[start - 1].isalnum():
        start -= 1
    while stop < len(text) and text[stop].isalnum():
        stop += 1
    return left - 1, right, text[start:stop]


def _legacy_delete_spaces(revision):
    # Older exports left two empty translated strokes when replacing a word
    # and its suffix. A standalone Delete Space can also be intentional.
    groups = set()
    position = 0
    for index, span in enumerate(revision.spans):
        if index and not span.content and span.formatting == ('04', '0e', '0b'):
            previous = revision.spans[index - 1]
            gap = _word_gap(revision.text, position)
            if (not previous.content and previous.formatting == ('0e', '0b')
                    and gap and gap[1] - gap[0] == 2):
                groups.add(index)
        position += len(span.content)
    return groups


def repair_legacy_spacing(job, bundle):
    legacy_joins = _legacy_delete_spaces(job.baseline)
    if legacy_joins:
        try:
            return _write_revision(job, bundle, legacy_joins)
        except ValueError:
            # An unedited copy can still be exported when its layout cannot
            # be rewritten safely. The source archive remains authoritative.
            pass
    return job.native_bytes


def serialize_candidate(job, bundle):
    validate_job(bundle, job)
    if job.revision == job.baseline:
        return job.native_bytes
    return _write_revision(job, bundle, _legacy_delete_spaces(job.baseline))


def _retained_join_gaps(baseline, groups, targets, legacy_joins):
    """Locate the same two source characters in the reviewed stroke groups."""
    source_starts = list(accumulate((len(s.content) for s in baseline.spans), initial=0))
    target_starts = list(accumulate(map(len, targets), initial=0))

    @lru_cache(maxsize=None)
    def matches(index):
        return group_matches(baseline.spans[index].content, targets[index])

    def destination(position):
        index = bisect_right(source_starts, position) - 1
        local = position - source_starts[index]
        for old, new, size in matches(index):
            if old <= local < old + size:
                return target_starts[index] + new + local - old
        return None

    retained = {}
    for index, span in enumerate(baseline.spans):
        if '04' not in span.formatting or index in legacy_joins:
            continue
        position = source_starts[index]
        for token in groups[index]:
            if token.raw == b'\x04':
                gap = _word_gap(baseline.text, position)
                if gap:
                    old_left, old_right, words = gap
                    left, right = destination(old_left), destination(old_right)
                    if left is not None and right is not None:
                        retained[token.offset] = (left, right, words)
            position += len(token.text)
    return retained


def _mask_conflict_separators(tokens, target, atoms):
    """Match a separator by its caret, independently of its generated spaces."""
    if not any(token.raw == b'\x02' and token.text for token in tokens):
        return tokens, target
    original = ''.join(token.text for token in tokens)
    if original == target:
        return tokens, target
    matches = iter(group_matches(original, target))
    match = next(matches, None)
    parts, cursor, end = [], 0, 0
    for index, token in enumerate(tokens):
        cursor += len(token.text)
        if token.raw != b'\x02' or not token.text:
            continue
        caret = cursor - len(token.text) + token.text.index('^')
        while match and match[0] + match[2] <= caret:
            match = next(matches, None)
        if match is None:
            break
        old, new, _ = match
        if caret < old:
            continue
        caret += new - old
        start = caret
        if token.text.startswith(' ') and caret > end and target[caret - 1] == ' ':
            start -= 1
        marker = chr(0xf0000 + len(atoms))
        atoms[marker] = token.raw
        tokens[index] = replace(token, text=marker)
        parts.extend((target[end:start], marker))
        end = caret + (2 if target.startswith('^ ', caret) else 1)
    parts.append(target[end:])
    return tokens, ''.join(parts)


def _rewritten_tokens(job, groups, targets, elements, element_starts):
    # Match native elements by identity, not by the letters displayed inside
    # them. A field value edit must never turn its reference into literal text.
    original_elements = {e.source: e for e in job.baseline.elements}
    current_elements = {e.source: e for e in elements if e.source is not None}
    markers, atoms = {}, {}
    for element in (*job.baseline.elements, *elements):
        if element.name == 'Center Justify' and element.kind == 'symbol':
            continue
        key = element.source if element.source is not None else element
        if key not in markers:
            markers[key] = chr(0xf0000 + len(markers))
        atoms[markers[key]] = bytes.fromhex(element.raw)
    cursor = 0
    for group, target in zip(groups, targets):
        stop = cursor + len(target)
        first = bisect_left(element_starts, cursor)
        last = bisect_left(element_starts, stop) if stop > cursor else bisect_right(element_starts, cursor)
        for element in reversed(elements[first:last]):
            if element.end <= stop:
                key = element.source if element.source is not None else element
                marker = markers[key]
                start = element.start - cursor
                # Diff the whole native paragraph start as one unit. A shared
                # newline alone must never match a different speaker turn.
                if start and target[start - 1] == '\n' and atoms[marker].startswith(b'\x16'):
                    start -= 1
                target = target[:start] + marker + target[element.end-cursor:]
        masked = []
        for token in group:
            element = original_elements.get(token.offset)
            # Older saved revisions represent a colloquy indent as five
            # ordinary spaces. Match that projection so its source paragraph
            # survives a later edit elsewhere in the job.
            if element and element.name == 'Colloquy' and token.offset not in current_elements:
                element = None
            if element:
                updated = current_elements.get(token.offset, element)
                token = replace(token, text=markers[element.source], raw=bytes.fromhex(updated.raw))
            masked.append(token)
        masked, target = _mask_conflict_separators(masked, target, atoms)
        yield from rewrite_group(masked, target, paragraph_start=cursor == 0, atoms=atoms)
        cursor = stop


def _translated_conflict_edits(edits):
    """Keep paired framing and its first separator together in the native stream."""
    frame = []
    for edit in edits:
        token, _, _ = edit
        if token.raw in CONFLICT_STARTS:
            yield from frame
            frame = [edit]
        elif not frame:
            yield edit
        else:
            frame.append(edit)
            if token.raw != b'\x03':
                continue
            opener, before, retained_opener = frame[0]
            separator, leading, retained_separator = frame[1]
            if sum(t.raw == b'\x02' for t, _, _ in frame) >= 2 and not any(
                    kept == b'\x02' or any(raw == b'\x02' for _, raw in records(new, 0, len(new)))
                    for _, new, kept in frame):
                frame[0] = (opener, before, b'')
                closing, before_end, _ = frame[-1]
                frame[-1] = (closing, before_end, b'')
            elif retained_separator == b'\x02' and leading:
                # Adjacent opener and first separator begin the linked range.
                # A paste immediately before that caret remains outside it.
                frame[0] = (opener, before + leading, retained_opener)
                frame[1] = (separator, b'', retained_separator)
            yield from frame
            frame = []
    yield from frame


def _opening_paragraph_edits(edits, text):
    """Keep the opening style and the first visible paragraph distinct."""
    if not text:
        return edits
    leading_break = text.startswith('\n')
    prefix = []
    opening = None
    for edit in edits:
        token, generated, retained = edit
        prefix.append(edit)
        if generated or (retained and token.text):
            if leading_break and opening is None:
                # CaseCAT Enter at the top adds an invisible default opener
                # before the first stroke so the next paragraph displays a break.
                first, first_generated, first_retained = prefix[0]
                prefix[0] = (first, b'\x16\xff\x00' + first_generated, first_retained)
            elif not leading_break and opening is not None and (generated or retained).startswith(b'\x16'):
                # Keep the source position for relocation, including when the
                # new paragraph follows one or more emptied stroke groups.
                prefix[opening] = (prefix[opening][0], b'', b'')
            break
        if retained.startswith(b'\x16'):
            opening = len(prefix) - 1
    return chain(prefix, edits)


def _render_field(renderer, raw, speakers, text, field, position):
    if field is None or raw.hex() != field.raw:
        raise ValueError(f'Native field reference does not match the edit at character {position}.')
    expected = text[field.start:field.end]
    for control in (b'', b'\x12\x8e', b'\x12\x0e'):
        candidate = copy(renderer)
        if control:
            candidate.control(control)
        rendered = render_record(candidate, raw, speakers)
        if rendered == expected:
            return rendered, candidate, control
    raise ValueError(f'Native field casing cannot preserve the edit at character {position}.')


def _write_revision(job, bundle, legacy_joins):
    text = job.text
    groups = source_groups(job.with_revision(job.baseline), bundle)
    targets = native_group_targets(job)
    stream, positions = bytearray(), []
    start = u32(job.native_bytes, 532)
    speakers, all_caps = rendering_settings(job, bundle)
    from .fields import field_values
    values = field_values(job.revision)
    baseline_values = field_values(job.baseline)
    end_cover = cover_end(job.native_bytes)
    wrapped = bool(end_cover)
    speakers.update({name: caption_display(caption_value(name, value)) if wrapped else value for name, value in values.items()
                     if value != baseline_values.get(name)})
    centers = {e.start for e in job.revision.elements if e.kind == 'symbol' and e.name == 'Center Justify'}
    elements = tuple(e for e in job.export_elements if not (e.kind == 'symbol' and e.name == 'Center Justify'))
    element_starts = [element.start for element in elements]
    fields_at = {element.start: element for element in elements if element.kind == 'field'}
    layouts = read_layouts(job.native_bytes)
    colloquy_indents = (_colloquy_indents(text, elements, element_starts)
                       if layouts and len(layouts[0].paragraphs) >= 4 else {})
    indent_end = 0
    renderer, visible = TextRenderer(all_caps=all_caps, cover_tables=wrapped), 0
    retained_gaps = _retained_join_gaps(job.baseline, groups, targets, legacy_joins)
    centered = 0 in centers
    examination_styles = job.examination_styles
    use_style_geometry = False
    edits = _translated_conflict_edits(_rewritten_tokens(job, groups, targets, elements, element_starts))
    for token, generated, retained in _opening_paragraph_edits(edits, text):
        if renderer.cover_tables and token.offset >= end_cover:
            renderer.cover_tables = False
        encoded = bytearray()
        rewritten = generated + retained
        for record_start, raw in records(rewritten, 0, len(rewritten)):
            # A heading can span strokes or diff fragments. Set the style at
            # the complete paragraph's position without moving any wording.
            if raw[0] == 0x16:
                wanted = examination_styles.get(visible + int(renderer.has_content))
                use_style_geometry = wanted is not None and (record_start < len(generated)
                                                              or int.from_bytes(raw[1:], 'little') != wanted)
                if wanted == CENTERED_STYLE:
                    raw = b'\x16\x07\x00'
            elif not renderer.has_content and examination_styles.get(0) == CENTERED_STYLE and raw[0] >= 32:
                encoded += b'\x16\x07\x00'
                renderer.paragraph(CENTERED_STYLE)
                use_style_geometry = True
            if (centered or use_style_geometry) and raw[:2] == b'\x15\x03':
                # A newly assigned style supplies its own indent and alignment.
                overridden = (10, 12) if use_style_geometry else (12,)
                payload = b''.join(bytes([kind]) + value for kind, value in read_deltas(raw[6:])
                                   if kind not in overridden)
                if not payload:
                    continue
                raw = raw[:2] + struct.pack('<I', len(payload)) + payload
            if raw == token.raw == b'\x04':
                # A dictionary join survives edits to unrelated text. It
                # must not consume a space at a new word boundary.
                gap = _word_gap(text, visible)
                if gap and gap != retained_gaps.get(token.offset):
                    continue
            conflict_space = (raw == b'\x02' and renderer.conflict_choice == 1
                              and text.startswith(' ^ ', visible))
            if conflict_space:
                # The retained separator needs an independent literal here.
                renderer.literal(' ')
            field_case = b''
            if raw[:2] == b'\x15\x07':
                rendered, renderer, field_case = _render_field(
                    renderer, raw, speakers, text, fields_at.get(visible), visible)
            else:
                rendered = render_record(renderer, raw, speakers)
            if conflict_space:
                rendered = ' ' + rendered
            paragraph = raw[0] == 0x16
            paragraph_start = visible + int(rendered.startswith('\n'))
            if paragraph:
                centered = paragraph_start in centers
            if rendered and visible == 0 and 0 in centers and (not paragraph or rendered.startswith('\n')):
                encoded += CENTER_JUSTIFY
                centers.remove(0)
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
                    # The marker resets case and punctuation. Rendering the
                    # literal again reproduces the final character state.
                    renderer.control(marker)
                    rendered = render_record(renderer, raw, speakers)
            if not text.startswith(rendered, visible):
                if raw == b'\x02':
                    raise ValueError(f'The native conflict separator needs its spacing at character {visible}. '
                                     'Keep the required space or resolve the conflict to an alternative.')
                raise ValueError(f'Native rendering cannot preserve the edit at character {visible}.')
            visible += len(rendered)
            if raw == b'\x16\xff\x00' and record_start < len(generated) and visible in colloquy_indents:
                # The native colloquy style supplies the indent. Consume the
                # logical padding even when it is split across stroke groups.
                encoded += b'\x16\x04\x00'
                indent_end = colloquy_indents[visible]
            elif visible > indent_end or raw not in (b' ', b'\x01'):
                if conflict_space:
                    encoded += b' '
                encoded += field_case + raw
            if paragraph and centered:
                encoded += CENTER_JUSTIFY
                centers.remove(paragraph_start)
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
                                  if value != baseline_values.get(name)}, wrap_captions=wrapped)
