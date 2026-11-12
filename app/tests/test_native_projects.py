from pathlib import Path
import io
import json
import zipfile

import pytest

from app.src import documents
from app.src.casecat import archive
from app.tests.test_native_casecat import zip_bytes


def native_doc(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    source = tmp_path/'example.zip'
    source.write_bytes(zip_bytes())
    return documents.import_casecat(source), source


def test_project_contains_original_zip_and_both_revisions_after_move(tmp_path, monkeypatch):
    doc, source = native_doc(tmp_path, monkeypatch)
    doc.set_text('original', 'Reviewed café.\n')
    doc.set_text('incoming', 'Pending revision.\n')
    doc.view = 1
    target = tmp_path/'example.bababui'
    documents.save_document(doc, target)
    assert not doc.dirty
    source.unlink()
    wav = Path(doc.wav_path)
    wav.unlink()
    moved = tmp_path/'moved'/'portable.bababui'
    moved.parent.mkdir()
    target.rename(moved)
    restored = documents.open_document(moved)
    assert (restored.original, restored.incoming, restored.view) == ('Reviewed café.\n', 'Pending revision.\n', 1)
    assert restored.native.bundle.data == zip_bytes()
    assert restored.native.original == doc.native.original
    assert restored.native.incoming == doc.native.incoming
    assert Path(restored.wav_path).read_bytes() == b'RIFF synthetic audio bytes'
    assert not restored.dirty
    copy = restored.duplicate()
    assert copy.native.bundle is restored.native.bundle
    copy.set_text('original', '')
    assert restored.original == 'Reviewed café.\n'
    assert copy.original == '' and copy.native.original.text == ''


def test_recovery_survives_removed_source_and_preserves_pending_edits(tmp_path, monkeypatch):
    doc, source = native_doc(tmp_path, monkeypatch)
    doc.set_text('incoming', 'Proposed.\n')
    recovery = tmp_path/'session.json'
    documents.save_session(recovery, [doc, doc.duplicate()], doc.id)
    source.unlink()
    restored, active = documents.load_session(recovery)
    assert active == doc.id
    assert len(restored) == 2
    assert restored[0].native.incoming == doc.native.incoming
    assert restored[0].native.bundle.data == zip_bytes()
    assert len(list((tmp_path/'session.json.assets').glob('*.zip'))) == 1


def test_repeated_recovery_does_not_read_or_hash_immutable_audio_archives(tmp_path, monkeypatch):
    doc, _ = native_doc(tmp_path, monkeypatch)
    recovery = tmp_path/'session.json'
    copies = [doc, doc.duplicate()]
    documents.save_session(recovery, copies, doc.id)
    read_bytes = Path.read_bytes
    sha256 = archive.hashlib.sha256

    def read_small_files(path):
        assert path.suffix != '.zip', 'Unchanged recovery assets must not be reread.'
        return read_bytes(path)

    def hash_small_values(data=b''):
        assert data != doc.native.bundle.data, 'Immutable ZIP digest must be cached.'
        return sha256(data)

    monkeypatch.setattr(Path, 'read_bytes', read_small_files)
    monkeypatch.setattr(archive.hashlib, 'sha256', hash_small_values)
    doc.set_text('incoming', 'An edited proposal.')
    documents.save_session(recovery, copies, doc.id)
    documents.save_session(recovery, copies, doc.id)


@pytest.mark.parametrize('damage', ['remove', 'change'])
def test_recovery_republishes_missing_or_changed_cached_assets(tmp_path, monkeypatch, damage):
    import os
    doc, _ = native_doc(tmp_path, monkeypatch)
    recovery = tmp_path/'session.json'
    documents.save_session(recovery, [doc], doc.id)
    asset = next((tmp_path/'session.json.assets').glob('*.zip'))
    if damage == 'remove':
        asset.unlink()
    else:
        before = asset.stat()
        asset.write_bytes(b'X' * before.st_size)
        os.utime(asset, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    documents.save_session(recovery, [doc], doc.id)
    assert asset.read_bytes() == doc.native.bundle.data


def test_failed_native_save_preserves_existing_project(tmp_path, monkeypatch):
    doc, _ = native_doc(tmp_path, monkeypatch)
    target = tmp_path/'example.bababui'
    documents.save_document(doc, target)
    before = target.read_bytes()
    doc.set_text('original', 'Changed')
    def fail(*args, **kwargs):
        raise OSError('Disk full')
    monkeypatch.setattr(archive.os, 'replace', fail)
    with pytest.raises(OSError):
        documents.save_document(doc)
    assert doc.dirty and target.read_bytes() == before
    assert not list(tmp_path.glob('.bababui-*.tmp'))


def test_project_export_uses_original_and_does_not_mark_saved(tmp_path, monkeypatch):
    from app.tests.test_native_structure import container_files
    from app.src.casecat.codec import load_job
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    bundle = archive.inspect_archive(zip_bytes(container_files()))
    doc = documents.import_casecat(bundle)
    doc.set_text('incoming', 'Proposal')
    doc.export_casecat(tmp_path/'output.zip')
    assert (tmp_path/'output.zip').read_bytes() == bundle.data
    assert doc.dirty and doc.save_path is None
    doc.set_text('original', 'Reviewed')
    doc.export_casecat(tmp_path/'edited.zip')
    exported = archive.inspect_archive(tmp_path/'edited.zip')
    assert load_job(exported, exported.jobs[0]).text == 'Reviewed'
    assert doc.incoming == 'Proposal' and doc.dirty and doc.save_path is None


def test_native_filename_suggestion(tmp_path, monkeypatch):
    doc, _ = native_doc(tmp_path, monkeypatch)
    assert documents.suggested_path(doc, tmp_path).name == 'example.bababui'


def corrupt_project(target, change):
    with zipfile.ZipFile(target) as source:
        original = source.read('source.zip')
        record = json.loads(source.read('document.json'))
    change(record)
    with zipfile.ZipFile(target, 'w') as output:
        output.writestr('source.zip', original)
        output.writestr('document.json', json.dumps(record))


@pytest.mark.parametrize('change', [
    lambda r: r['native']['original']['spans'][0].update(stroke_refs=[]),
    lambda r: r['native']['original']['spans'].reverse(),
    lambda r: r['native']['original']['spans'][0].update(audio=['invented-time']),
    lambda r: r['native']['incoming']['spans'][0].update(formatting=['invalid']),
    lambda r: r['document'].update(warnings=[{}]),
    lambda r: r['document'].update(unknown_setting=True),
    lambda r: r['document'].update(view='invalid'),
    lambda r: r['document'].update(busy='invalid'),
])
def test_corrupt_project_rejected_with_value_error(tmp_path, monkeypatch, change):
    doc, _ = native_doc(tmp_path, monkeypatch)
    target = tmp_path/'example.bababui'
    documents.save_document(doc, target)
    corrupt_project(target, change)
    with pytest.raises(ValueError):
        documents.open_document(target)


def test_attached_audio_survives_project_and_recovery(tmp_path, monkeypatch):
    doc, _ = native_doc(tmp_path, monkeypatch)
    external = tmp_path/'replacement.wav'
    external.write_bytes(b'RIFF replacement')
    doc.audio_override = doc.wav_path = str(external)
    target = tmp_path/'audio.bababui'
    documents.save_document(doc, target)
    assert documents.open_document(target).wav_path == str(external)
    session = tmp_path/'session.json'
    documents.save_session(session, [doc], doc.id)
    assert documents.load_session(session)[0][0].wav_path == str(external)
