import struct
import zipfile
from dataclasses import replace

import pytest

from app.src.casecat.archive import inspect_archive, export_zip
from app.src.casecat.codec import load_job, records
from app.src import documents
from app.src.review_model import build_review
from app.src.suggestions import resolve_all
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_fields import field_files, native_stream
from app.tests.test_native_layout import layout_bytes
from app.tests.test_native_structure import container_files


def test_accept_all_export_uses_colloquy_indent_for_new_speaker_turns(tmp_path):
    layout = bytearray(layout_bytes(first=3600))
    default = layout[1024:1536]
    colloquy = bytearray(default)
    struct.pack_into('<H', colloquy, 174, 2880)
    layout[1536:1536] = default * 2 + colloquy
    struct.pack_into('<I', layout, 4, 4)
    files = field_files(layout=layout)
    del files['jobs/example.wav']
    doc = documents.import_casecat(inspect_archive(zip_bytes(files)))
    original = doc.native.original
    incoming = original.replace(len(original.text), len(original.text),
                                '\n     MR. COUNSEL:  One question.\n     :  Go ahead.\n          More testimony.')
    start = incoming.text.index(':  Go ahead.')
    incoming = incoming.insert_field(start, 'EZ SPEAKER 01', 'MS. OLD')
    review = build_review(original, incoming)
    doc.native.original, doc.native.incoming = resolve_all(original, incoming, review.ranges, True)

    target = tmp_path / 'accepted.zip'
    doc.export_casecat(target)
    restored_bundle = inspect_archive(target)
    restored = load_job(restored_bundle, restored_bundle.jobs[0])
    assert restored.text == incoming.text
    assert any(element.start == start and element.kind == 'field' for element in restored.revision.elements)
    stream = native_stream(restored)
    paragraph_styles = [int.from_bytes(raw[1:], 'little')
                        for _, raw in records(stream, 0, len(stream)) if raw[0] == 0x16]
    assert paragraph_styles == [5, 2, 3, 4, 4, 4, 255]


def test_export_moves_boundary_to_retained_byline_control(tmp_path):
    byline = b'\x16\x05\x00\x11\x06\x02\x00\x00\x00BY COUNSEL:'
    bundle = inspect_archive(zip_bytes(container_files(('Before. ', byline.decode('cp1252')))))
    job = load_job(bundle, bundle.jobs[0])
    # Accepted edits can leave the LF on the preceding stroke while retaining
    # the by-line symbol and its own paragraph control on the next stroke.
    first, second = job.baseline.spans
    revision = replace(job.baseline,
                       spans=(replace(first, content='Before.\n'),
                              replace(second, content='BY COUNSEL:')),
                       elements=tuple(replace(e, start=e.start-1, end=e.end-1)
                                      for e in job.baseline.elements))
    target = tmp_path / 'byline.zip'

    export_zip(bundle, job.with_revision(revision), target)

    exported = inspect_archive(target)
    restored = load_job(exported, job.key)
    assert restored.text == 'Before.\nBY COUNSEL:'
    assert bytes.fromhex(restored.baseline.elements[0].raw) == byline[:12]
    assert restored.stroke_clocks == job.stroke_clocks
    assert restored.notes_bytes == job.notes_bytes
    for name in bundle.members:
        if name != bundle.member(job.key + '.sgngl'):
            assert exported.read(name) == bundle.read(name)


def test_edited_export_updates_only_selected_native_member(tmp_path):
    files = container_files()
    files.update({name.replace('example', 'other'): value for name, value in container_files().items()})
    bundle = inspect_archive(zip_bytes(files), name='example.zip')
    job = load_job(bundle, 'jobs/example')
    job = job.with_revision(job.revision.replace(0, len(job.text), 'lowercase café.\n     Q    question?'))
    destination = tmp_path / bundle.export_name
    export_zip(bundle, job, destination)
    exported = inspect_archive(destination)
    assert load_job(exported, job.key).text == job.text
    with zipfile.ZipFile(destination) as archive:
        assert archive.comment == b'Keep the comment'
        assert archive.namelist() == list(files)
        for name, original in files.items():
            if name != 'jobs/example.sgngl':
                assert archive.read(name) == original


