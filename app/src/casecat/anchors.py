"""Immutable editorial associations, independent of Qt and the native writer."""
from dataclasses import dataclass, replace
from bisect import bisect_left, bisect_right
from functools import cached_property
from itertools import accumulate
import re
import uuid

from .elements import NativeElement, edited_elements, paragraph_symbols


@dataclass(frozen=True)
class AnchoredSpan:
    identity: str
    # Ordered embedded stroke occurrences, including distinct copies of a
    # reused original note. They index NativeJob.stroke_clocks for playback.
    stroke_refs: tuple[int, ...]
    audio: tuple[str, ...]
    content: str
    formatting: tuple[str, ...] = ()


def _ordered(values):
    return tuple(dict.fromkeys(values))


def _validate_field_value(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError('A field value must be a single line.')
    try:
        value.encode('cp1252')
    except UnicodeEncodeError as exc:
        raise ValueError('Field values must use Windows-1252 characters.') from exc


def utf16_index(text, offset):
    """Convert a Qt offset, rejecting a position inside a surrogate pair."""
    if not isinstance(offset, int) or offset < 0:
        raise ValueError('Invalid UTF-16 offset.')
    if text.isascii():
        if offset <= len(text):
            return offset
        raise ValueError('UTF-16 offset exceeds the document.')
    encoded = text.encode('utf-16-le', 'surrogatepass')
    if 2 * offset > len(encoded):
        raise ValueError('UTF-16 offset exceeds the document.')
    if offset and 2 * offset < len(encoded) and 0xdc <= encoded[2 * offset + 1] <= 0xdf:
        if 0xd8 <= encoded[2 * offset - 1] <= 0xdb:
            raise ValueError('UTF-16 offset splits a character.')
    return len(encoded[:2 * offset].decode('utf-16-le', 'surrogatepass'))


@dataclass(frozen=True)
class Revision:
    spans: tuple[AnchoredSpan, ...]
    elements: tuple[NativeElement, ...] = ()
    all_caps: bool = False
    definitions: tuple[tuple[str, str], ...] = ()

    @cached_property
    def text(self):
        return ''.join(span.content for span in self.spans)

    @cached_property
    def _span_ends(self):
        return tuple(accumulate(len(span.content) for span in self.spans))

    @cached_property
    def _supplementary_positions(self):
        if self.text.isascii():
            return ()
        return tuple(m.start() for m in re.finditer(r'[\U00010000-\U0010ffff]', self.text))

    def utf16_offset(self, position):
        """Return the Qt offset for a Python character boundary in this revision."""
        if not isinstance(position, int) or not 0 <= position <= len(self.text):
            raise ValueError('Invalid character offset.')
        return position + bisect_left(self._supplementary_positions, position)

    def replace_utf16(self, position, removed, inserted):
        text = self.text
        return self.replace(utf16_index(text, position), utf16_index(text, position + removed), inserted)

    def replace(self, start, end, content):
        if not isinstance(content, str) or not 0 <= start <= end <= len(self.text):
            raise ValueError('Invalid native edit range.')
        for element in self.elements:
            inside = (element.start <= start < end <= element.end or
                      element.start < start == end < element.end)
            if not inside:
                continue
            if element.kind == 'field' and (content or start != element.start or end != element.end):
                if element.wrap_caption and element.value:
                    from .caption import caption_offsets
                    offsets = caption_offsets(element.name, element.value)
                    first, last = offsets[start - element.start], offsets[end - element.start]
                    value = element.value[:first] + content + element.value[last:]
                else:
                    value = self.text[element.start:start] + content + self.text[end:element.end]
                return self.set_field(element.name, value)
            if element.kind == 'symbol':
                label = content.strip()
                if label in ('Q', 'A'):
                    symbol = replace(element, raw='160200' if label == 'Q' else '160300')
                    elements = tuple(symbol if e is element else e for e in self.elements)
                    return replace(self, elements=elements)._replace(
                        element.start, element.end, f'     {label}    ', preserve=symbol)
                return self._replace(element.start, element.end, content)
        # A selection cannot leave half a native field or generated label behind.
        for element in self.elements:
            if start < element.end and end > element.start:
                start, end = min(start, element.start), max(end, element.end)
        return self._replace(start, end, content)

    def set_field(self, name, value):
        _validate_field_value(value)
        fields = [e for e in self.elements if e.kind == 'field' and e.name == name]
        definitions = dict(self.definitions)
        if not fields and name not in definitions:
            raise ValueError('The selected native field is no longer present.')
        definitions[name] = value
        result = replace(self, definitions=tuple(sorted(definitions.items())))
        for element in reversed(fields):
            from .fields import rendered_value
            updated = replace(element, value=value)
            result = replace(result, elements=tuple(updated if e is element else e for e in result.elements))
            result = result._replace(element.start, element.end,
                                     rendered_value(result.text[:element.start], value, name,
                                                    all_caps=self.all_caps or element.uppercase,
                                                    wrap_caption=element.wrap_caption),
                                     preserve=updated)
        return result

    def define_field(self, name, value=''):
        from .field_table import field_record
        from .fields import field_values
        name = name.strip().upper()
        field_record(name)
        if name in field_values(self):
            raise ValueError('That field name already exists.')
        definitions = dict(self.definitions)
        definitions[name] = ''
        return replace(self, definitions=tuple(sorted(definitions.items()))).set_field(name, value)

    def insert_field(self, position, name, value):
        from .field_table import field_record
        from .fields import rendered_value
        self.atomic_range(position, position)
        name = name.strip().upper()
        raw = field_record(name)
        _validate_field_value(value)
        existing = next((e for e in self.elements if e.kind == 'field' and e.name == name), None)
        if existing:
            raw = bytes.fromhex(existing.raw)
            value = existing.value if existing.value is not None else self.text[existing.start:existing.end]
        elif name in dict(self.definitions):
            value = dict(self.definitions)[name]
        wrap = bool(existing and existing.wrap_caption)
        display = rendered_value(self.text[:position], value, name, all_caps=self.all_caps, wrap_caption=wrap)
        result = self._replace(position, position, display)
        element = NativeElement(position, position + len(display), 'field', raw.hex(), name,
                                existing.source if existing else None, value, wrap)
        definitions = dict(result.definitions)
        definitions[name] = value
        return replace(result, elements=tuple(sorted((*result.elements, element), key=lambda e: (e.start, e.end))),
                       definitions=tuple(sorted(definitions.items())))

    def atomic_range(self, start, end):
        """Expand replacements to complete elements; reject insertion inside one."""
        if not 0 <= start <= end <= len(self.text):
            raise ValueError('Invalid native edit range.')
        if start == end:
            if any(e.start < start < e.end for e in self.elements):
                raise ValueError('Place the cursor outside the existing field or symbol.')
            return start, end
        for element in self.elements:
            if start < element.end and end > element.start:
                start, end = min(start, element.start), max(end, element.end)
        return start, end

    def adopt(self, start, end, source, source_start, source_end, *, at_destination=False,
              update_fields=True, exact_position=False):
        """Accept or reject a passage using the selected revision's associations."""
        if not 0 <= source_start <= source_end <= len(source.text):
            raise ValueError('Invalid source revision range.')
        if at_destination and start == end and not exact_position:
            # The advanced diff may place an insertion before a shared space
            # (" Extra") rather than after it ("Extra "). Move only equivalent
            # plain whitespace boundaries so the new words inherit the native
            # passage at their destination, not the preceding stroke clock.
            while (start < len(self.text) and source_start < source_end < len(source.text)
                   and self.text[start] in ' \t'
                   and source.text[source_start] == source.text[source_end] == self.text[start]
                   and not any(e.start <= start < e.end for e in self.elements)
                   and not any(e.start <= p < e.end for e in source.elements
                               for p in (source_start, source_end))):
                start += 1
                end += 1
                source_start += 1
                source_end += 1
        copied = None
        if not at_destination:
            copied, cursor = [], 0
            for span in source.spans:
                stop = cursor + len(span.content)
                if cursor < source_end and stop > source_start:
                    text = span.content[max(0, source_start - cursor):source_end - cursor]
                    copied.append(replace(span, identity=uuid.uuid4().hex, content=text))
                cursor = stop
        result = self._replace(start, end, source.text[source_start:source_end], copied)
        elements = [e for e in result.elements if e.end <= start or e.start >= start + source_end - source_start]
        elements.extend(replace(e, start=start + e.start - source_start, end=start + e.end - source_start)
                        for e in source.elements if source_start <= e.start and e.end <= source_end)
        elements = tuple(sorted(elements, key=lambda e: (e.start, e.end)))
        if elements != result.elements:
            result = replace(result, elements=elements)
        if not update_fields:
            return result
        definitions = {e.name: e.value if e.value is not None else source.text[e.start:e.end] for e in source.elements
                       if e.kind == 'field'
                       and source_start <= e.start and e.end <= source_end}
        for name, value in definitions.items():
            result = result.set_field(name, value)
        return result

    def _replace(self, start, end, content, adopted=None, preserve=None):
        """Apply an actual range. Empty source spans remain in their source order.

        Replacement text shares the affected passage's associations. This does
        not assign individual word times or assert a native marker placement.
        At a boundary, an insertion uses the following span; EOF uses the last.
        """
        if not isinstance(content, str) or not 0 <= start <= end <= len(self.text):
            raise ValueError('Invalid native edit range.')
        if start == end and not content:
            return self
        ends = self._span_ends
        first = bisect_right(ends, start)
        offset = ends[first-1] if first else 0
        stop = first if end == offset else bisect_left(ends, end) + 1
        affected = self.spans[first:stop]
        if not affected:
            following = self.spans[min(first, len(ends)-1)] if ends else AnchoredSpan('root', (), (), '')
            affected = (following,)
        inserted = AnchoredSpan(uuid.uuid4().hex,
                               _ordered(ref for span in affected for ref in span.stroke_refs),
                               _ordered(ref for span in affected for ref in span.audio),
                               content, affected[0].formatting)
        additions = [inserted] if adopted is None else adopted
        result, added = [], False
        for index in range(first, stop):
            span = self.spans[index]
            a, b = offset, ends[index]
            offset = b
            # Empty anchors are retained even when the whole passage is deleted.
            if not span.content:
                result.append(span)
                continue
            prefix = span.content[:max(0, start - a)]
            suffix = span.content[max(0, end - a):] if end < b else ''
            result.append(replace(span, content=prefix))
            if not added:
                if content:
                    result.extend(additions)
                added = True
            if suffix:
                result.append(replace(span, identity=uuid.uuid4().hex, content=suffix))
        if not added and content:
            result.extend(additions)
        elements = edited_elements(self.elements, self.text, start, end, content, preserve)
        text = self.text[:start] + content + self.text[end:]
        spans = self.spans[:first] + tuple(result) + self.spans[stop:]
        revision = replace(self, spans=spans, elements=paragraph_symbols(text, elements))
        # The exact projection is already available; avoid joining every native
        # span again when the editor reads the new revision after a keystroke.
        revision.__dict__['text'] = text
        return revision

    def revise(self, text, *, edits=None):
        """Apply VS Code inner changes while retaining native field associations."""
        if text == self.text:
            return self
        if edits is None:
            from app.src.suggestions import text_edits
            edits = text_edits(self.text, text)
        edits = tuple(edits)
        changes = [(a, b, text[c:d]) for a, b, c, d in edits]
        # A proposal can change a field's displayed name too. Gather all edits
        # to each definition before applying ranges, since a linked update can
        # change the length of multiple earlier occurrences.
        field_changes, ordinary = {}, []
        for start, end, content in changes:
            field = next((e for e in self.elements if e.kind == 'field'
                          and e.start <= start and end <= e.end
                          and (start < end or e.start < start < e.end)), None)
            if field and (content or (start, end) != (field.start, field.end)):
                field_changes.setdefault(field, []).append((start, end, content))
            else:
                ordinary.append((start, end, content, None))
        definitions = {}
        for field, replacements in field_changes.items():
            value = self.text[field.start:field.end]
            for start, end, content in reversed(replacements):
                value = value[:start-field.start] + content + value[end-field.start:]
            _validate_field_value(value)
            if field.name in definitions and definitions[field.name] != value:
                raise ValueError('The proposal assigns conflicting values to one speaker field.')
            definitions[field.name] = value
        for field in self.elements:
            if field.kind == 'field' and field.name in definitions:
                if not any(a < field.end and b > field.start for a, b, _, _ in ordinary):
                    ordinary.append((field.start, field.end, definitions[field.name], field))
        result = self
        # A new paragraph can be inserted at the start of a replaced turn
        # label. Apply the replacement before inserting at its left boundary.
        for start, end, content, field in reversed(sorted(ordinary, key=lambda change: change[:2])):
            if field:
                from .fields import rendered_value
                updated = replace(field, value=content)
                result = replace(result, elements=tuple(updated if e is field else e for e in result.elements))
                field = updated
                content = rendered_value(result.text[:start], content, field.name, all_caps=self.all_caps)
            result = result._replace(start, end, content, preserve=field)
        if definitions:
            values = dict(result.definitions)
            values.update(definitions)
            result = replace(result, definitions=tuple(sorted(values.items())))
        if result.text == text and any(e.name == 'By-line' or e.kind == 'field' for e in self.elements):
            from app.src.spoken_edits import byline_moves, restore_bylines
            moves = byline_moves(self, result, edits)
            if moves:
                result = restore_bylines(self, result, moves)
        return result

    def to_dict(self):
        # Span and element fields contain only immutable values. A detached
        # mapping is enough for project saves and background recovery.
        return {'spans': [vars(span).copy() for span in self.spans],
                'elements': [vars(element).copy() for element in self.elements], 'all_caps': self.all_caps,
                'definitions': list(self.definitions)}

    @classmethod
    def from_dict(cls, record):
        try:
            spans = []
            identities = set()
            for raw in record['spans']:
                span = AnchoredSpan(raw['identity'], tuple(raw['stroke_refs']), tuple(raw['audio']),
                                    raw['content'], tuple(raw['formatting']))
                if (not isinstance(span.identity, str) or span.identity in identities
                        or not isinstance(span.content, str)
                        or any(type(ref) is not int or ref < 0 for ref in span.stroke_refs)
                        or any(not isinstance(value, str) for value in (*span.audio, *span.formatting))):
                    raise ValueError('Invalid native span.')
                identities.add(span.identity)
                spans.append(span)
            elements = tuple(NativeElement(**value) for value in record.get('elements', []))
            length = sum(len(s.content) for s in spans)
            previous = 0
            for element in elements:
                if (type(element.start) is not int or type(element.end) is not int
                        or not previous <= element.start <= element.end <= length
                        or element.kind not in ('field', 'symbol') or not isinstance(element.name, str)
                        or not isinstance(element.raw, str)
                        or (element.value is not None and not isinstance(element.value, str))
                        or (element.source is not None and (type(element.source) is not int or element.source < 0))):
                    raise ValueError('Invalid native element.')
                bytes.fromhex(element.raw)
                previous = element.end
            all_caps = record.get('all_caps', False)
            if type(all_caps) is not bool:
                raise ValueError('Invalid native capitalization setting.')
            definitions = tuple(tuple(item) for item in record.get('definitions', []))
            if (any(len(item) != 2 or not all(isinstance(v, str) for v in item) for item in definitions)
                    or len({item[0] for item in definitions}) != len(definitions)):
                raise ValueError('Invalid native field definitions.')
            return cls(tuple(spans), elements, all_caps, definitions)
        except (KeyError, TypeError) as exc:
            raise ValueError('Invalid native revision.') from exc
