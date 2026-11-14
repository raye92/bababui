"""Semantic assertions use native bytes observed in CaseCAT 22.1."""
import struct
import xml.etree.ElementTree as ET
from dataclasses import replace
import pytest

from app.src.casecat import archive, codec
from app.src.casecat.anchors import Revision
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_structure import container_files


FIELD = b'\x15\x07\x12\x00\x00\x00\x01\x01\x01\x01EZ SPEAKER 01\x00'
ORPHAN = b'\x11\x06\x02\x00\x00\x00'


def field_files(value='MS. OLD'):
    words = (b'\x16\x05\x00' + ORPHAN + b'BY ' + FIELD + b':\x16\x02\x00Question?',
             b'\x16\x03\x00Yes.\x16\x04\x00' + FIELD + b': More.')
    files = container_files(tuple(word.decode('cp1252') for word in words))
    native = bytearray(files['jobs/example.sgngl'])
    offset, size = struct.unpack_from('<II', native, 632)
    entry = bytearray(128)
    entry[:14] = b'EZ SPEAKER 01\0'
    entry[64:68] = b'\x01' * 4
    struct.pack_into('<I', entry, 72, len(value.encode('cp1252')))
    table = struct.pack('<I', 1) + entry + value.encode('cp1252')
    struct.pack_into('<I', native, 636, len(table))
    struct.pack_into('<I', native, 556, codec.u32(native, 556) + len(table) - size)
    native[offset:offset+size] = table
    files['jobs/example.sgngl'] = bytes(native)
    files['jobs/example.sgxml'] = (
        b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
        b'<SGXML_Preferences><!--preserve--><Speaker><Speaker-1 sgpref-val="MS. OLD" '
        b'Steno=""/><Speaker-2 sgpref-val="OTHER"/></Speaker><Other value="keep"/></SGXML_Preferences>').replace(b'MS. OLD', value.encode())
    return files


def field_job():
    bundle = archive.inspect_archive(zip_bytes(field_files()))
    return bundle, codec.load_job(bundle, 'jobs/example')


def native_stream(job):
    start = codec.u32(job.native_bytes, 532)
    return job.native_bytes[start:start + codec.u32(job.native_bytes, 536)]


def test_import_exposes_field_identity_and_atomic_question_spacing():
    _, job = field_job()
    fields = [e for e in job.revision.elements if e.kind == 'field']
    assert len(fields) == 2
    assert {e.name for e in fields} == {'EZ SPEAKER 01'}
    assert [job.text[e.start:e.end] for e in fields] == ['MS. OLD', 'MS. OLD']
    symbols = [e for e in job.revision.elements if e.kind == 'symbol']
    assert '     Q    ' in [job.text[e.start:e.end] for e in symbols]


def test_typing_inside_speaker_updates_linked_fields_and_retains_references(tmp_path):
    bundle, job = field_job()
    start = job.text.index('OLD')
    revision = job.revision.replace(start, start + 3, 'NEW & CO')
    assert revision.text.count('MS. NEW & CO') == 2
    assert Revision.from_dict(revision.to_dict()) == revision
    target = tmp_path / 'fields.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    exported = archive.inspect_archive(target)
    restored = codec.load_job(exported, job.key)
    assert restored.text == revision.text
    assert native_stream(restored) == native_stream(job)
    metadata = exported.read('jobs/example.sgxml')
    assert b'<!--preserve-->' in metadata
    assert ET.fromstring(metadata).find('./Speaker/Speaker-1').get('sgpref-val') == 'MS. NEW & CO'
    for name in bundle.members:
        if name not in ('jobs/example.sgxml', 'jobs/example.sgngl'):
            assert exported.read(name) == bundle.read(name)
    raw = restored.native_bytes
    cache = raw[codec.u32(raw, 632):codec.u32(raw, 632)+codec.u32(raw, 636)]
    assert cache[132:] == b'MS. NEW & CO'
    assert codec.u32(cache, 76) == 12
    assert codec.u32(cache, 84) == 12


