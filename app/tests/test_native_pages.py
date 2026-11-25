import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtTest import QTest
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


@pytest.mark.parametrize('width, cancel', [(600, 'click'), (1450, 'escape')])
def test_middle_click_autoscroll_tracks_pointer_and_stops(width, cancel):
    from app.src.page_view import PageView

    app = QApplication.instance() or QApplication([])
    editor_view = editor.NativeTranscriptEditor(QFont('Courier New', 12))
    editor_view.setPlainText('\n'.join(f'Transcript line {i}.' for i in range(120)))
    page = PageView(editor_view)
    page.resize(width, 550)
    page.show()
    page.activateWindow()
    app.processEvents()
    try:
        bar = editor_view.verticalScrollBar()
        midpoint = bar.maximum() // 2
        assert midpoint > 0
        bar.setValue(midpoint)
        viewport = page.viewport()
        anchor = viewport.rect().center()
        QTest.mouseMove(viewport, anchor)
        QTest.mouseClick(viewport, Qt.MiddleButton, pos=anchor)

        QTest.mouseMove(viewport, anchor + QPoint(0, 6))
        QTest.qWait(120)
        assert bar.value() == midpoint

        QTest.mouseMove(viewport, anchor + QPoint(0, 90))
        QTest.qWait(120)
        assert bar.value() > midpoint
        down = bar.value()
        QTest.mouseMove(viewport, anchor - QPoint(0, 90))
        QTest.qWait(120)
        assert bar.value() < down

        if cancel == 'click':
            QTest.mouseClick(viewport, Qt.MiddleButton, pos=anchor)
        else:
            QTest.keyClick(page, Qt.Key_Escape)
        stopped = bar.value()
        QTest.mouseMove(viewport, anchor + QPoint(0, 90))
        QTest.qWait(120)
        assert bar.value() == stopped
    finally:
        page.close()


def test_review_splitter_keeps_paged_editor_visible_when_dragged_left():
    from app.src.casecat.project import NativeState
    from app.src.document_view import DocumentView
    from app.src.documents import Document

    app = QApplication.instance() or QApplication([])
    bundle = review_layout_bundle(('Cover sheet.\n\x0c\x16\x07\x00', 'INDEX\nFirst entry.\nSecond entry.'))
    state = NativeState.load(bundle, bundle.jobs[0])
    state.incoming = state.original.revise(state.original.text.replace('Cover sheet', 'Cover information'))
    view = DocumentView(Document(native=state))
    view.resize(720, 800)
    view.show()
    app.processEvents()
    try:
        splitter = view.review_splitter
        splitter.moveSplitter(0, 1)
        app.processEvents()
        assert splitter.sizes()[0] >= 400
        assert view.inline_page.viewport().width() >= 400
        assert view.inline_page.sceneRect().height() < 3000

        splitter.moveSplitter(445, 1)
        splitter.moveSplitter(splitter.width(), 1)
        app.processEvents()
        assert splitter.sizes()[1] == 0
        assert view.inline_page.transform().m11() > 0.5
    finally:
        view.close()


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


def review_layout_bundle(words):
    import struct
    from app.tests.test_native_casecat import job_files, zip_bytes
    from app.tests.test_native_layout import layout_bytes

    files = job_files(words, audio=False)
    native = bytearray(files['jobs/example.sgngl'])
    layout = bytearray(layout_bytes())
    paragraph = layout[1024:1536]
    question = bytearray(paragraph)
    struct.pack_into('<H', question, 174, 3599)
    colloquy = bytearray(paragraph)
    struct.pack_into('<H', colloquy, 174, 2879)
    centered = bytearray(paragraph)
    struct.pack_into('<H', centered, 178, 2)
    layout[1536:1536] = question * 2 + colloquy + paragraph * 2 + centered
    struct.pack_into('<I', layout, 4, 7)
    struct.pack_into('<II', native, 540, len(native), len(layout))
    struct.pack_into('<I', native, 624, 1)
    files['jobs/example.sgngl'] = bytes(native + layout)
    return inspect_archive(zip_bytes(files))


