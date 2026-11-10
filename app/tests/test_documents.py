import json
from pathlib import Path
import pytest
from app.src.documents import Document, save_document, open_document, companion, suggested_path, save_session, load_session


def test_save_roundtrip_and_duplicate(tmp_path):
    doc = Document(original='Reviewed', incoming='Proposed', wav_path=str(tmp_path/'missing.wav'),
                   model='deepseek-v4-pro')
    target = tmp_path/'version.txt'
    save_document(doc, target)
    assert not doc.dirty and target.read_text() == 'Reviewed'
    restored = open_document(target)
    assert (restored.original, restored.incoming, restored.wav_path, restored.model) == (
        doc.original, doc.incoming, doc.wav_path, doc.model)
    copy = restored.duplicate()
    assert copy.id != restored.id and copy.dirty and copy.save_path is None and not copy.busy


def test_new_save_rejects_text_or_sidecar_collision(tmp_path):
    target = tmp_path/'existing.txt'
    target.write_text('Do not overwrite')
    with pytest.raises(ValueError, match='exists'):
        save_document(Document(original='New'), target)
    assert target.read_text() == 'Do not overwrite'
    target.unlink()
    companion(target).write_text('{}')
    with pytest.raises(ValueError, match='exists'):
        save_document(Document(), target)


def test_save_updates_owned_file_but_save_as_requires_unique_path(tmp_path):
    doc = Document(original='One')
    target = tmp_path/'one.txt'
    save_document(doc, target)
    doc.original = 'Two'
    doc.dirty = True
    save_document(doc)
    assert target.read_text() == 'Two' and not doc.dirty
    with pytest.raises(ValueError):
        save_document(doc, target, save_as=True)


def test_plain_text_and_mismatched_metadata(tmp_path):
    target = tmp_path/'plain.txt'
    target.write_text('Plain')
    doc = open_document(target)
    assert doc.original == doc.incoming == 'Plain' and not doc.wav_path
    save_document(doc)
    target.write_text('Externally changed')
    restored = open_document(target)
    assert restored.incoming == restored.original == 'Externally changed'
    assert restored.warnings and restored.dirty


def test_failed_save_stays_dirty_and_reports_incomplete_state(tmp_path, monkeypatch):
    import app.src.documents as storage
    doc = Document(original='One', incoming='Two')
    target = tmp_path/'one.txt'
    real = storage.atomic_bytes
    def fail_metadata(path, content):
        if Path(path) == companion(target):
            raise OSError('Disk full')
        real(path, content)
    monkeypatch.setattr(storage, 'atomic_bytes', fail_metadata)
    with pytest.raises(OSError):
        save_document(doc, target)
    assert doc.dirty
    if target.exists():
        assert open_document(target).warnings


def test_session_restores_unsaved_work_and_interrupts_jobs(tmp_path):
    doc = Document(original='Unsaved', incoming='Incoming', busy=True, view=1,
                   model='deepseek-v4-pro', wav_path='missing.wav')
    path = tmp_path/'session.json'
    save_session(path, [doc], doc.id)
    docs, active = load_session(path)
    assert active == doc.id and docs[0].id == doc.id
    assert docs[0].dirty and not docs[0].busy and docs[0].view == 1
    assert 'interrupted' in docs[0].status.lower()
    assert docs[0].original == 'Unsaved' and docs[0].incoming == 'Incoming'


def test_suggested_filename_avoids_both_collisions(tmp_path):
    (tmp_path/'meeting.txt').touch()
    companion(tmp_path/'meeting (2).txt').touch()
    assert suggested_path(Document(wav_path='meeting.wav'), tmp_path).name == 'meeting (3).txt'


def test_incomplete_metadata_never_applies_pending_revisions(tmp_path):
    target = tmp_path/'one.txt'
    save_document(Document(original='Reviewed', incoming='Untrusted proposal', wav_path='audio.wav'), target)
    meta = json.loads(companion(target).read_text())
    del meta['transcription_model']
    companion(target).write_text(json.dumps(meta))
    doc = open_document(target)
    assert doc.original == doc.incoming == 'Reviewed'
    assert doc.wav_path is None and doc.warnings
