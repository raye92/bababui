import json
import pytest
from app.src import documents
from app.tests.test_native_projects import native_doc


def test_import_screen_has_no_editable_text_or_save(tmp_path):
    doc = documents.Document()
    assert not doc.dirty
    with pytest.raises(ValueError, match='Import'):
        doc.set_text('original', 'text')
    with pytest.raises(ValueError, match='Import'):
        documents.save_document(doc, tmp_path/'blank.bababui')


def test_plaintext_is_preserved_but_not_opened(tmp_path):
    path = tmp_path/'old.txt'
    path.write_text('Keep this')
    with pytest.raises(ValueError, match='Plain-text'):
        documents.open_document(path)
    assert path.read_text() == 'Keep this'


def test_structured_state_is_the_only_serialized_text(tmp_path, monkeypatch):
    doc, _ = native_doc(tmp_path, monkeypatch)
    doc.set_text('incoming', 'Proposal')
    path = tmp_path/'session.json'
    documents.save_session(path, [doc], doc.id)
    raw = json.loads(path.read_text())
    assert raw['version'] == 2
    assert 'original' not in raw['documents'][0]
    assert 'incoming' not in raw['documents'][0]
    restored, active = documents.load_session(path)
    assert active == doc.id and restored[0].incoming == 'Proposal'


def test_legacy_recovery_is_backed_up_before_rejection(tmp_path):
    path = tmp_path/'session.json'
    data = json.dumps({'version': 1, 'documents': [{'original': 'Keep', 'incoming': 'Proposal'}]})
    path.write_text(data)
    with pytest.raises(ValueError):
        documents.load_session(path)
    assert path.read_text() == data
    assert path.with_name('session.json.legacy-backup').read_text() == data


def test_existing_casecat_project_v1_reads_and_validates_duplicate_text(tmp_path, monkeypatch):
    import io, zipfile
    doc, _ = native_doc(tmp_path, monkeypatch)
    path = tmp_path/'saved.bababui'
    documents.save_document(doc, path)
    with zipfile.ZipFile(path) as z:
        source = z.read('source.zip')
        raw = json.loads(z.read('document.json'))
    raw['version'] = 1
    raw['document'].update(original=doc.original, incoming=doc.incoming)
    def write():
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('source.zip', source)
            z.writestr('document.json', json.dumps(raw))
    write()
    assert documents.open_document(path).original == doc.original
    raw['document']['original'] = 'corrupted'
    write()
    with pytest.raises(ValueError):
        documents.open_document(path)