def test_accept_all_preserves_index_page_break_and_centering():
    from app.src.documents import import_casecat
    from app.src.document_view import DocumentView

    app = QApplication.instance() or QApplication([])
    bundle = review_layout_bundle(('Cover sheet.\n\x0c\x16\x07\x00', 'INDEX\nFirst entry.\nSecond entry.'))
    doc = import_casecat(bundle)
    view = DocumentView(doc)
    view.receive(doc.original.replace('Cover sheet', 'Cover information'), [])

    view.review(None, True, background=True)
    assert view._review_worker.wait(5000)
    app.processEvents()

    assert not view.review_model.edits
    assert [(line.page, line.number) for line in view.editor.page_lines()] == [(1, 1), (1, 2), (2, 1), (2, 2), (2, 3)]
    assert view.editor.document().findBlockByNumber(2).blockFormat().alignment() == Qt.AlignHCenter
    view.undo_review()
    assert [(line.page, line.number) for line in view.editor.page_lines()][2] == (2, 1)
    inline_heading = next(row for row in view.inline_editor.rows if row.text == 'INDEX')
    native_heading = view.editor.document().findBlockByNumber(2).layout()
    native_x = native_heading.position().x() + native_heading.lineAt(0).cursorToX(0)[0]
    assert inline_heading.x == native_x
    assert view.review_model.edits
    view.close()


def test_accept_all_formats_inserted_turns_in_a_saved_proposal():
    from PySide6.QtGui import QFontMetricsF
    from app.src.documents import import_casecat
    from app.src.document_view import DocumentView

    app = QApplication.instance() or QApplication([])
    bundle = review_layout_bundle(('\x16\x04\x00THE WITNESS:  Okay.', '\x16\x02\x00What happened next?'))
    doc = import_casecat(bundle)
    proposal = doc.original.replace('\n', '\n     MS. COUNSEL:  Please continue.\nQ    Where were you?\n')
    doc.set_text('incoming', proposal)
    view = DocumentView(doc)

    view.review(None, True, background=True)
    assert view._review_worker.wait(5000)
    app.processEvents()

    assert doc.original == proposal
    assert not view.review_model.edits
    native = view.editor.document()
    indent = lambda i: native.findBlockByNumber(i).blockFormat().textIndent()
    assert indent(0) == indent(1)
    assert indent(2) - indent(3) == pytest.approx(QFontMetricsF(view.editor.font()).horizontalAdvance(' ' * 5))
    view.close()


@pytest.mark.parametrize('accept', [True, False], ids=['accept-in-original', 'reject-in-incoming'])
def test_bulk_review_keeps_the_visible_passage_after_reflow(tmp_path, monkeypatch, accept):
    from app.src.document_view import DocumentView
    from app.tests.test_native_projects import native_doc

    app = QApplication.instance() or QApplication([])
    doc, _ = native_doc(tmp_path, monkeypatch)
    doc.wav_path = None
    transcript = '\n'.join(f'Original transcript paragraph {i}.' for i in range(110))
    doc.set_text('original', transcript)
    doc.set_text('incoming', doc.original, revision=doc.native.original)
    view = DocumentView(doc)
    view.resize(1200, 800)
    view.show()
    inserted = '\n'.join(f'Additional testimony {i}.' for i in range(32))
    view.receive(inserted + '\n' + transcript, [])
    if not accept:
        view.toggle_view()
    app.processEvents()
    anchor = 'Original transcript paragraph 55.'
    editor = view.active_view()
    line = next(i for i, row in enumerate(editor.page_lines()) if row.text == anchor)
    editor.scroll_to_center_line(line)

    view.review(None, accept, background=True)
    assert view._review_worker.wait(5000)
    app.processEvents()
    app.processEvents()
    assert not view.review_model.edits
    editor = view.active_view()
    assert editor.page_lines()[editor.center_line()].text == anchor

    view.undo_review()
    app.processEvents()
    editor = view.active_view()
    assert editor.page_lines()[editor.center_line()].text == anchor
    assert view.review_model.edits
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