def test_failed_edited_export_does_not_replace_destination(tmp_path):
    bundle = inspect_archive(zip_bytes(container_files()))
    job = load_job(bundle, bundle.jobs[0])
    job = job.with_revision(job.revision.replace(0, len(job.text), 'Unsupported \U0001f600'))
    destination = tmp_path / 'existing.zip'
    destination.write_bytes(b'keep existing')
    with pytest.raises(ValueError, match='Windows-1252'):
        export_zip(bundle, job, destination, overwrite=True)
    assert destination.read_bytes() == b'keep existing'


@pytest.mark.parametrize('edited', [False, True])
def test_project_export_restores_as_separate_jobs_with_linked_audio(tmp_path, monkeypatch, edited):
    files = container_files()
    native = bytearray(files.pop('jobs/example.sgngl'))
    audio_records = struct.pack('<10I', 3, *range(9))
    audio_paths = b'\0'.join((br'C:\old case\Example.WAV', br'D:\recordings\Example.wav', b'external.wav'))
    audio = audio_paths.ljust(260, b'\0') + audio_records
    struct.pack_into('<I', native, 560, len(audio))
    files['jobs/example.SGNGL'] = native[:-3] + audio
    files['jobs/example.sgdct'] = b'job dictionary'
    files.update({name.replace('example', 'second'): data
                  for name, data in container_files().items() if name.startswith('jobs/')})
    files['Shared/'] = b''
    files['Shared/readme.txt'] = b'archive information'
    bundle = inspect_archive(zip_bytes(files), name='archive.zip')
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    doc = documents.import_casecat(bundle, 'jobs/example')
    if edited:
        doc.set_text('original', 'Reviewed transcript.')
    target = tmp_path/'custom name.zip'

    doc.export_casecat(target)

    exported = inspect_archive(target)
    assert exported.jobs == ('jobs/example_AI', 'jobs/second_AI')
    restored = load_job(exported, 'jobs/example_AI')
    assert restored.text == ('Reviewed transcript.' if edited else doc.original)
    assert restored.notes_bytes == files['jobs/example.sgstn']
    assert restored.audio_member == 'jobs/example_AI.wav'
    assert exported.read(restored.audio_member) == files['jobs/example.wav']
    address, size = struct.unpack_from('<II', restored.native_bytes, 556)
    relinked = b'example_AI.wav\0example_AI.wav\0external.wav'.ljust(260, b'\0')
    assert restored.native_bytes[address:address+size] == relinked + audio_records
    renamed = {'jobs/example.sgstn': 'jobs/example_AI.sgstn',
               'jobs/example.sgxml': 'jobs/example_AI.sgxml',
               'jobs/example.wav': 'jobs/example_AI.wav',
               'jobs/example.SGNGL': 'jobs/example_AI.SGNGL',
               'jobs/example.sgdct': 'jobs/example_AI.sgdct',
               'jobs/second.sgngl': 'jobs/second_AI.sgngl',
               'jobs/second.sgstn': 'jobs/second_AI.sgstn',
               'jobs/second.sgxml': 'jobs/second_AI.sgxml',
               'jobs/second.wav': 'jobs/second_AI.wav'}
    with zipfile.ZipFile(target) as result:
        assert result.comment == b'Keep the comment'
        assert result.namelist() == [renamed.get(name, name) for name in files]
        for name, data in files.items():
            if name != 'jobs/example.SGNGL':
                assert result.read(renamed.get(name, name)) == data


def test_ai_export_handles_existing_job_suffixes_and_companions(tmp_path, monkeypatch):
    files = container_files()
    files.update({name.replace('example', 'example_AI'): data
                  for name, data in container_files().items() if name.startswith('jobs/')})
    files['jobs/EXAMPLE_2_AI.txt'] = b'independent file'
    bundle = inspect_archive(zip_bytes(files), name='archive.zip')
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    first = tmp_path/'first.zip'
    documents.import_casecat(bundle, 'jobs/example').export_casecat(first)
    renamed = inspect_archive(first)
    assert renamed.jobs == ('jobs/example_3_AI', 'jobs/example_AI')
    assert renamed.read('jobs/EXAMPLE_2_AI.txt') == b'independent file'

    second = tmp_path/'second.zip'
    documents.import_casecat(renamed, 'jobs/example_3_AI').export_casecat(second)
    assert second.read_bytes() == first.read_bytes()
