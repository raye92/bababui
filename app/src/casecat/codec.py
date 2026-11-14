"""Native transcript reader with immutable steno, audio and source assets."""
from dataclasses import dataclass, replace
import struct
import xml.etree.ElementTree as ET

from .anchors import AnchoredSpan, Revision
from .rendering import TextRenderer
from .elements import NativeElement, field_name


RENDERING_NOTICE = ('CaseCAT native editing. New wording inherits source passage timing; '
                    'unsupported native structures are rejected during export.')


def u32(data, offset):
    if offset < 0 or offset + 4 > len(data):
        raise ValueError('Truncated native field.')
    return struct.unpack_from('<I', data, offset)[0]


def records(data, start, end):
    """Widths observed in CaseCAT 22.1.5.46514 at 0x00cf0e00.

    Length-delimited bodies are always opaque. This is structural knowledge,
    not an assertion about every opcode's rendering or synchronization meaning.
    """
    if not 0 <= start <= end <= len(data):
        raise ValueError('Invalid native stream bounds.')
    offset = start
    fixed = {0x10: 2, 0x11: 6, 0x12: 2, 0x16: 3, 0x17: 2, 0x1a: 4}
    while offset < end:
        opcode = data[offset]
        size = {0x13: 3, 0x15: 6, 0x18: 8}.get(opcode, fixed.get(opcode, 1))
        if offset + size > end:
            raise ValueError('Truncated native record header.')
        if opcode == 0x13:
            size += data[offset + 2] * 8
        elif opcode == 0x15:
            size += u32(data, offset + 2)
        elif opcode == 0x18:
            length = struct.unpack_from('<H', data, offset + 4)[0]
            if length > 0x7fff:
                raise ValueError('Unsupported signed native record length.')
            size += length
        if offset + size > end:
            raise ValueError('Truncated native record body.')
        yield offset, data[offset:offset + size]
        offset += size


@dataclass(frozen=True)
class NativeJob:
    key: str
    source_digest: str
    native_bytes: bytes
    notes_bytes: bytes
    audio_member: str | None
    baseline: Revision
    revision: Revision
    warnings: tuple[str, ...]
    # One effective playback clock per embedded stroke occurrence. Reused
    # records keep their source bytes but inherit the preceding passage clock.
    stroke_clocks: tuple[int, ...]

    @property
    def text(self):
        return self.revision.text

    def with_revision(self, revision):
        return replace(self, revision=revision)