def test_compound_byline_uses_its_own_native_indent():
    import struct
    from app.tests.test_native_casecat import job_files, zip_bytes
    from app.tests.test_native_layout import layout_bytes
    app, view = paged_editor()
    files = job_files(words=('\x16\x05\x00\x11\x06\x02\x00\x00\x00BY COUNSEL:',))
    native = bytearray(files['jobs/example.sgngl'])
    payload = bytearray(layout_bytes(first=3600))
    paragraph = payload[1024:1536]
    byline = bytearray(paragraph)
    struct.pack_into('<H', byline, 174, 2160)
    payload[1536:1536] = paragraph * 3 + byline
    struct.pack_into('<I', payload, 4, 5)
    struct.pack_into('<II', native, 540, len(native), len(payload))
    struct.pack_into('<I', native, 624, 1)
    files['jobs/example.sgngl'] = bytes(native + payload)
    bundle = inspect_archive(zip_bytes(files))
    job = load_job(bundle, bundle.jobs[0])
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    assert view.document().firstBlock().blockFormat().textIndent() == 0
    view.close()


def test_double_spacing_starts_at_top_margin_instead_of_lowering_glyphs():
    app, view = paged_editor()
    view.setPlainText('First\nSecond')
    lines = view.page_lines()
    # Qt rounds root-frame margins to physical pixels.
    assert abs(lines[0].y - view._top) < 0.5
    assert abs(lines[1].y - lines[0].y - view._line_height) < 0.02
    view.close()


def test_native_courier_pitch_preserves_56_columns_without_integer_rounding():
    import struct
    from pathlib import Path
    import pytest
    from PySide6.QtGui import QFontMetricsF, QFontDatabase
    from app.tests.test_native_casecat import job_files, zip_bytes
    from app.tests.test_native_layout import layout_bytes
    app, view = paged_editor()
    font_file = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/cour.ttf'
    if font_file.exists():
        QFontDatabase.addApplicationFont(str(font_file))
    if 'Courier New' not in QFontDatabase.families():
        pytest.skip('The native Courier New font is unavailable.')
    files = job_files(words=('a' * 51 + ' truck',))
    native = bytearray(files['jobs/example.sgngl'])
    payload = layout_bytes()
    struct.pack_into('<II', native, 540, len(native), len(payload))
    struct.pack_into('<I', native, 624, 1)
    files['jobs/example.sgngl'] = bytes(native + payload)
    bundle = inspect_archive(zip_bytes(files))
    job = load_job(bundle, bundle.jobs[0])
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    # Measured native 12pt Courier pitch, at the editor's 1.5px/pt scale.
    assert abs(QFontMetricsF(view.font()).horizontalAdvance('0') - 10.86) < 0.02
    assert [line.text for line in view.page_lines()] == ['A' + 'a' * 50, 'truck']
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
    files = job_files(words=('A \x11\x09\x00\x00\x00\x00\x02one two\x02three\x03 end.',))
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
    assert view.document().firstBlock().blockFormat().textIndent() == 54
    assert view.toPlainText() == 'First line.'
    revised = job.with_revision(job.revision.replace(0, 1, 'L'))
    view.set_native_source(bundle, revised)
    view.setPlainText(revised.text)
    assert view.document().firstBlock().blockFormat().textIndent() == 54
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


