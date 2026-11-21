"""A CaseCAT date field: a nameless field record that stores a date.

The record is the one CATalyst 22.1 wrote after "Dated this" in a reporter's
certificate (261106lewis_Scoped, November 19, 2026).
"""
import struct

import pytest

from app.src.casecat import archive, codec
from app.src.casecat.anchors import Revision
from app.src.casecat.clipboard import paste_revision, selection_data
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_structure import container_files


DATE = b'\x15\x07\x08\x00\x00\x00\xea\x97\xe5\x96' + struct.pack('<I', 20261119)
WORDS = ('\x16\xff\x00I declare that the foregoing is true and correct. ',
         'Dated this ' + DATE.decode('cp1252') + '.')


def date_files(words=WORDS):
    """A job whose field table is valid and empty, as in a real job without named fields."""
    files = container_files(words)
    native = bytearray(files['jobs/example.sgngl'])
    offset, size = struct.unpack_from('<II', native, 632)
    table = struct.pack('<I', 0)
    struct.pack_into('<I', native, 636, len(table))
    struct.pack_into('<I', native, 556, codec.u32(native, 556) + len(table) - size)
    native[offset:offset + size] = table
    files['jobs/example.sgngl'] = bytes(native)
    return files


def date_job(record=DATE):
    words = tuple(word.replace(DATE.decode('cp1252'), record.decode('cp1252')) for word in WORDS)
    bundle = archive.inspect_archive(zip_bytes(date_files(words)))
    return bundle, codec.load_job(bundle, 'jobs/example')


def test_a_date_field_imports_as_a_readable_date():
    _, job = date_job()
    assert job.text.endswith('Dated this November 19, 2026.')
    date, = [e for e in job.revision.elements if e.kind == 'date']
    assert job.text[date.start:date.end] == 'November 19, 2026'
    assert bytes.fromhex(date.raw) == DATE
    assert not [e for e in job.revision.elements if e.kind == 'field']


def test_a_date_field_keeps_its_bytes_through_edits_export_and_restore(tmp_path):
    bundle, job = date_job()
    start = job.text.index('true and correct')
    revision = job.revision.replace(start, start + 4, 'accurate')
    assert Revision.from_dict(revision.to_dict()) == revision
    target = tmp_path / 'dated.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    restored = codec.load_job(archive.inspect_archive(target), job.key)
    assert restored.text == revision.text
    assert restored.native_bytes.count(DATE) == 1


def test_a_date_field_is_copied_and_pasted_whole():
    bundle, job = date_job()
    start = job.text.index('Dated this')
    data = selection_data(job.revision, start, len(job.text))
    pasted = paste_revision(job.revision, job.baseline, 0, 0, data)
    assert pasted.text.startswith('Dated this November 19, 2026.')
    assert [pasted.text[e.start:e.end] for e in pasted.elements if e.kind == 'date'] == ['November 19, 2026'] * 2
    assert codec.serialize_native(job.with_revision(pasted), bundle).count(DATE) == 2


def test_deleting_text_around_a_date_field_removes_it_whole():
    bundle, job = date_job()
    date, = [e for e in job.revision.elements if e.kind == 'date']
    revision = job.revision.replace(date.start - len('Dated this '), date.end + 1, '')
    assert revision.text.endswith('true and correct. ')
    assert codec.serialize_native(job.with_revision(revision), bundle).count(DATE) == 0


@pytest.mark.parametrize('record', [
    b'\x15\x07\x08\x00\x00\x00\xea\x97\xe5\x96' + struct.pack('<I', 20261341),  # Not a date.
    b'\x15\x07\x04\x00\x00\x00\xea\x97\xe5\x96',  # No name and no date.
])
def test_an_unknown_field_record_names_its_position(record):
    with pytest.raises(ValueError, match=r'^Unsupported CaseCAT field record at byte \d+\. '):
        date_job(record)
