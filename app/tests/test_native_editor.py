import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtGui import QTextCursor, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton
from PySide6.QtTest import QTest
import pytest

from app.src import documents
from app.src.main import TranscriptEditor
from app.src.document_view import DocumentView
from app.tests.test_native_casecat import zip_bytes, job_files


@pytest.fixture
def native_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    window = TranscriptEditor(session_path=tmp_path/'session.json', legacy_dir=tmp_path)
    window.show()
    app.processEvents()
    yield window
    window.close()


def source_zip(tmp_path, *, audio=True):
    source = tmp_path/'example.zip'
    source.write_bytes(zip_bytes(job_files(audio=audio)))
    return source


def test_review_card_click_and_space_playback(native_window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel
    native_window.import_zip(0, source_zip(tmp_path))
    view = native_window.current
    view.receive('A different proposed passage.', [])
    app = QApplication.instance()
    app.processEvents()
    assert view.diff_view.changes
    centered = []
    monkeypatch.setattr(view.editor, 'scroll_to_center_line', centered.append)
    card = view.diff_view.cards[0]
    QTest.mouseClick(card.findChild(QLabel), Qt.LeftButton)
    assert centered
    toggles = []
    monkeypatch.setattr(view.playback, 'toggle', lambda: toggles.append(True))
    native_window.activateWindow()
    for target in (view.editor, card.findChild(QPushButton)):
        target.setFocus()
        app.processEvents()
        before = len(toggles)
        QTest.keyClick(target, Qt.Key_Space)
        assert len(toggles) == before + 1


def test_native_import_uses_casecat_pages(native_window, tmp_path):
    from PySide6.QtWidgets import QTextEdit
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    for editor in (view.editor, view.incoming_editor):
        assert isinstance(editor, QTextEdit)
        assert editor.lineWrapMode() == QTextEdit.FixedPixelWidth
        assert editor._page_width > 0
        assert editor.toPlainText() == view.document.native.original.text


def test_playback_stays_compact_when_window_resizes(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path))
    view = native_window.current
    app = QApplication.instance()
    for height in (650, 900):
        native_window.resize(1100, height)
        app.processEvents()
        assert view.playback.height() <= view.playback.sizeHint().height() + 2
        assert view.review_splitter.height() > view.height() * 0.8
        assert view.playback.geometry().bottom() >= view.height() - 2


def test_import_cancel_and_parse_failure_leave_active_document_untouched(native_window, tmp_path, monkeypatch):
    window = native_window
    window.import_zip(0, source_zip(tmp_path, audio=False))
    view = window.current
    view.editor.setPlainText('Existing work')
    monkeypatch.setattr(window, 'confirm_native_replace', lambda view: 'cancel')
    window.import_zip(0, source_zip(tmp_path))
    assert window.current is view and view.document.original == 'Existing work'
    assert view.document.native is not None
    bad = tmp_path/'bad.zip'
    bad.write_bytes(b'broken')
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)
    window.import_zip(0, bad)
    assert window.current is view and view.document.original == 'Existing work'


def test_import_save_before_replace_and_missing_audio(native_window, tmp_path, monkeypatch):
    window = native_window
    window.import_zip(0, source_zip(tmp_path, audio=False))
    window.current.editor.setPlainText('Keep this')
    target = tmp_path/'old.bababui'
    monkeypatch.setattr(window, 'confirm_native_replace', lambda view: 'save')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    window.import_zip(0, source_zip(tmp_path, audio=False))
    assert documents.open_document(target).original == 'Keep this'
    assert window.current.document.original == window.current.document.incoming == 'Hello world.\n'
    assert window.current.document.native and window.current.document.wav_path is None
    assert not window.bababui_btn.isEnabled()
    assert 'Export CaseCAT ZIP' in window.file_actions


