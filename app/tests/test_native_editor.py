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


def test_native_import_uses_the_original_plain_editor(native_window, tmp_path):
    from PySide6.QtWidgets import QPlainTextEdit
    from app.src.diff_view import LineNumberedEditor
    from PySide6.QtGui import QFont
    legacy_font = QFont("Courier New", 12)
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    for editor in (view.editor, view.incoming_editor):
        assert isinstance(editor, LineNumberedEditor)
        assert isinstance(editor, QPlainTextEdit)
        assert editor.lineWrapMode() == QPlainTextEdit.NoWrap
        assert editor.font().family() == legacy_font.family()
        assert not hasattr(editor, '_page_width')
        assert editor.toPlainText() == view.document.native.original.text


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
    assert view.document.native.original == proposal
    assert view.document.warnings


def test_native_generated_layout_never_enters_text(native_window, tmp_path):
    window = native_window
    window.import_zip(0, source_zip(tmp_path))
    before = window.current.document.native.original
    assert not hasattr(window, "manual_btn")
    assert window.current.document.native.original == before
    assert not window.current.document.original.startswith('          1')


def test_partial_accept_uses_incoming_passage_associations(native_window, tmp_path):
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
    assert accepted.stroke_refs == (2,)


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