def test_question_to_answer_edit_exports_a_symbol_not_literal_letters(tmp_path):
    bundle, job = field_job()
    start = job.text.index('Q    ')
    revision = job.revision.replace(start, start + 1, 'A')
    destination = tmp_path / 'answer.zip'
    archive.export_zip(bundle, job.with_revision(revision), destination)
    restored = codec.load_job(archive.inspect_archive(destination), job.key)
    assert restored.text == job.text.replace('     Q    ', '     A    ')
    stream = native_stream(restored)
    assert b'\x16\x02\x00' not in stream
    assert stream.count(b'\x16\x03\x00') == 2
    assert stream.count(FIELD) == 2
    assert ORPHAN in stream


def test_deleting_part_of_question_symbol_deletes_whole_label():
    _, job = field_job()
    start = job.text.index('Q    ')
    revision = job.revision.replace(start, start + 1, '')
    assert '\nQuestion?' in revision.text
    assert '     ' not in revision.text.split('Question?')[0].split('\n')[-1]


def test_body_edit_preserves_fields_and_symbols_after_export(tmp_path):
    bundle, job = field_job()
    revision = job.revision.revise(job.text.replace('Question?', 'Another question?'))
    target = tmp_path / 'body.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    exported = archive.inspect_archive(target)
    restored = codec.load_job(exported, job.key)
    assert restored.text == revision.text
    assert native_stream(restored).count(FIELD) == 2
    assert b'\x16\x02\x00' in native_stream(restored)
    assert exported.read('jobs/example.sgxml') == bundle.read('jobs/example.sgxml')


def test_whole_text_proposal_renames_the_field_without_flattening():
    _, job = field_job()
    revision = job.revision.revise(job.text.replace('MS. OLD', 'MS. NEW', 1))
    assert revision.text.count('MS. NEW') == 2
    assert len([e for e in revision.elements if e.kind == 'field']) == 2


def test_project_reload_retains_independent_speaker_values(tmp_path, monkeypatch):
    from app.src import documents
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    files = field_files()
    del files['jobs/example.wav']
    source = tmp_path/'source.zip'
    source.write_bytes(zip_bytes(files))
    doc = documents.import_casecat(source)
    doc.set_text('incoming', doc.incoming.replace('MS. OLD', 'MS. NEW'))
    target = tmp_path/'edit.bababui'
    documents.save_document(doc, target)
    restored = documents.open_document(target)
    assert restored.native.original == doc.native.original
    assert restored.native.incoming == doc.native.incoming
    assert len(restored.native.incoming.elements) == 5


def test_document_proposal_keeps_normalized_linked_values(tmp_path):
    from app.src.documents import Document
    from app.src.casecat.project import NativeState
    bundle, job = field_job()
    doc = Document(native=NativeState(bundle, job, job.revision, job.revision))
    doc.set_text('incoming', job.text.replace('MS. OLD', 'MS. NEW', 1))
    assert doc.incoming.count('MS. NEW') == 2
    assert doc.incoming == doc.native.incoming.text


def test_legacy_project_restores_native_elements():
    from app.src.casecat.project import NativeState
    bundle, job = field_job()
    state = NativeState.load(bundle, job.key)
    record = state.to_dict()
    del record['original']['elements']
    del record['incoming']['elements']
    restored = NativeState.restore(bundle, record)
    assert restored.original.elements == job.baseline.elements


def test_forged_native_element_is_rejected_before_export(tmp_path):
    bundle, job = field_job()
    field = next(e for e in job.revision.elements if e.kind == 'field')
    forged = replace(field, raw=FIELD.hex().replace('303100', '303200'))
    revision = replace(job.revision, elements=tuple(forged if e is field else e for e in job.revision.elements))
    with pytest.raises(ValueError, match='field|element'):
        archive.export_zip(bundle, job.with_revision(revision), tmp_path/'forged.zip')


