"""EZ Speaker definitions, stored separately from transcript field references."""
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from .elements import speaker_number


def field_values(revision):
    values = dict(revision.definitions)
    for element in revision.elements:
        if element.kind != 'field':
            continue
        value = element.value if element.value is not None else revision.text[element.start:element.end]
        if element.name in values and values[element.name] != value:
            raise ValueError('Linked speaker fields have conflicting values.')
        values[element.name] = value
    return values


def speaker_values(revision):
    return {speaker_number(name): value for name, value in field_values(revision).items()
            if speaker_number(name) is not None}


def rendered_value(prefix, value, name='', *, all_caps=False):
    from .rendering import TextRenderer
    renderer = TextRenderer(all_caps=all_caps)
    for index, paragraph in enumerate(prefix.split('\n')):
        if index:
            renderer.paragraph(255)
        if paragraph.startswith(('     Q    ', '     A    ')):
            paragraph = paragraph[10:]
        renderer.literal(paragraph)
    return renderer.literal(value or f'[!{name}]')


def serialize_metadata(job, bundle):
    member = bundle.member(job.key + '.sgxml')
    original = bundle.read(member) if member else None
    values = speaker_values(job.revision)
    baseline = speaker_values(job.baseline)
    changes = {key: value for key, value in values.items() if value != baseline.get(key)}
    if not changes or original is None:
        return original
    # CATalyst writes UTF-8 XML. Patch only values, retaining comments, spacing,
    # unrelated preferences, and every other attribute byte for byte.
    declaration = re.search(br'<\?xml[^>]*encoding=[\"\']([^\"\']+)', original)
    encoding = declaration[1].decode('ascii') if declaration else 'utf-8'
    text = original.decode(encoding)
    for number, value in changes.items():
        value.encode('cp1252')
        if any(ord(char) < 32 for char in value):
            raise ValueError('A speaker value must be a single line.')
        pattern = rf'(<Speaker-{number}\b[^>]*\bsgpref-val=)([\"\'])(.*?)(\2)'
        escaped = escape(value, {'"': '&quot;', "'": '&apos;'})
        text, count = re.subn(pattern, lambda m: m[1] + m[2] + escaped + m[4], text)
        if count == 0 and not re.search(rf'<Speaker-{number}\b', text):
            node = f'<Speaker-{number} sgpref-val="{escaped}" Steno=""/>'
            if '</Speaker>' in text:
                text = text.replace('</Speaker>', node + '</Speaker>', 1)
            elif re.search(r'<Speaker\s*/>', text):
                text = re.sub(r'<Speaker\s*/>', lambda _: '<Speaker>' + node + '</Speaker>', text, count=1)
            else:
                root = ET.fromstring(text)
                closing = f'</{root.tag}>'
                addition = '<Speaker>' + node + '</Speaker>'
                if closing in text:
                    text = text.replace(closing, addition + closing, 1)
                else:
                    position = text.rfind('/>')
                    text = text[:position] + '>' + addition + closing + text[position+2:]
        elif count != 1:
            raise ValueError('The native speaker definition is missing or ambiguous.')
    result = text.encode(encoding)
    ET.fromstring(result)
    return result
