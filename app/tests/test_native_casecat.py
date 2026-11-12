"""Synthetic native fixtures contain no private transcript or recording."""
import io
import struct
import zipfile

import pytest

from app.src.casecat import archive, anchors, codec


def job_files(words=('Hello ', 'world.\n'), *, audio=True):
    strokes = [struct.pack('<II', 1 << i, 1000 + i * 10) for i in range(len(words))]
    stream = b''.join(b'\x13\x01\x01' + stroke + word.encode('cp1252').replace(b'\n', b'\x16\x08\x00')
                      for stroke, word in zip(strokes, words))
    native = bytearray(1024)
    native[:8] = b'SGCAT32\0'
    struct.pack_into('<II', native, 532, 1024, len(stream))
    notes = bytearray(640)
    notes[:8] = b'SGCAT32\0'
    struct.pack_into('<I', notes, 516, len(strokes))
    files = {'jobs/example.sgngl': bytes(native) + stream,
             'jobs/example.sgstn': bytes(notes) + b''.join(strokes),
             'jobs/example.sgxml': b'<JobHistory/>', 'unrelated.bin': b'opaque\x00data'}
    if audio:
        files['jobs/example.wav'] = b'RIFF synthetic audio bytes'
    return files


def zip_bytes(files=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.comment = b'Keep the comment'
        for name, data in (files if files is not None else job_files()).items():
            info = zipfile.ZipInfo()
            info.filename = name  # Keep adversarial backslashes on Windows.
            z.writestr(info, data)
    return out.getvalue()


def test_lossless_archive_export_and_protect_source(tmp_path):
    data = zip_bytes()
    source = tmp_path/'example_AI.zip'
    source.write_bytes(data)
    bundle = archive.inspect_archive(source)
    assert bundle.jobs == ('jobs/example',)
    assert bundle.export_name == 'example_AI.zip'
    revision = codec.load_job(bundle, bundle.jobs[0])
    assert revision.text == 'Hello world.\n'
    target = tmp_path/'copy.zip'
    archive.export_zip(bundle, revision, target)
    assert target.read_bytes() == data
    with pytest.raises(ValueError, match='source'):
        archive.export_zip(bundle, revision, source, overwrite=True)
    target.write_bytes(b'keep')
    with pytest.raises(ValueError, match='exists'):
        archive.export_zip(bundle, revision, target)
    assert target.read_bytes() == b'keep'


@pytest.mark.parametrize('name', ['../escape.wav', '/escape.wav', 'C:/escape.wav',
                                  'jobs/../escape.wav', 'jobs\\escape.wav', 'jobs/a:stream',
                                  'jobs/CON.txt', 'jobs/name.'])
def test_unsafe_archive_members_rejected(name):
    with pytest.raises(ValueError, match='Unsafe'):
        archive.inspect_archive(zip_bytes({**job_files(), name: b'bad'}))


def test_ambiguous_members_and_missing_notes_rejected():
    with pytest.raises(ValueError, match='Duplicate'):
        archive.inspect_archive(zip_bytes({**job_files(), 'JOBS/EXAMPLE.WAV': b'other'}))
    files = job_files()
    del files['jobs/example.sgstn']
    bundle = archive.inspect_archive(zip_bytes(files))
    with pytest.raises(ValueError, match='steno'):
        codec.load_job(bundle, bundle.jobs[0])


def test_multiple_jobs_and_missing_audio(tmp_path):
    files = job_files(audio=False)
    files.update({name.replace('example', 'second'): value for name, value in job_files().items()})
    bundle = archive.inspect_archive(zip_bytes(files))
    assert bundle.jobs == ('jobs/example', 'jobs/second')
    first = codec.load_job(bundle, 'jobs/example')
    assert first.audio_member is None
    second = codec.load_job(bundle, 'jobs/second')
    path = archive.materialize_audio(bundle, second, tmp_path)
    assert path.read_bytes() == files['jobs/second.wav']
    assert path.is_relative_to(tmp_path)


def test_cross_anchor_edit_retains_deleted_anchors_and_passage_associations():
    original = anchors.Revision((
        anchors.AnchoredSpan('a', (0,), ('marker-a',), 'one '),
        anchors.AnchoredSpan('b', (1, 2), ('marker-b',), 'two '),
        anchors.AnchoredSpan('c', (3,), ('marker-c',), 'three'),
    ))
    edited = original.replace(2, 9, 'replacement')
    assert edited.text == 'onreplacementhree'
    assert {'a', 'b', 'c'} <= {span.identity for span in edited.spans}
    inserted = next(span for span in edited.spans if span.content == 'replacement')
    assert inserted.stroke_refs == (0, 1, 2, 3)
    assert inserted.audio == ('marker-a', 'marker-b', 'marker-c')
    assert next(span for span in edited.spans if span.identity == 'b').content == ''
    emptied = edited.replace(0, len(edited.text), '')
    assert emptied.text == ''
    assert {'a', 'b', 'c'} <= {span.identity for span in emptied.spans}
    assert original.text == 'one two three'


def test_insertion_timing_and_utf16_offsets():
    original = anchors.Revision((anchors.AnchoredSpan('a', (0,), ('a',), 'A😀'),
                                 anchors.AnchoredSpan('b', (1,), ('b',), 'B')))
    edited = original.replace_utf16(3, 0, 'é\n')
    assert edited.text == 'A😀é\nB'
    inserted = next(span for span in edited.spans if span.content == 'é\n')
    assert inserted.stroke_refs == (1,)
    with pytest.raises(ValueError, match='UTF-16'):
        original.replace_utf16(2, 0, 'bad')


def test_ordered_revision_keeps_repeated_paragraph_identity():
    original = anchors.Revision((anchors.AnchoredSpan('a', (0,), (), 'Yes.\n'),
                                 anchors.AnchoredSpan('b', (1,), (), 'Middle.\n'),
                                 anchors.AnchoredSpan('c', (2,), (), 'Yes.\n')))
    revised = original.revise('Yes.\nNew middle.\nYes.\n')
    assert revised.text == 'Yes.\nNew middle.\nYes.\n'
    assert next(s for s in revised.spans if s.identity == 'a').content == 'Yes.\n'
    assert next(s for s in revised.spans if s.identity == 'c').content == 'Yes.\n'
    assert anchors.Revision.from_dict(revised.to_dict()) == revised


def test_edited_export_refuses_missing_native_sections_without_touching_destination(tmp_path):
    bundle = archive.inspect_archive(zip_bytes())
    job = codec.load_job(bundle, bundle.jobs[0])
    edited = job.with_revision(job.revision.replace(0, 5, 'Different'))
    target = tmp_path/'export.zip'
    target.write_bytes(b'existing')
    with pytest.raises(ValueError, match='section layout'):
        archive.export_zip(bundle, edited, target, overwrite=True)
    assert target.read_bytes() == b'existing'


def test_embedded_steno_must_match_original():
    files = job_files()
    data = bytearray(files['jobs/example.sgstn'])
    data[-1] ^= 1
    files['jobs/example.sgstn'] = bytes(data)
    bundle = archive.inspect_archive(zip_bytes(files))
    with pytest.raises(ValueError, match='steno'):
        codec.load_job(bundle, bundle.jobs[0])


def test_length_delimited_payload_never_becomes_text():
    files = job_files(words=('Café',))
    data = bytearray(files['jobs/example.sgngl'])
    opaque = b'\x15\x08\x08\x00\x00\x00TEXT\x13\x00\x00\x00'
    data += opaque
    struct.pack_into('<I', data, 536, len(data) - 1024)
    files['jobs/example.sgngl'] = bytes(data)
    bundle = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, bundle.jobs[0])
    assert job.text == 'Café'
    assert job.revision.spans[0].audio == (opaque.hex(),)