def test_partial_field_accept_updates_all_linked_occurrences():
    _, job = field_job()
    incoming = job.revision.set_field('EZ SPEAKER 01', 'MS. NEW')
    end = job.text.index('\n') + 1
    accepted = job.revision.adopt(0, end, incoming, 0, end)
    assert accepted.text.count('MS. NEW') == 2
    assert len([e for e in accepted.elements if e.kind == 'field']) == 2


def test_native_field_table_takes_precedence_over_stale_xml():
    files = field_files()
    files['jobs/example.sgxml'] = files['jobs/example.sgxml'].replace(b'MS. OLD', b'STALE XML')
    bundle = archive.inspect_archive(zip_bytes(files))
    assert codec.load_job(bundle, 'jobs/example').text.count('MS. OLD') == 2


def test_first_field_creates_a_missing_native_definition_table(tmp_path):
    files = container_files()
    native = bytearray(files['jobs/example.sgngl'])
    offset, size = struct.unpack_from('<II', native, 632)
    del native[offset:offset+size]
    struct.pack_into('<I', native, 556, codec.u32(native, 556) - size)
    struct.pack_into('<II', native, 632, 0, 0)
    files['jobs/example.sgngl'] = bytes(native)
    bundle = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, 'jobs/example')
    revision = job.revision.insert_field(len(job.text), 'NEW NAME', 'MS. FIRST')
    target = tmp_path/'first-field.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    restored = codec.load_job(archive.inspect_archive(target), job.key)
    assert restored.text == revision.text
    assert restored.revision.elements[-1].name == 'NEW NAME'
    assert restored.notes_bytes == job.notes_bytes


def test_mixed_case_field_baseline_and_rename_roundtrip(tmp_path):
    bundle = archive.inspect_archive(zip_bytes(field_files('john doe')))
    job = codec.load_job(bundle, 'jobs/example')
    target = tmp_path/'baseline.zip'
    archive.export_zip(bundle, job, target)
    assert target.read_bytes() == bundle.data
    revision = job.revision.set_field('EZ SPEAKER 01', 'jane smith')
    assert revision.text.startswith('BY jane smith:')
    assert '\n     Jane smith: More.' in revision.text
    archive.export_zip(bundle, job.with_revision(revision), tmp_path/'changed.zip')
    restored = codec.load_job(archive.inspect_archive(tmp_path/'changed.zip'), job.key)
    assert restored.text == revision.text


@pytest.mark.parametrize('edit', ['delete_question', 'leading_blank', 'delete_byline'])
def test_paragraph_boundary_edits_export_without_extra_or_missing_breaks(tmp_path, edit):
    bundle, job = field_job()
    start, end, value = {'delete_question': (12, 32, ''), 'leading_blank': (0, 0, '\n'),
                         'delete_byline': (0, 11, '')}[edit]
    revision = job.revision.replace(start, end, value)
    target = tmp_path/'boundary.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    assert codec.load_job(archive.inspect_archive(target), job.key).text == revision.text


def test_insert_named_field_writes_definition_reference_and_linked_value(tmp_path):
    bundle, job = field_job()
    revision = job.revision.insert_field(len(job.text), 'PARITY NAME', 'MS. ADDED')
    revision = revision.insert_field(3, 'PARITY NAME', 'MS. ADDED')
    revision = revision.set_field('PARITY NAME', 'MS. CHANGED')
    assert revision.text.count('MS. CHANGED') == 2
    target = tmp_path/'new-field.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    restored = codec.load_job(archive.inspect_archive(target), job.key)
    assert restored.text == revision.text
    assert native_stream(restored).count(bytes.fromhex('150710000000aeb8e083504152495459204e414d4500')) == 2


def test_empty_field_keeps_an_editable_placeholder_and_native_reference(tmp_path):
    bundle, job = field_job()
    revision = job.revision.set_field('EZ SPEAKER 01', '')
    assert revision.text.count('[!EZ SPEAKER 01]') == 2
    target = tmp_path/'empty-field.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    restored = codec.load_job(archive.inspect_archive(target), job.key)
    assert restored.text == revision.text
    assert native_stream(restored).count(FIELD) == 2


