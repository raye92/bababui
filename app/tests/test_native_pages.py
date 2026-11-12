import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QApplication

from app.src import native_editor as editor
from app.src.casecat.archive import inspect_archive
from app.src.casecat.codec import load_job
from app.tests.test_native_rendering import native_stream


def paged_editor():
    app = QApplication.instance() or QApplication([])
    assert hasattr(editor, 'NativeTranscriptEditor'), 'Native page view is not implemented.'
    view = editor.NativeTranscriptEditor(QFont('Courier New', 12))
    view.resize(1000, 700)
    view.show()
    return app, view


def test_native_page_numbers_are_decoration_and_wrapping_does_not_change_content():
    app, view = paged_editor()
    text = '\n'.join('     Q    ' + 'Word ' * 15 for _ in range(28))
    view.setPlainText(text)
    app.processEvents()
    lines = view.page_lines()
    assert len(lines) == 56
    assert [(line.page, line.number) for line in lines][24:27] == [(1,25), (2,1), (2,2)]
    assert view.toPlainText() == text
    assert view.document().pageCount() == 3
    assert not view.document().isUndoAvailable()
    view.close()


def test_inserted_paragraph_inherits_native_continuation_indent():
    import struct
    from app.tests.test_native_casecat import job_files, zip_bytes
    from app.tests.test_native_layout import layout_bytes
    app, view = paged_editor()
    files = job_files(words=('\x16\x01\x00First line.',))
    native = bytearray(files['jobs/example.sgngl'])
    payload = bytearray(layout_bytes())
    struct.pack_into('<H', payload, 1024 + 176, 2880)
    struct.pack_into('<II', native, 540, len(native), len(payload))
    struct.pack_into('<I', native, 624, 1)
    files['jobs/example.sgngl'] = bytes(native + payload)
    bundle = inspect_archive(zip_bytes(files))
    job = load_job(bundle, bundle.jobs[0])
    job = job.with_revision(job.revision.replace(6, 6, '\n'))
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    assert view.document().firstBlock().next().blockFormat().textIndent() > 50
    assert view.toPlainText() == 'First \nline.'
    view.close()


def test_native_page_edit_and_undo_use_logical_offsets_across_wrapped_lines():
    app, view = paged_editor()
    text = '     Q    ' + 'Word ' * 30
    view.setPlainText(text)
    app.processEvents()
    cursor = view.textCursor()
    cursor.setPosition(50)
    cursor.setPosition(80, QTextCursor.KeepAnchor)
    cursor.insertText('Café\n')
    assert view.toPlainText() == text[:50] + 'Café\n' + text[80:]
    view.undo()
    assert view.toPlainText() == text
    view.redo()
    assert view.toPlainText() == text[:50] + 'Café\n' + text[80:]
    view.close()


def test_hard_space_is_preserved_for_wrapping_without_changing_plain_text():
    app, view = paged_editor()
    assert hasattr(view, 'set_native_source'), 'Native presentation associations are not implemented.'
    from app.tests.test_native_casecat import job_files, zip_bytes
    files = job_files(words=('Word ' * 10 + 'Mr.\x01Smith',))
    bundle = inspect_archive(zip_bytes(files))
    job = load_job(bundle, bundle.jobs[0])
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    app.processEvents()
    assert '\u00a0' in view.document().toRawText()
    assert view.toPlainText() == job.text
    lines = view.page_lines()
    assert lines[1].text == 'Mr.\u00a0Smith'
    view.close()


def test_conflict_generated_spaces_do_not_create_native_word_breaks():
    from app.tests.test_native_casecat import job_files, zip_bytes
    app, view = paged_editor()
    files = job_files(words=('A \x02one two\x02three\x03 end.',))
    bundle = inspect_archive(zip_bytes(files))
    job = load_job(bundle, bundle.jobs[0])
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    assert '^\u00a0one two\u00a0^\u00a0three' in view.document().toRawText()
    assert view.toPlainText() == job.text
    view.close()


def test_centered_paragraph_does_not_hide_the_preceding_blank_line():
    from app.tests.test_native_casecat import job_files, zip_bytes
    app, view = paged_editor()
    files = job_files(words=('First.\x16\x08\x00\x16\x07\x00(Centered.)',))
    bundle = inspect_archive(zip_bytes(files))
    job = load_job(bundle, bundle.jobs[0])
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    app.processEvents()
    assert [line.text.strip() for line in view.page_lines()] == ['First.', '', '(Centered.)']
    assert view.toPlainText() == job.text
    view.close()


