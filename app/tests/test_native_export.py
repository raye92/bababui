import zipfile

import pytest

from app.src.casecat.archive import inspect_archive, export_zip
from app.src.casecat.codec import load_job
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
