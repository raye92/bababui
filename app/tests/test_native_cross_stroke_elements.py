"""Native symbols and linked fields can span multiple edited stroke groups."""
from hashlib import sha256
from io import BytesIO
import struct
import wave
import xml.etree.ElementTree as ET

import pytest

from app.src import documents
from app.src.casecat import codec
from app.src.casecat.codec import load_job, records, u32
from app.src.casecat.clipboard import paste_revision, selection_data
from app.src.casecat.timing import AudioMap
from app.src.review_editing import resolve_review
from app.src.review_model import build_review
from app.src.speech_alignment import SpeechAlignment
from app.tests.test_native_audio import audio_archive
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_fields import FIELD, field_files
from app.tests.test_native_structure import container_files


def _roundtrip(tmp_path, files, edit):
    audio = BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(bytes(32000))
    files['jobs/example.wav'] = audio.getvalue()
    source = tmp_path / 'source.zip'
    source.write_bytes(zip_bytes(files))
    before = documents.import_casecat(source)
    original = before.native.job
    edited = edit(original.revision)
    before.set_text('original', edited.text, revision=edited)
    target = tmp_path / 'reviewed.zip'
    before.export_casecat(target, corrected_audio=False)
    exported = documents.import_casecat(target)
    restored = exported.native.job

    assert restored.text == edited.text
    assert restored.notes_bytes == original.notes_bytes
    assert restored.stroke_clocks == original.stroke_clocks
    def anchors(job):
        return [(s.stroke_refs, s.audio) for s in job.baseline.spans if s.stroke_refs or s.audio]
    assert anchors(restored) == anchors(original)
    assert exported.native.bundle.read(restored.audio_member) == audio.getvalue()
    return restored


@pytest.mark.parametrize(('label', 'raw'), [('Q', '160200'), ('A', '160300')])
def test_export_keeps_a_qa_symbol_split_across_strokes(tmp_path, label, raw):
    audio_marker = b'\x15\x08\x08\0\0\0' + struct.pack('<II', 1000, 640)
    files = container_files(('Opening.\n  ', '   X', audio_marker.decode('cp1252') + '    Next.', ' Done.'))

    def edit(revision):
        start = revision.text.index('X')
        return revision.replace(start, start + 1, label)

    restored = _roundtrip(tmp_path, files, edit)

    assert [(e.kind, e.raw, restored.text[e.start:e.end]) for e in restored.revision.elements] == [
        ('symbol', raw, f'     {label}    ')]
    assert [span.content for span in restored.baseline.spans] == [
        'Opening.', '', f'\n     {label}    Next.', ' Done.']


def _accept_linked_field_replacement(revision):
    reference, = revision.elements
    start = revision.text.index('MS. OLD', reference.end)
    clipboard = selection_data(revision, reference.start, reference.end)
    proposal = paste_revision(revision, revision, start, start + len('MS. OLD'), clipboard)
    start = proposal.text.index('separate')
    proposal = proposal.replace(start, start + len('separate'), 'different')
    model, _ = resolve_review(build_review(revision, proposal), None, None, True)
    return model.original


def test_accept_all_export_keeps_a_linked_field_split_across_strokes(tmp_path):
    files = field_files(words=(b'Opening ' + FIELD + b'.', b'\x16\x08\x00MS. ',
                               b'OLD approved it.', b'\x16\x08\x00A separate sentence.'))

    restored = _roundtrip(tmp_path, files, _accept_linked_field_replacement)

    assert [(e.start, e.end, e.name, e.value) for e in restored.revision.elements] == [
        (8, 15, 'EZ SPEAKER 01', 'MS. OLD'), (17, 24, 'EZ SPEAKER 01', 'MS. OLD')]
    assert [span.content for span in restored.baseline.spans] == [
        'Opening MS. OLD.', '\n', 'MS. OLD approved it.', '\nA different sentence.']


@pytest.mark.parametrize(('label', 'blank_lines'), [('Q', 1), ('A', 2)])
def test_accepted_fields_and_manual_edits_share_one_native_export(tmp_path, label, blank_lines):
    paragraph = b'\x16\xff\x00'
    files = field_files(words=(
        b'Omit.', paragraph + b'Keep.', paragraph + b'  ', b'   X', b'    Next.',
        paragraph + b'Opening ' + FIELD + b'.', paragraph + b'MS. ', b'OLD approved.',
        paragraph + b'A separate sentence.', paragraph + b'Left. Right.'))

    def edit(revision):
        revision = _accept_linked_field_replacement(revision)
        index = revision.text.index('X')
        revision = revision.replace(index, index + 1, label)
        revision = revision.replace(0, len('Omit.'), '\n' * (blank_lines - 1))
        index = revision.text.index(' Right.')
        return revision.replace(index, index + 1, '\t')

    restored = _roundtrip(tmp_path, files, edit)

    assert restored.text == ('\n' * blank_lines + f'Keep.\n     {label}    Next.\nOpening MS. OLD.'
                             '\nMS. OLD approved.\nA different sentence.\nLeft.\tRight.')
    assert [(e.kind, e.raw) for e in restored.revision.elements] == [
        ('symbol', '160200' if label == 'Q' else '160300'), ('field', FIELD.hex()), ('field', FIELD.hex())]
    start = u32(restored.native_bytes, 532)
    assert restored.native_bytes[start:start + 3] == paragraph