def test_native_view_uses_embedded_layout_and_paragraph_indent():
    import struct
    from app.tests.test_native_casecat import job_files, zip_bytes
    from app.tests.test_native_layout import layout_bytes
    app, view = paged_editor()
    files = job_files(words=('',))
    native = bytearray(files['jobs/example.sgngl'])
    native += b'\x16\x01\x00\x15\x03\x03\x00\x00\x00\x0a\x40\x0bFirst line.'
    struct.pack_into('<I', native, 536, len(native) - 1024)
    payload = layout_bytes(lines=28)
    struct.pack_into('<II', native, 540, len(native), len(payload))
    struct.pack_into('<I', native, 624, 1)
    native += payload
    files['jobs/example.sgngl'] = bytes(native)
    bundle = inspect_archive(zip_bytes(files))
    job = load_job(bundle, bundle.jobs[0])
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    app.processEvents()
    assert view.lines_per_page == 28
    assert view.font().family() == 'Courier New'
    assert view.document().firstBlock().blockFormat().textIndent() > 50
    assert view.toPlainText() == 'First line.'
    view.close()


def test_live_paragraph_indent_and_undo_match_reopened_native_revision(tmp_path, monkeypatch):
    import struct
    from app.src import documents
    from app.src.document_view import DocumentView
    from app.tests.test_native_casecat import job_files, zip_bytes
    from app.tests.test_native_layout import layout_bytes
    app = QApplication.instance() or QApplication([])
    files = job_files(words=('\x16\x01\x00First line.',))
    native = bytearray(files['jobs/example.sgngl'])
    payload = bytearray(layout_bytes())
    struct.pack_into('<H', payload, 1024 + 176, 2880)
    struct.pack_into('<II', native, 540, len(native), len(payload))
    struct.pack_into('<I', native, 624, 1)
    files['jobs/example.sgngl'] = bytes(native + payload)
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path)
    doc = documents.import_casecat(inspect_archive(zip_bytes(files)))
    view = DocumentView(doc)
    original = doc.native.original
    cursor = view.editor.textCursor()
    cursor.setPosition(6)
    view.editor.setTextCursor(cursor)
    cursor.insertText('\n')
    revised = doc.native.original
    assert view.editor.document().pageSize().height() == view.editor._page_height
    assert view.editor.document().firstBlock().next().blockFormat().textIndent() == 54
    assert view.editor.textCursor().position() == 7
    view.editor.undo()
    assert doc.native.original == original
    view.editor.redo()
    assert doc.native.original == revised
    assert view.editor.document().firstBlock().next().blockFormat().textIndent() == 54
    view.incoming_editor.setPlainText('First \nnew line.')
    assert view.incoming_editor.document().firstBlock().next().blockFormat().textIndent() == 54
    assert not view.incoming_editor.document().isUndoAvailable()
    view.close()


def test_paged_review_selection_and_independent_acceptance(tmp_path, monkeypatch):
    from app.tests.test_native_projects import native_doc
    from app.src.document_view import DocumentView
    from app.src.casecat.anchors import utf16_index
    app = QApplication.instance() or QApplication([])
    doc, _ = native_doc(tmp_path, monkeypatch)
    doc.set_text('original', 'The red car is large.')
    doc.set_text('incoming', doc.original, revision=doc.native.original)
    view = DocumentView(doc)
    view.resize(1200, 800)
    view.show()
    view.receive('The blue car is small.', [])
    app.processEvents()
    assert view.active_view() is view.editor
    assert view.diff_view.isVisible()
    assert len(view.diff_view.changes) == 2
    view.diff_view.select(1)
    assert utf16_index(doc.original, view.editor.textCursor().position()) == doc.original.index('large')
    assert view.editor._review_selections
    view.review(1, True)
    assert doc.original == 'The red car is small.'
    view.undo_review()
    assert doc.original == 'The red car is large.'
    view.review(0, False)
    assert len(view.diff_view.changes) == 1
    view.review(0, True)
    assert not view.diff_view.isVisible()
    assert doc.original == 'The red car is small.'
    view.close()


def test_page_click_selects_change_and_insertion_keeps_text_unchanged(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from app.tests.test_native_projects import native_doc
    from app.src.document_view import DocumentView
    app = QApplication.instance() or QApplication([])
    doc, _ = native_doc(tmp_path, monkeypatch)
    doc.wav_path = None
    doc.set_text('original', 'The red car is large.')
    doc.set_text('incoming', doc.original, revision=doc.native.original)
    view = DocumentView(doc)
    view.resize(1200, 800)
    view.show()
    view.receive('The blue car is very large.', [])
    app.processEvents()
    assert len(view.diff_view.changes) == 2
    assert len(view.editor._review_insertions) == 1
    position, index = view.editor._review_insertions[0]
    before = doc.native.original, doc.native.incoming
    cursor = view.editor.textCursor()
    cursor.setPosition(position)
    QTest.mouseClick(view.editor.viewport(), Qt.LeftButton, pos=view.editor.cursorRect(cursor).center())
    assert view.diff_view.current == index
    assert (doc.native.original, doc.native.incoming) == before
    view.review(index, True)
    assert doc.original == 'The red car is very large.'
    view.close()
