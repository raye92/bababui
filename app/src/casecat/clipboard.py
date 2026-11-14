"""Native elements on the app clipboard, with plain text for other applications."""
from dataclasses import asdict, replace
import json

from .anchors import AnchoredSpan, Revision
from .elements import validate_elements
from .field_table import field_record


MIME_TYPE = 'application/x-bababui-casecat-elements'


def selection_data(revision, start, end):
    elements = []
    for element in revision.elements:
        if start <= element.start and element.end <= end:
            raw = field_record(element.name).hex() if element.kind == 'field' else element.raw
            elements.append(asdict(replace(element, start=element.start-start,
                                          end=element.end-start, source=None, raw=raw)))
    return json.dumps({'text': revision.text[start:end], 'elements': elements}).encode('utf-8')


def paste_revision(revision, baseline, start, end, data):
    from .fields import field_values
    destination_values = field_values(revision)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('Native clipboard data is too large.')
    record = json.loads(data)
    text = record['text']
    copied = Revision.from_dict({'spans': [asdict(AnchoredSpan('clipboard', (), (), text))],
                                 'elements': record['elements']})
    validate_elements(copied, Revision(()))
    start, end = revision.atomic_range(start, end)
    prefix = '\n' if (start and revision.text[start-1] != '\n' and copied.elements
                      and copied.elements[0].kind == 'symbol' and copied.elements[0].start == 0) else ''
    inserted = prefix + text
    result = revision._replace(start, end, inserted)
    elements, values = [], {}
    for element in copied.elements:
        element = replace(element, start=start+len(prefix)+element.start,
                          end=start+len(prefix)+element.end)
        if element.kind == 'field':
            existing = next((e for e in revision.elements if e.kind == 'field' and e.name == element.name), None)
            original = existing or next((e for e in baseline.elements if e.kind == 'field' and e.name == element.name), None)
            value = destination_values.get(element.name, element.value)
            if value is None:
                value = result.text[element.start:element.end]
            if element.name in values and values[element.name] != value:
                raise ValueError('Clipboard fields contain conflicting definitions.')
            values[element.name] = value
            if original:
                element = replace(element, raw=original.raw, source=original.source)
            element = replace(element, value=value)
        elements.append(element)
    kept = [e for e in result.elements if not any(e.start < n.end and e.end > n.start for n in elements)]
    result = replace(result, elements=tuple(sorted((*kept, *elements), key=lambda e: (e.start, e.end))))
    for name, value in values.items():
        result = result.set_field(name, value)
    return result
