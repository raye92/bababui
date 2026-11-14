"""Positioned native fields and generated paragraph labels.

Positions address logical text, never page numbers or Qt's display formatting.
"""
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import re


@dataclass(frozen=True)
class NativeElement:
    start: int
    end: int
    kind: str
    raw: str
    name: str = ''
    source: int | None = None
    value: str | None = None


def field_name(raw):
    if raw[:2] != b'\x15\x07':
        return None
    if len(raw) < 11 or raw[-1] != 0:
        raise ValueError('Invalid native field record.')
    return raw[10:-1].decode('cp1252')


def speaker_number(name):
    match = re.fullmatch(r'EZ SPEAKER (\d+)', name)
    return str(int(match[1])) if match else None


def edited_elements(elements, text, start, end, content, preserve=None):
    """Retain exact matched elements through a range edit; never split one."""
    delta = len(content) - (end - start)
    matches = None
    result, unmatched = [], []
    for element in elements:
        if element is preserve:
            result.append(replace(element, start=start, end=start + len(content)))
        elif element.end <= start:
            result.append(element)
        elif element.start >= end:
            result.append(replace(element, start=element.start + delta, end=element.end + delta))
        elif start <= element.start and element.end <= end:
            if matches is None:
                matches = SequenceMatcher(None, text[start:end], content, autojunk=False).get_matching_blocks()
            for a, b, size in matches:
                if a <= element.start - start and element.end - start <= a + size:
                    position = start + b + element.start - start - a
                    result.append(replace(element, start=position, end=position + element.end - element.start))
                    break
            else:
                unmatched.append(element)
    # A whole-passage move can leave an intact field outside the ordered
    # matching blocks. Retain it only when its remaining destination is unique.
    for element in unmatched:
        needle = text[element.start:element.end]
        if not needle:
            continue
        candidates, offset = [], 0
        while (offset := content.find(needle, offset)) >= 0:
            position = start + offset
            if not any(e.start < position + len(needle) and e.end > position for e in result):
                candidates.append(position)
            offset += len(needle)
        if len(candidates) == 1:
            position = candidates[0]
            result.append(replace(element, start=position, end=position+len(needle)))
    return tuple(sorted(result, key=lambda element: (element.start, element.end)))


def paragraph_symbols(text, elements):
    result = [e for e in elements if e.kind != 'symbol' or e.start == 0 or text[e.start - 1] == '\n']
    for match in re.finditer(r'(?m)^     [QA]    ', text):
        if not any(e.start < match.end() and e.end > match.start() for e in elements):
            result.append(NativeElement(match.start(), match.end(), 'symbol',
                                        '160200' if match[0][5] == 'Q' else '160300'))
    return tuple(sorted(result, key=lambda element: (element.start, element.end)))


def validate_elements(revision, baseline):
    sources = {e.source: e for e in baseline.elements}
    text, previous = revision.text, 0
    for element in revision.elements:
        if not previous <= element.start <= element.end <= len(text):
            raise ValueError('Invalid native element range.')
        previous = element.end
        source = sources.get(element.source)
        if element.kind == 'field':
            from .field_table import field_record
            if element.source is None:
                valid = element.raw == field_record(element.name).hex()
            else:
                valid = source is not None and (element.kind, element.raw, element.name) == (source.kind, source.raw, source.name)
            if not valid:
                raise ValueError('Unrecognized native field reference.')
        elif element.kind == 'symbol':
            label = {'160200': '     Q    ', '160300': '     A    '}.get(element.raw)
            if element.name == 'By-line':
                allowed = ('160500425920', '160500110602000000425920')
                if element.raw in allowed or (source and element.raw == source.raw):
                    label = 'BY '
            if label is None or text[element.start:element.end] != label:
                raise ValueError('Invalid native symbol element.')
        else:
            raise ValueError('Unsupported native element kind.')