def test_zip_drop_and_baseline_export(native_window, tmp_path, monkeypatch):
    source = source_zip(tmp_path)
    bar = native_window.tabs.tabBar()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    event = QDropEvent(bar.tabRect(0).center(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    bar.dropEvent(event)
    assert event.isAccepted() and native_window.current.document.native
    target = tmp_path/'example_AI.zip'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    native_window.export_casecat()
    assert target.read_bytes() == source.read_bytes()
    assert native_window.current.document.dirty


def test_native_typing_undo_redo_restores_exact_associations(native_window, tmp_path):
    window = native_window
    window.import_zip(0, source_zip(tmp_path))
    view = window.current
    original = view.document.native.original
    cursor = view.editor.textCursor()
    cursor.setPosition(3)
    cursor.setPosition(8, QTextCursor.KeepAnchor)
    cursor.insertText('é😀\n')
    edited = view.document.native.original
    assert view.document.original == 'Helé😀\nrld.\n'
    assert edited.text == view.document.original
    assert set(ref for s in edited.spans for ref in s.stroke_refs) == {0, 1}
    view.toggle_view()
    view.toggle_view()
    view.editor.undo()
    assert view.document.native.original == original
    view.editor.redo()
    assert view.document.native.original == edited


def test_native_review_preserves_blank_paragraphs_and_accepts_associations(native_window, tmp_path):
    window = native_window
    window.import_zip(0, source_zip(tmp_path))
    view = window.current
    view.receive('Hello\n\nworld.\n', [])
    proposal = view.document.native.incoming
    assert view.diff_view.has_changes
    buttons = [b for b in view.diff_view.findChildren(QPushButton) if 'Accept' in b.text()]
    assert buttons
    while view.diff_view.has_changes:
        next(b for b in view.diff_view.findChildren(QPushButton) if 'Accept' in b.text()).click()
    assert view.document.original == 'Hello\n\nworld.\n'
    assert view.document.native.original == view.document.native.incoming
    assert view.document.native.original.text == proposal.text
    assert view.document.warnings


def test_native_generated_layout_never_enters_text(native_window, tmp_path):
    window = native_window
    window.import_zip(0, source_zip(tmp_path))
    before = window.current.document.native.original
    assert not hasattr(window, "manual_btn")
    assert window.current.document.native.original == before
    assert not window.current.document.original.startswith('          1')


def test_partial_accept_keeps_destination_passage_associations(native_window, tmp_path):
    from app.src.casecat.anchors import AnchoredSpan, Revision
    source = tmp_path/'example.zip'
    source.write_bytes(zip_bytes(job_files(words=('First.\n', 'Middle.\n', 'Last.\n'))))
    native_window.import_zip(0, source)
    view = native_window.current
    view.receive('Replacement.\nMiddle.\nEnd.\n', [])
    spans = tuple(AnchoredSpan(s.identity, (2,) if s.content == 'Replacement' else s.stroke_refs,
                              s.audio, s.content, s.formatting) for s in view.document.native.incoming.spans)
    view.document.native.incoming = Revision(spans)
    view.refresh()
    view.review(0, True)
    assert view.document.original == 'Replacement.\nMiddle.\nLast.\n'
    assert view.document.incoming == 'Replacement.\nMiddle.\nEnd.\n'
    accepted = next(s for s in view.document.native.original.spans if s.content == 'Replacement')
    assert accepted.stroke_refs == (0,)


def test_speaker_typing_propagates_and_undo_restores_fields(native_window, tmp_path):
    from app.tests.test_native_fields import field_files
    files = field_files()
    del files['jobs/example.wav']
    source = tmp_path/'fields.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    before = view.document.native.original
    cursor = view.editor.textCursor()
    start = before.text.index('OLD')
    cursor.setPosition(start)
    cursor.setPosition(start + 3, QTextCursor.KeepAnchor)
    cursor.insertText('NEW')
    after = view.document.native.original
    assert after.text.count('MS. NEW') == 2
    assert view.editor.toPlainText() == after.text == view.document.original
    assert view.document.native.incoming == after
    view.editor.undo()
    assert view.document.native.original == before
    assert view.editor.toPlainText() == before.text
    view.editor.redo()
    assert view.document.native.original == after
    assert view.editor.toPlainText() == after.text


def test_question_deletion_updates_display_and_undo(native_window, tmp_path):
    from app.tests.test_native_fields import field_files
    files = field_files()
    del files['jobs/example.wav']
    source = tmp_path/'fields.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    before = view.document.native.original
    cursor = view.editor.textCursor()
    cursor.setPosition(before.text.index('Q    '))
    cursor.deleteChar()
    assert '\nQuestion?' in view.editor.toPlainText()
    assert view.editor.toPlainText() == view.document.original
    view.editor.undo()
    assert view.document.native.original == before


def test_field_dialog_and_partial_review_preserve_linked_fields(native_window, tmp_path, monkeypatch):
    from app.tests.test_native_fields import field_files
    from app.src.native_dialogs import FillFieldDialog
    files = field_files()
    del files['jobs/example.wav']
    source = tmp_path/'fields.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    cursor = view.editor.textCursor()
    cursor.setPosition(view.document.original.index('OLD'))
    view.editor.setTextCursor(cursor)
    monkeypatch.setattr(FillFieldDialog, 'get_value', lambda *args, **kwargs: ('MS. EDITED', True))
    view.editor.edit_native_field()
    assert view.document.original.count('MS. EDITED') == 2
    view.editor.undo()
    assert view.document.original.count('MS. OLD') == 2
    view.receive(view.document.original.replace('MS. OLD', 'MS. NEW', 1), [])
    view.review(0, True)
    assert view.document.original.count('MS. NEW') == 2
    assert view.document.native.original == view.document.native.incoming


def test_field_lookup_after_length_changing_undo_and_rejected_input(native_window, tmp_path, monkeypatch):
    from app.tests.test_native_fields import field_files
    from PySide6.QtWidgets import QInputDialog
    files = field_files()
    del files['jobs/example.wav']
    source = tmp_path/'fields.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    cursor = view.editor.textCursor()
    start = view.document.original.index('OLD')
    cursor.setPosition(start)
    cursor.setPosition(start+3, QTextCursor.KeepAnchor)
    cursor.insertText('MUCH LONGER')
    view.editor.undo()
    assert view.editor._native_source[1].revision == view.document.native.original
    cursor = view.editor.textCursor()
    cursor.setPosition(start)
    cursor.insertText('\U0001f600')
    assert '\U0001f600' not in view.document.original
    assert view.document.original == view.editor.toPlainText()


def test_field_dialog_changes_definition_even_when_display_case_matches(native_window, tmp_path, monkeypatch):
    from app.tests.test_native_fields import field_files
    from app.src.native_dialogs import FillFieldDialog
    files = field_files('john doe')
    del files['jobs/example.wav']
    source = tmp_path/'fields.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    before = view.document.native.original
    cursor = view.editor.textCursor()
    cursor.setPosition(before.text.index('John doe'))
    view.editor.setTextCursor(cursor)
    monkeypatch.setattr(FillFieldDialog, 'get_value', lambda *args, **kwargs: ('John doe', True))
    view.editor.edit_native_field()
    assert view.document.original.startswith('BY John doe:')
    assert all(e.value == 'John doe' for e in view.document.native.original.elements if e.kind == 'field')
    view.editor.undo()
    assert view.document.native.original == before


def test_editor_inserts_field_and_question_as_native_elements(native_window, tmp_path, monkeypatch):
    from app.tests.test_native_fields import field_files
    files = field_files()
    del files['jobs/example.wav']
    source = tmp_path/'fields.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    cursor = view.editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    view.editor.setTextCursor(cursor)
    view.editor.apply_native_revision(view.document.native.original.define_field('PARITY NAME', 'MS. ADDED'))
    view.editor.insert_named_field('PARITY NAME')
    assert view.document.original.endswith('MS. ADDED')
    assert view.document.native.original.elements[-1].name == 'PARITY NAME'
    view.editor.insert_native_symbol('Q')
    assert view.document.original.endswith('MS. ADDED\n     Q    ')
    target = tmp_path/'added.zip'
    view.document.export_casecat(target)
    view.editor.undo()
    assert view.document.original.endswith('MS. ADDED')


def test_cut_and_paste_preserves_native_field_identity(native_window, tmp_path):
    from app.tests.test_native_fields import field_files, FIELD, native_stream
    from app.src.casecat import archive, codec
    from PySide6.QtWidgets import QApplication
    files = field_files()
    del files['jobs/example.wav']
    source = tmp_path/'fields.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    before = view.document.native.original
    field = next(e for e in before.elements if e.kind == 'field')
    cursor = view.editor.textCursor()
    cursor.setPosition(field.start)
    cursor.setPosition(field.end, QTextCursor.KeepAnchor)
    view.editor.setTextCursor(cursor)
    view.editor.cut()
    from app.src.casecat.clipboard import MIME_TYPE
    assert QApplication.clipboard().mimeData().hasFormat(MIME_TYPE)
    assert b'EZ SPEAKER 01' in bytes(QApplication.clipboard().mimeData().data(MIME_TYPE))
    assert len([e for e in view.document.native.original.elements if e.kind == 'field']) == 1
    cursor = view.editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    view.editor.setTextCursor(cursor)
    view.editor.paste()
    pasted = view.document.native.original
    assert len([e for e in pasted.elements if e.kind == 'field']) == 2
    assert pasted.elements[-1].name == field.name
    view.editor.undo()
    assert len([e for e in view.document.native.original.elements if e.kind == 'field']) == 1
    view.editor.redo()
    target = tmp_path/'pasted.zip'
    view.document.export_casecat(target)
    restored = codec.load_job(archive.inspect_archive(target), 'jobs/example')
    assert restored.text == pasted.text
    assert native_stream(restored).count(FIELD) == 2
    QApplication.clipboard().clear()


def test_replacing_byline_with_byline_keeps_one_native_symbol(native_window, tmp_path):
    from app.tests.test_native_fields import field_files
    files = field_files()
    del files['jobs/example.wav']
    source = tmp_path/'fields.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    cursor = view.editor.textCursor()
    cursor.setPosition(1)
    view.editor.setTextCursor(cursor)
    view.editor.insert_native_symbol('By-line')
    assert len([e for e in view.document.native.original.elements if e.name == 'By-line']) == 1
    view.document.export_casecat(tmp_path/'byline.zip')


def test_native_equal_review_is_read_only_and_incoming_remains_editable(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    baseline = view.document.native.original
    view.receive('Hello changed.\n', [])
    assert view.editor.isReadOnly()
    view.set_busy(True)
    view.set_busy(False)
    assert view.editor.isReadOnly()
    view.toggle_view()
    assert view.incoming_editor.isReadOnly()
    assert view.document.native.original == baseline


def test_programmatic_whole_text_replacement_inherits_the_affected_passage(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path))
    view = native_window.current
    view.editor.setPlainText('Rewritten')
    assert view.document.original == 'Rewritten'
    written = next(s for s in view.document.native.original.spans if s.content == 'Rewritten')
    assert written.stroke_refs == (0, 1)

def test_completed_review_can_be_edited_and_saved(native_window,tmp_path):
    from app.src.casecat.project import project_bytes
    native_window.import_zip(0,source_zip(tmp_path))
    view=native_window.current
    view.receive('Changed words.\n',[])
    while view.diff_view.changes:
        view.review(0,False)
    view.editor.selectAll()
    view.editor.textCursor().insertText('Short.')
    assert view.document.native.review is None
    project_bytes(view.document.native,{})

def test_native_speaker_override_undo_and_project_reopen(native_window,tmp_path):
    from app.tests.test_native_fields import field_files
    from app.src.casecat.project import project_bytes,read_project
    path=tmp_path/'speakers.zip'
    files=field_files();del files['jobs/example.wav']
    path.write_bytes(zip_bytes(files));native_window.import_zip(0,path)
    view=native_window.current
    before=view.document.native.original
    view.receive(before.text.replace('MS. OLD','SPEAKER 3'),[])
    assert not view.diff_view.changes
    assert not view.editor.isReadOnly()
    view.change_speaker_mapping('SPEAKER 3',None)
    proposed=view.document.native.incoming
    assert 'SPEAKER 3' in proposed.text
    view.undo_review();assert view.document.native.incoming==before
    view.redo_review();assert view.document.native.incoming==proposed
    state,_=read_project(project_bytes(view.document.native,{}))
    assert state.review==view.document.native.review
    while view.diff_view.changes:view.review(0,False)
    view.editor.selectAll();view.editor.textCursor().insertText('Short.')
    assert view.document.native.review is None
    project_bytes(view.document.native,{})


def test_automatic_review_batch_is_native_undoable_and_persisted(native_window, tmp_path):
    from app.src.casecat.project import project_bytes, read_project
    from app.src.casecat import archive, codec
    from app.tests.test_native_structure import container_files
    files = container_files()
    del files['jobs/example.wav']
    source = tmp_path/'automatic-source.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    before = view.document.native.original
    incoming = before.text.replace('Hello', 'HELLO').replace('.', '?')
    assert incoming != before.text
    view.receive(incoming, [])
    assert view.document.original == incoming
    assert 'automatically accepted' in view.document.status
    assert not view.diff_view.changes
    after = view.document.native.original
    assert view.document.native.review['automatic_changes']
    view.undo_review()
    assert view.document.native.original == before
    assert view.diff_view.changes
    view.redo_review()
    assert view.document.native.original == after
    restored, _ = read_project(project_bytes(view.document.native, {}))
    assert restored.original == after
    assert restored.review == view.document.native.review
    view.document.export_casecat(tmp_path/'automatic.zip')
    loaded = codec.load_job(archive.inspect_archive(tmp_path/'automatic.zip'), view.document.native.job.key)
    assert loaded.text == after.text
    assert loaded.notes_bytes == view.document.native.job.notes_bytes


def test_off_record_batch_undo_reopen_and_native_export(native_window, tmp_path):
    import re
    from app.tests.test_off_record import ORIGINAL, INCOMING, NOTE
    from app.tests.test_native_fields import field_files
    from app.src.casecat.project import project_bytes, read_project
    from app.src.casecat import archive, codec
    from app.src.suggestion_filter import auto_accept
    files = field_files('MS. SIEMENS')
    del files['jobs/example.wav']
    source = tmp_path/'off-record.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    state = view.document.native
    original = state.original.revise(ORIGINAL)
    # Give both surviving SIEMENS occurrences real native field identities.
    for start in reversed([m.start() for m in re.finditer('MS. SIEMENS', ORIGINAL)]):
        original = original._replace(start, start+len('MS. SIEMENS'), '')
        original = original.insert_field(start, 'EZ SPEAKER 01', 'MS. SIEMENS')
    state.original = state.incoming = original
    view.refresh()
    view.receive(INCOMING, [])
    assert 'review the transcripts' not in state.incoming.text
    assert NOTE in state.incoming.text
    assert state.original == original
    assert len([e for e in state.incoming.elements if e.kind == 'field']) == 2
    filtered = state.incoming
    view.undo_review()
    assert 'review the transcripts' in state.incoming.text
    restored, _ = read_project(project_bytes(state, {}))
    assert auto_accept(restored) == []
    assert 'review the transcripts' in restored.incoming.text
    view.redo_review()
    assert state.incoming == filtered
    restored, _ = read_project(project_bytes(state, {}))
    assert restored.review == state.review
    assert restored.incoming == filtered
    for _ in range(50):
        if not view.diff_view.changes:
            break
        view.review(0, True)
    assert not view.diff_view.changes
    view.document.export_casecat(tmp_path/'off-record-export.zip')
    loaded = codec.load_job(archive.inspect_archive(tmp_path/'off-record-export.zip'), state.job.key)
    assert loaded.text == state.original.text
    assert loaded.notes_bytes == state.job.notes_bytes


def test_reopening_unfiltered_review_keeps_incoming_native_fields(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    document = native_window.current.document
    incoming = document.native.original.insert_field(0, 'CUSTOM', 'Named speaker')
    document.native.incoming = incoming
    document.native.review = None
    reopened = DocumentView(document)
    assert document.native.incoming == incoming
    reopened.close()
