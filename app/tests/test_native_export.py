import struct
import zipfile

import pytest

from app.src.casecat.archive import inspect_archive, export_zip
from app.src.casecat.codec import load_job
from app.src import documents
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_structure import container_files


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