@pytest.mark.parametrize('action', ['type', 'paste', 'accept suggestion', 'type with preview fallback'])
def test_wording_edit_preserves_native_layout_in_large_stroke_group(tmp_path, action):
    import struct
    from PySide6.QtCore import QMimeData
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    from app.src.casecat.codec import u32
    from app.src.documents import import_casecat, open_document, save_document
    from app.src.document_view import DocumentView
    from app.tests.test_native_casecat import zip_bytes
    from app.tests.test_native_structure import container_files

    app = QApplication.instance() or QApplication([])
    # A source stroke can hold the entire front matter, including breaks and
    # per-paragraph formatting. One character edit must keep those controls.
    contents = '\x16\x01\x00' + 'Cover wording. ' * 110 + '\x0c\x16\x01\x00Index heading.\nIndex entry.'
    files = container_files((contents,))
    native = bytearray(files['jobs/example.sgngl'])
    struct.pack_into('<H', native, u32(native, 540) + 1024 + 174, 2880)
    files['jobs/example.sgngl'] = bytes(native)
    del files['jobs/example.wav']
    doc = import_casecat(inspect_archive(zip_bytes(files)))
    view = DocumentView(doc, disabled_auto_accept_rules={'trailing_whitespace'})
    source = doc.native.original

    def layout(view):
        editor = view.editor
        heading = editor.document().findBlockByNumber(1)
        line = next(line for line in editor.page_lines() if line.text == 'Index heading.')
        return heading.blockFormat().textIndent(), line.page, line.number

    expected = layout(view)
    assert expected[0] == 54 and expected[1] > 1 and expected[2] == 1
    replacement = 'Ω' if action == 'type with preview fallback' else 'B'
    edited_text = replacement + source.text[1:]
    if action == 'accept suggestion':
        view.receive(edited_text, [])
        button = next(button for button in view.diff_view.findChildren(QPushButton)
                      if button.text() == 'Accept')
        button.click()
        assert view._review_worker.wait(5000)
        app.processEvents()
        undo, redo = view.undo_review, view.redo_review
    else:
        cursor = view.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(1, QTextCursor.KeepAnchor)
        view.editor.setTextCursor(cursor)
        if action == 'paste':
            # A multi-part edit can span the entire stroke group.
            edited_text = edited_text[:-1] + '!'
            mime = QMimeData()
            mime.setText(edited_text)
            view.editor.selectAll()
            view.editor.insertFromMimeData(mime)
        elif action == 'type with preview fallback':
            cursor.insertText(replacement)  # Native export uses Windows-1252.
        else:
            QTest.keyClicks(view.editor, 'B')
        undo, redo = view.editor.undo, view.editor.redo
    revised = doc.native.original
    assert revised.text == edited_text
    assert layout(view) == expected

    undo()
    assert doc.native.original == source
    assert layout(view) == expected
    redo()
    assert doc.native.original == revised
    assert layout(view) == expected

    project = tmp_path / 'edited.bababui'
    save_document(doc, project)
    reopened = DocumentView(open_document(project))
    assert layout(reopened) == expected
    reopened.close()
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
    assert view.active_view() is view.inline_editor
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


def test_resize_preserves_page_breaks_and_positive_line_numbers():
    app, view = paged_editor()
    text = '\n'.join('     Q    ' + 'Word ' * 15 for _ in range(60))
    view.setPlainText(text)
    baseline = [(line.page, line.number, line.text) for line in view.page_lines()]
    for width, height in ((900, 650), (720, 900), (1250, 700), (1000, 700)):
        view.resize(width, height)
        app.processEvents()
        assert view.document().pageSize().height() == view._page_height
        lines = view.page_lines()
        assert [(line.page, line.number, line.text) for line in lines] == baseline
        assert all(1 <= line.number <= view.lines_per_page for line in lines)
        assert view.toPlainText() == text
        assert not view.document().isUndoAvailable()
    view.close()