def test_review_adopts_proposal_associations_without_discarding_original_anchors():
    original = anchors.Revision((anchors.AnchoredSpan('a', (0,), ('time-a',), 'Old.\n'),
                                 anchors.AnchoredSpan('b', (1,), ('time-b',), 'Keep.\n')))
    proposal = anchors.Revision((anchors.AnchoredSpan('proposal', (7, 8), ('passage-time',), 'New wording.\n'),))
    accepted = original.adopt(0, 5, proposal, 0, len(proposal.text))
    assert accepted.text == 'New wording.\nKeep.\n'
    inserted = next(s for s in accepted.spans if s.content == 'New wording.\n')
    assert inserted.stroke_refs == (7, 8) and inserted.audio == ('passage-time',)
    assert next(s for s in accepted.spans if s.identity == 'a').content == ''
    assert next(s for s in accepted.spans if s.identity == 'b').content == 'Keep.\n'


def test_damaged_deflate_is_reported_as_invalid_archive():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in job_files().items():
            z.writestr(name, data)
    data = bytearray(output.getvalue())
    name_len, extra_len = struct.unpack_from('<HH', data, 26)
    data[30 + name_len + extra_len] = 0x07  # Invalid DEFLATE block type.
    with pytest.raises(ValueError, match='Invalid'):
        archive.inspect_archive(bytes(data))
