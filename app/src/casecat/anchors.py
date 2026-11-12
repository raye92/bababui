"""Immutable editorial associations, independent of Qt and the native writer."""
from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
import re
import uuid

from .elements import NativeElement, edited_elements, paragraph_symbols


@dataclass(frozen=True)
class AnchoredSpan:
    identity: str
    stroke_refs: tuple[int, ...]
    audio: tuple[str, ...]
    content: str
    formatting: tuple[str, ...] = ()


def _ordered(values):
    return tuple(dict.fromkeys(values))


def utf16_index(text, offset):
    """Convert a Qt offset, rejecting a position inside a surrogate pair."""
    if not isinstance(offset, int) or offset < 0:
        raise ValueError('Invalid UTF-16 offset.')
    units = 0
    for index, char in enumerate(text):
        if units == offset:
            return index
        units += 2 if ord(char) > 0xffff else 1
        if units > offset:
            raise ValueError('UTF-16 offset splits a character.')
    if units == offset:
        return len(text)
    raise ValueError('UTF-16 offset exceeds the document.')


@dataclass(frozen=True)
class Revision:
    spans: tuple[AnchoredSpan, ...]
    elements: tuple[NativeElement, ...] = ()
    all_caps: bool = False
    definitions: tuple[tuple[str, str], ...] = ()

    @property
    def text(self):
        return ''.join(span.content for span in self.spans)

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
                value = (self.text[element.start:start] + content + self.text[end:element.end])
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
        if not isinstance(value, str) or any(ord(c) < 32 for c in value):
            raise ValueError('A field value must be a single line.')
        try:
            value.encode('cp1252')
        except UnicodeEncodeError as exc:
            raise ValueError('Field values must use Windows-1252 characters.') from exc
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
                                     rendered_value(result.text[:element.start], value, name, all_caps=self.all_caps),
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
        if not isinstance(value, str) or any(ord(c) < 32 for c in value):
            raise ValueError('A field value must be a single line.')
        try:
            value.encode('cp1252')
        except UnicodeEncodeError as exc:
            raise ValueError('Field values must use Windows-1252 characters.') from exc
        existing = next((e for e in self.elements if e.kind == 'field' and e.name == name), None)
        if existing:
            raw = bytes.fromhex(existing.raw)
            value = existing.value if existing.value is not None else self.text[existing.start:existing.end]
        elif name in dict(self.definitions):
            value = dict(self.definitions)[name]
        display = rendered_value(self.text[:position], value, name, all_caps=self.all_caps)
        result = self._replace(position, position, display)
        element = NativeElement(position, position + len(display), 'field', raw.hex(), name,
                                existing.source if existing else None, value)
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

    def adopt(self, start, end, source, source_start, source_end):
        """Accept/deny a passage using the selected revision's associations."""
        if not 0 <= source_start <= source_end <= len(source.text):
            raise ValueError('Invalid source revision range.')
        copied, cursor = [], 0
        for span in source.spans:
            stop = cursor + len(span.content)
            if cursor < source_end and stop > source_start:
                text = span.content[max(0, source_start - cursor):source_end - cursor]
                copied.append(replace(span, identity=uuid.uuid4().hex, content=text))
            cursor = stop
        result = self._replace(start, end, ''.join(s.content for s in copied), copied)
        elements = [e for e in result.elements if e.end <= start or e.start >= start + source_end - source_start]
        elements.extend(replace(e, start=start + e.start - source_start, end=start + e.end - source_start)
                        for e in source.elements if source_start <= e.start and e.end <= source_end)
        result = replace(result, elements=tuple(sorted(elements, key=lambda e: (e.start, e.end))))
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
        positions, cursor = [], 0
        for span in self.spans:
            positions.append((cursor, cursor + len(span.content), span))
            cursor += len(span.content)
        affected = [span for a, b, span in positions if a < end and b > start]
        if not affected:
            following = next((span for a, b, span in positions if a <= start < b), None)
            affected = [following or (self.spans[-1] if self.spans else AnchoredSpan('root', (), (), ''))]
        inserted = AnchoredSpan(uuid.uuid4().hex,
                               _ordered(ref for span in affected for ref in span.stroke_refs),
                               _ordered(ref for span in affected for ref in span.audio),
                               content, affected[0].formatting)
        additions = [inserted] if adopted is None else adopted
        result, added = [], False
        for a, b, span in positions:
            # Empty anchors are retained even when the whole passage is deleted.
            if not span.content:
                result.append(span)
                continue
            if b <= start:
                result.append(span)
                continue
            if a >= end and added:
                result.append(span)
                continue
            prefix = span.content[:max(0, start - a)]
            suffix = span.content[max(0, end - a):] if end < b else ''
            if a >= end:  # insertion at the beginning of a following span
                if content:
                    result.extend(additions)
                added = True
                result.append(span)
                continue
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
        return replace(self, spans=tuple(result), elements=paragraph_symbols(text, elements))

    def revise(self, text):
        """Ordered paragraph/token alignment for proposals and whole-text edits.

        Newlines are explicit content. Repeated words are never treated as a
        global bag of tokens, and paragraph joins are not silently discarded.
        """
        if text == self.text:
            return self
        old_parts = self.text.splitlines(keepends=True)
        new_parts = text.splitlines(keepends=True)
        old_offsets = [0]
        for part in old_parts:
            old_offsets.append(old_offsets[-1] + len(part))
        changes = []
        for tag, a, b, c, d in SequenceMatcher(None, old_parts, new_parts, autojunk=False).get_opcodes():
            if tag == 'equal':
                continue
            old, new = ''.join(old_parts[a:b]), ''.join(new_parts[c:d])
            # Bound work for very large pastes. A passage replacement still
            # retains all associations, without guessing word correspondence.
            tokens_a = re.findall(r'\n|[^\S\n]+|\w+|[^\w\s]', old)
            tokens_b = re.findall(r'\n|[^\S\n]+|\w+|[^\w\s]', new)
            if len(tokens_a) * len(tokens_b) > 1_000_000:
                changes.append((old_offsets[a], old_offsets[b], new))
                continue
            offsets = [0]
            for token in tokens_a:
                offsets.append(offsets[-1] + len(token))
            for subtag, i, j, k, l in SequenceMatcher(None, tokens_a, tokens_b, autojunk=False).get_opcodes():
                if subtag != 'equal':
                    changes.append((old_offsets[a] + offsets[i], old_offsets[a] + offsets[j], ''.join(tokens_b[k:l])))
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
        for field, edits in field_changes.items():
            value = self.text[field.start:field.end]
            for start, end, content in reversed(edits):
                value = value[:start-field.start] + content + value[end-field.start:]
            if field.name in definitions and definitions[field.name] != value:
                raise ValueError('The proposal assigns conflicting values to one speaker field.')
            definitions[field.name] = value
        for field in self.elements:
            if field.kind == 'field' and field.name in definitions:
                if not any(a < field.end and b > field.start for a, b, _, _ in ordinary):
                    ordinary.append((field.start, field.end, definitions[field.name], field))
        result = self
        for start, end, content, field in sorted(ordinary, key=lambda change: change[0], reverse=True):
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
        return result

    def to_dict(self):
        return {'spans': [asdict(span) for span in self.spans],
                'elements': [asdict(element) for element in self.elements], 'all_caps': self.all_caps,
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