@pytest.mark.parametrize('kind', ['field', 'question'])
def test_export_checks_native_elements_even_when_the_words_match(tmp_path, monkeypatch, kind):
    if kind == 'field':
        files = field_files(words=(b'Opening ' + FIELD + b'.', b'\x16\x08\x00MS. OLD replied.'))
    else:
        files = container_files(('Opening.\n     X    ', 'Next.'))
    source = tmp_path / 'source.zip'
    source.write_bytes(zip_bytes(files))
    doc = documents.import_casecat(source)
    original = doc.native.original
    literal_copy = doc.native.job.native_bytes
    if kind == 'field':
        field, = original.elements
        start = original.text.index('MS. OLD', field.end)
        edited = paste_revision(original, original, start, start + len('MS. OLD'),
                                selection_data(original, field.start, field.end))
    else:
        start = original.text.index('X')
        edited = original.replace(start, start + 1, 'Q')
        literal_copy = literal_copy.replace(b'     X    ', b'     Q    ', 1)
    doc.set_text('original', edited.text, revision=edited)
    monkeypatch.setattr(codec, 'serialize_native', lambda *_: literal_copy)
    target = tmp_path / 'reviewed.zip'
    target.write_bytes(b'previous export')

    with pytest.raises(ValueError, match='native field or paragraph symbol'):
        doc.export_casecat(target, overwrite=True, corrected_audio=False)

    assert target.read_bytes() == b'previous export'


def test_corrected_timing_uses_the_stroke_where_the_linked_field_is_exported(tmp_path):
    recording = audio_archive(tmp_path)
    audio_job = load_job(recording, 'jobs/example')
    audio_marker = bytes.fromhex(audio_job.baseline.spans[0].audio[0])
    files = field_files(words=(audio_marker + b'Opening ' + FIELD + b'.', b'\x16\x08\x00MS. ',
                               b'OLD approved it. A separate sentence.'))
    native = bytearray(files['jobs/example.sgngl'])
    notes = bytearray(files['jobs/example.sgstn'])
    stream_start, stream_size = struct.unpack_from('<II', native, 532)
    strokes = (offset for offset, raw in records(bytes(native), stream_start, stream_start + stream_size)
               if raw[0] == 0x13)
    for index, (offset, clock) in enumerate(zip(strokes, audio_job.stroke_clocks)):
        struct.pack_into('<I', native, offset + 7, clock)
        struct.pack_into('<I', notes, 644 + index * 8, clock)
    audio_section = audio_job.native_bytes[u32(audio_job.native_bytes, 556):]
    native[u32(native, 556):] = audio_section
    struct.pack_into('<I', native, 560, len(audio_section))
    struct.pack_into('<I', native, 652, u32(audio_job.native_bytes, 652))
    metadata = ET.fromstring(files['jobs/example.sgxml'])
    metadata.append(ET.fromstring(recording.read('jobs/example.sgxml')).find('Read-Settings'))
    wav = recording.read(audio_job.audio_member)
    files.update({'jobs/example.sgngl': bytes(native), 'jobs/example.sgstn': bytes(notes),
                  'jobs/example.sgxml': ET.tostring(metadata), 'jobs/example.wav': wav})
    source = tmp_path / 'source.zip'
    source.write_bytes(zip_bytes(files))
    doc = documents.import_casecat(source)
    doc.native.original = _accept_linked_field_replacement(doc.native.original)
    doc.native.alignment = SpeechAlignment(sha256(wav).hexdigest(), 40000, (4000, 10000, 18000), (
        ('opening', 4000), ('ms', 5000), ('old', 6000), ('ms', 12000), ('old', 13000),
        ('approved', 14000), ('it', 15000), ('a', 16000), ('different', 17000), ('sentence', 18000)))

    target = tmp_path / 'reviewed.zip'
    doc.export_casecat(target)
    restored = documents.import_casecat(target)
    bundle, job = restored.native.bundle, restored.native.job

    assert job.text == 'Opening MS. OLD.\nMS. OLD approved it. A different sentence.'
    assert [e.name for e in job.revision.elements] == ['EZ SPEAKER 01', 'EZ SPEAKER 01']
    assert [key for key, _ in struct.iter_unpack('<II', job.notes_bytes[640:])] == [1, 2, 4]
    assert bundle.read(job.audio_member) == wav
    assert AudioMap.from_job(bundle, job, restored.wav_path).stroke_ms == (4000, 7420, 12000)