def load_job(bundle, key):
    if key not in bundle.jobs:
        raise ValueError('The selected job is not present in this archive.')
    native = bundle.read(bundle.member(key + '.sgngl'))
    notes_member = bundle.member(key + '.sgstn')
    if notes_member is None:
        raise ValueError('The original steno (.sgstn) file is missing.')
    notes = bundle.read(notes_member)
    if len(native) < 1024 or len(notes) < 640 or native[:8] != b'SGCAT32\0' or notes[:8] != b'SGCAT32\0':
        raise ValueError('Unsupported native headers.')
    count = u32(notes, 516)
    if len(notes) != 640 + count * 8:
        raise ValueError('Unsupported original steno record layout.')
    start, length = u32(native, 532), u32(native, 536)
    if start < 1024 or start + length > len(native):
        raise ValueError('Invalid native stream bounds.')
    from .layout import read_layouts
    read_layouts(native)
    speakers = {}
    all_caps = False
    metadata = bundle.member(key + '.sgxml')
    if metadata:
        try:
            root = ET.fromstring(bundle.read(metadata))
            speakers = {node.tag.removeprefix('Speaker-'): node.get('sgpref-val', '')
                        for node in root.iter() if node.tag.startswith('Speaker-')}
            all_caps = any(node.tag == 'Capitalize-All-Text' and node.get('sgpref-val') == '1'
                           for node in root.iter())
        except ET.ParseError as exc:
            raise ValueError('Invalid job metadata XML.') from exc
    spans, refs, content, audio, formatting = [], (), [], [], []
    elements, position, content_length, byline = [], 0, 0, None
    stroke = 0
    original_strokes = {notes[i:i + 8] for i in range(640, len(notes), 8)}
    stroke_clocks = []
    renderer = TextRenderer(all_caps=all_caps)
    from .field_table import field_texts
    has_fields = any(raw[:2] == b'\x15\x07' for _, raw in records(native, start, start + length))
    try:
        definitions = field_texts(native)
    except ValueError:
        if has_fields:
            raise
        definitions = {}  # Retain an unknown section when no field uses it.

    def flush():
        if refs or content or audio or formatting:
            spans.append(AnchoredSpan(f'source-{len(spans)}', refs, tuple(audio), ''.join(content), tuple(formatting)))

    for offset, raw in records(native, start, start + length):
        before, part_count = content_length, len(content)
        op = raw[0]
        if op == 0x13:
            byline = None
            flush()
            position += before
            before, part_count = 0, 0
            kind, size = raw[1:3]
            if kind not in (1, 2) or not size:
                raise ValueError(f'Native steno association mismatch at byte {offset}.')
            # References identify occurrences in the transcript, not offsets
            # into .sgstn. Otherwise editing one copy could target another copy.
            refs = tuple(range(len(stroke_clocks), len(stroke_clocks) + size))
            for index in range(size):
                record = raw[3 + index * 8:11 + index * 8]
                if record == notes[640 + stroke * 8:648 + stroke * 8]:
                    stroke += 1
                    stroke_clocks.append(u32(record, 4))
                elif record in original_strokes:
                    # An extra occurrence may precede its original. Ordered
                    # coverage is still required at EOF. Leading copies use
                    # the first original clock because no passage precedes them.
                    stroke_clocks.append(stroke_clocks[-1] if stroke_clocks else u32(notes, 644))
                else:
                    raise ValueError(f'Native steno association mismatch at byte {offset}.')
            content, audio, formatting = [], [], []
        elif op >= 32:
            try:
                content.append(renderer.literal(raw.decode('cp1252')))
            except UnicodeDecodeError as exc:
                raise ValueError(f'Unresolved native character encoding at byte {offset}.') from exc
        elif op == 1:
            content.append(renderer.literal(' '))
            formatting.append(raw.hex())
        elif op == 2:
            content.append(renderer.conflict())
            formatting.append(raw.hex())
        elif op == 0x16:
            style = int.from_bytes(raw[1:], 'little')
            content.append(renderer.paragraph(style))
            formatting.append(raw.hex())
        elif op == 0x15 and raw[1] == 8:
            audio.append(raw.hex())
        elif op == 0x15 and raw[1] == 7:
            label = raw[10:].rstrip(b'\0').decode('cp1252')
            if label in definitions:
                value = definitions[label]
                content.append(renderer.literal(value or f'[!{label}]'))
            elif label.startswith('EZ SPEAKER '):
                number = str(int(label.removeprefix('EZ SPEAKER ')))
                value = speakers.get(number, f'[{label}]')
                content.append(renderer.literal(value or f'[!{label}]'))
            else:
                value = f'[{label}]'
                content.append(renderer.literal(value))
            formatting.append(raw.hex())
        else:
            # Preserve all formatting/control bytes, including translation
            # history. They are never dumped into editable transcript content.
            formatting.append(raw.hex())
            renderer.control(raw)
        after = before + (len(content[-1]) if len(content) > part_count else 0)
        content_length = after
        if op == 0x15 and raw[1] == 7:
            elements.append(NativeElement(position + before, position + after, 'field',
                                          raw.hex(), field_name(raw), offset, value))
        elif op == 0x16 and int.from_bytes(raw[1:], 'little') in (2, 3):
            prefix = content[-1]
            elements.append(NativeElement(position + before + int(prefix.startswith('\n')),
                                          position + after, 'symbol', raw.hex(), source=offset))
        if raw == b'\x16\x05\x00':
            byline = (offset, position + after)
        elif byline:
            byte, label_start = byline
            width = position + after - label_start
            if width == 3 and ''.join(content).endswith('BY '):
                elements.append(NativeElement(label_start, label_start+3, 'symbol',
                                              native[byte:offset+len(raw)].hex(), 'By-line', byte))
                byline = None
            elif width > 3:
                byline = None
    flush()
    if stroke != count:
        raise ValueError('The native transcript does not cover the original steno sequence.')
    revision = Revision(tuple(spans), tuple(elements), all_caps, tuple(sorted(definitions.items())))
    audio_member = bundle.member(key + '.wav')
    warnings = [RENDERING_NOTICE]
    if audio_member is None:
        warnings.append('This job has no WAV. Transcript editing is available; audio processing is disabled.')
    return NativeJob(key, bundle.digest, native, notes, audio_member, revision, revision,
                     tuple(warnings), tuple(stroke_clocks))


def validate_job(bundle, job):
    from .elements import validate_elements
    validate_elements(job.revision, job.baseline)
    if job.revision.all_caps != job.baseline.all_caps:
        raise ValueError('Original native capitalization settings were modified.')
    if job.source_digest != bundle.digest or job.key not in bundle.jobs:
        raise ValueError('Native job does not belong to the source archive.')
    if job.native_bytes != bundle.read(bundle.member(job.key + '.sgngl')) or job.notes_bytes != bundle.read(bundle.member(job.key + '.sgstn')):
        raise ValueError('Original native source bytes were modified.')
    count = len(job.stroke_clocks)
    if any(not 0 <= ref < count for span in job.revision.spans for ref in span.stroke_refs):
        raise ValueError('Invalid source steno reference.')
    sources = {span.identity: span for span in job.baseline.spans}
    retained = [span for span in job.revision.spans if span.identity in sources]
    if [span.identity for span in retained] != list(sources):
        raise ValueError('A source anchor was discarded or reordered.')
    for span in retained:
        source = sources[span.identity]
        if (span.stroke_refs, span.audio, span.formatting) != (source.stroke_refs, source.audio, source.formatting):
            raise ValueError('Original source associations or formatting were modified.')
    audio = {value for span in job.baseline.spans for value in span.audio}
    formatting = {value for span in job.baseline.spans for value in span.formatting}
    for span in job.revision.spans:
        if (tuple(sorted(set(span.stroke_refs))) != span.stroke_refs
                or any(value not in audio for value in span.audio)
                or any(value not in formatting for value in span.formatting)):
            raise ValueError('A revision contains unrecognized native associations.')


def serialize_native(job, bundle=None):
    if job.revision == job.baseline:
        return job.native_bytes
    if bundle is None:
        raise ValueError('The original archive is required for edited native serialization.')
    from .structure import serialize_candidate
    return serialize_candidate(job, bundle)


def serialize_candidate(job, bundle):
    """Compatibility entry point for local research scripts."""
    from .structure import serialize_candidate as candidate
    return candidate(job, bundle)