def test_page_number_is_in_bottom_right_footer():
    app, view = paged_editor()
    view.setPlainText('First page.\n' * 60)
    for page in range(view.document().pageCount()):
        footer = view.page_number_rect(page)
        assert footer.top() >= (page + 1) * view._page_height - view._bottom
        assert footer.bottom() < (page + 1) * view._page_height
        assert footer.right() == view._page_width - view._right
        assert footer.left() > view._page_width / 2
    view.close()


def test_short_final_page_can_scroll_to_its_footer_after_resize():
    app, view = paged_editor()
    view.setPlainText('\n'.join('Transcript line.' for _ in range(28)))
    for height in (500, 800, 600):
        view.resize(1000, height)
        app.processEvents()
        footer = view.page_number_rect(view.document().pageCount() - 1)
        assert view.verticalScrollBar().maximum() + view.viewport().height() >= footer.bottom()
    view.close()


def test_short_page_scrollbar_settles_without_repeated_resize_events():
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtTest import QTest, QSignalSpy
    app = QApplication.instance() or QApplication([])
    font_file = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/cour.ttf'
    if font_file.exists():
        QFontDatabase.addApplicationFont(str(font_file))
    app, view = paged_editor()
    view.setPlainText('Short transcript.')
    view.resize(1050, 650)
    spy = QSignalSpy(view.verticalScrollBar().rangeChanged)
    QTest.qWait(20)
    assert spy.count() < 10
    assert view.verticalScrollBar().maximum() > 0
    view.close()


def test_formatter_defaults_center_heading_without_changing_stored_text():
    from PySide6.QtCore import Qt
    from app.tests.test_native_casecat import job_files, zip_bytes
    app, view = paged_editor()
    text = 'EXAMINATION\nBY SPEAKER 2:\n     Q    Please describe the records you reviewed before the examination.'
    bundle = inspect_archive(zip_bytes(job_files(words=(text,), audio=False)))
    job = load_job(bundle, bundle.jobs[0])
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    assert view.document().firstBlock().blockFormat().alignment() == Qt.AlignHCenter
    assert view.document().firstBlock().next().blockFormat().alignment() == Qt.AlignLeft
    assert view.columns == 56 and view.lines_per_page == 25
    assert view.toPlainText() == text
    view.close()


def test_embedded_page_layout_survives_resize_and_review(tmp_path, monkeypatch):
    import struct
    from app.src import documents
    from app.src.document_view import DocumentView
    from app.tests.test_native_casecat import job_files, zip_bytes
    from app.tests.test_native_layout import layout_bytes
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    files = job_files(words=('First long paragraph with repeated words. ' * 250,), audio=False)
    native = bytearray(files['jobs/example.sgngl'])
    payload = layout_bytes(lines=28)
    struct.pack_into('<II', native, 540, len(native), len(payload))
    struct.pack_into('<I', native, 624, 1)
    files['jobs/example.sgngl'] = bytes(native) + payload
    doc = documents.import_casecat(inspect_archive(zip_bytes(files)))
    view = DocumentView(doc)
    view.resize(1100, 800)
    view.show()
    view.receive(doc.original.replace('First', 'Second', 1), [])
    original = doc.native.original
    for width in (900, 1300, 1100):
        view.resize(width, 700)
        view.review_splitter.setSizes([width-300, 300])
        app.processEvents()
        for ed in (view.editor, view.incoming_editor):
            assert ed.document().pageSize().height() == ed._page_height
            assert all(1 <= line.number <= 28 for line in ed.page_lines())
        assert doc.native.original == original
    view.close()

def test_hyphens_do_not_create_native_wrap_points_or_enter_clipboard():
    app,view=paged_editor()
    text='     Q    '+('word '*8)+'handyman-type work.'
    view.setPlainText(text)
    app.processEvents()
    assert all(not p.text.endswith('handyman-') for p in view.page_lines())
    assert view.toPlainText()==text
    view.selectAll()
    assert view.createMimeDataFromSelection().text()==text
    assert len(view.document().toRawText())==len(text)
    view.close()