def test_byline_is_retained_with_its_native_style_and_orphan_control():
    _, job = field_job()
    byline = [e for e in job.revision.elements if e.name == 'By-line']
    assert len(byline) == 1
    assert job.text[byline[0].start:byline[0].end] == 'BY '
    assert bytes.fromhex(byline[0].raw) == b'\x16\x05\x00' + ORPHAN + b'BY '


def test_insert_field_cannot_split_an_existing_native_element():
    _, job = field_job()
    with pytest.raises(ValueError, match='outside'):
        job.revision.insert_field(6, 'NEW', 'NEW')


def test_all_caps_field_edits_and_insertions_preserve_rendering_mode(tmp_path):
    files = field_files('john doe')
    files['jobs/example.sgxml'] = files['jobs/example.sgxml'].replace(
        b'<Other', b'<Capitalize-All-Text sgpref-val="1"/><Other')
    bundle = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, 'jobs/example')
    revision = job.revision.set_field('EZ SPEAKER 01', 'jane smith')
    revision = revision.insert_field(len(revision.text), 'NEW NAME', 'new person')
    assert 'jane smith' not in revision.text
    assert revision.text.count('JANE SMITH') == 2
    assert revision.text.endswith('NEW PERSON')
    assert Revision.from_dict(revision.to_dict()) == revision
    target = tmp_path/'all-caps.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    assert codec.load_job(archive.inspect_archive(target), job.key).text == revision.text


def test_clipboard_keeps_byline_fields_and_question_symbols(tmp_path):
    from app.src.casecat.clipboard import selection_data, paste_revision
    bundle, job = field_job()
    end = job.text.index('Question?')
    data = selection_data(job.revision, 0, end)
    changed = job.revision.set_field('EZ SPEAKER 01', 'MS. CURRENT')
    revision = paste_revision(changed, job.baseline, len(changed.text), len(changed.text), data)
    assert revision.text.endswith('\nBY MS. CURRENT:\n     Q    ')
    assert len([e for e in revision.elements if e.kind == 'field']) == 3
    target = tmp_path/'clipboard.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    restored = codec.load_job(archive.inspect_archive(target), job.key)
    assert restored.text == revision.text
    assert native_stream(restored).count(FIELD) == 3
    assert native_stream(restored).count(ORPHAN) == 2


def test_moving_byline_preserves_field_and_native_byline_structure(tmp_path):
    bundle, job = field_job()
    text = job.text[12:] + '\n' + job.text[:11]
    revision = job.revision.replace(0, len(job.text), text)
    target = tmp_path/'moved.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    restored = codec.load_job(archive.inspect_archive(target), job.key)
    assert restored.text == text
    assert native_stream(restored).count(FIELD) == 2
    assert native_stream(restored).count(b'\x16\x05\x00') == 1
    assert ORPHAN in native_stream(restored)


def test_new_ez_speaker_is_added_to_native_and_xml_definitions(tmp_path):
    bundle, job = field_job()
    revision = job.revision.insert_field(len(job.text), 'EZ SPEAKER 03', 'MS. THIRD')
    target = tmp_path/'speaker3.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    exported = archive.inspect_archive(target)
    assert ET.fromstring(exported.read('jobs/example.sgxml')).find('./Speaker/Speaker-3').get('sgpref-val') == 'MS. THIRD'
    assert codec.load_job(exported, job.key).text == revision.text


def test_native_only_field_job_does_not_require_xml_for_a_rename(tmp_path):
    files = field_files()
    del files['jobs/example.sgxml']
    bundle = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, 'jobs/example')
    revision = job.revision.set_field('EZ SPEAKER 01', 'MS. NATIVE')
    target = tmp_path/'native-only.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    assert codec.load_job(archive.inspect_archive(target), job.key).text == revision.text
