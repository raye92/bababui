import os
from pathlib import Path
import sys
from time import monotonic
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton
from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtGui import QDropEvent, QFontDatabase, QFont
from PySide6.QtTest import QTest
import pytest
import main


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if os.name == 'nt':
        for font in ('segoeui.ttf', 'cour.ttf'):
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
        app.setFont(QFont('Segoe UI', 9))
    w = main.TranscriptEditor(session_path=tmp_path/'session.json', legacy_dir=tmp_path)
    w.show()
    app.processEvents()
    from app.src import documents
    from app.tests.test_native_casecat import zip_bytes, job_files
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    source = tmp_path/'test.zip'
    source.write_bytes(zip_bytes(job_files(audio=False)))
    w.import_zip(0, source)
    yield w
    for view in w.views():
        if view.document.native:
            view.set_busy(False)
    w.close()


def test_toolbar_tabs_shortcuts_and_dirty_dot(window):
    assert not window.toolbar.isMovable() and not window.toolbar.isFloatable()
    assert window.tabs.count() == 1 and window.current.document.dirty
    assert '●' in window.tabs.tabText(0)
    assert not window.tabs.tabBar().is_empty(0)
    QTest.keyClick(window, Qt.Key_T, Qt.ControlModifier)
    assert window.tabs.count() == 2
    assert window.file_btn.text() == 'File'


def test_import_screen_and_no_manual_menu(window):
    window.new_tab()
    assert window.current.active_editor() is None
    assert not hasattr(window.current, 'editor')
    assert not hasattr(window, 'manual_btn')
    assert not window.file_actions['Save'].isEnabled()


def test_click_and_drop_tab_zip(window, tmp_path, monkeypatch):
    from app.tests.test_native_casecat import zip_bytes
    from app.src import documents
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    source = tmp_path/'meeting.zip'
    source.write_bytes(zip_bytes())
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(source), ''))
    monkeypatch.setattr(window, 'confirm_native_replace', lambda view: 'replace')
    window.choose_zip(0)
    bar = window.tabs.tabBar()
    QTest.mouseClick(bar, Qt.LeftButton, pos=bar.tabRect(0).center())
    assert Path(window.current.document.wav_path).read_bytes() == b'RIFF synthetic audio bytes'
    assert 'meeting.zip' in window.tabs.tabText(0) and not bar.is_empty(0)
    window.new_tab()
    QApplication.processEvents()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    event = QDropEvent(bar.tabRect(1).center(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    bar.dropEvent(event)
    assert event.isAccepted() and window.current.document.native


def test_tabs_duplicate_settings_and_save(window, tmp_path, monkeypatch):
    first = window.current
    first.editor.setPlainText('Reviewed')
    first.receive('Proposed', [])
    window.set_processing_model('deepseek-v4-pro')
    window.duplicate_tab()
    second = window.current
    assert second.document.model == 'deepseek-v4-pro' and second.document.incoming == 'Proposed'
    assert first.document.id != second.document.id
    window.set_processing_model('gemini-3.8-flash')
    assert first.document.model == 'deepseek-v4-pro'
    target = tmp_path/'version.bababui'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
    assert main.open_document(target).original == 'Reviewed' and not second.document.dirty
    assert window.tabs.tabText(1) == 'version.bababui'
    window.open_file(target)
    assert window.tabs.count() == 2 and window.current is second


def test_background_results_route_by_id_and_lock_only_one_tab(window, tmp_path, monkeypatch):
    wav = tmp_path/'test.wav'
    wav.write_bytes(b'wav')
    first = window.current
    assert 'This job has no WAV' in window.status_label.text()
    window.attach_wav(0, str(wav))
    assert 'This job has no WAV' not in window.status_label.text()
    first.editor.setPlainText('First original')
    requests = []
    monkeypatch.setattr(window.jobs, 'start', requests.append)
    window.run_bababui()
    assert 'This job has no WAV' not in window.status_label.text()
    assert first.document.busy and first.editor.isReadOnly()
    assert window.progress.isVisible() and not window.bababui_btn.isVisible()
    window.new_tab()
    second = window.current
    window.import_zip(1, tmp_path/'test.zip')
    second = window.current
    second.editor.setPlainText('Second original')
    assert not window.bababui_btn.isEnabled() and window.edit_btn.isEnabled()
    window.attach_wav(1, str(wav))
    window.run_bababui()
    window.jobs.succeeded.emit(second.document.id, 'Second result', [], None)
    window.jobs.completed.emit(second.document.id)
    window.jobs.succeeded.emit(first.document.id, 'First result', ['Review speakers'], None)
    window.jobs.completed.emit(first.document.id)
    assert first.document.original == 'First original' and first.document.incoming == 'First result'
    assert second.document.original == 'Second original' and second.document.incoming == 'Second result'
    assert window.current is second and len(requests) == 2
    assert 'Review speakers' in first.document.warnings
    assert 'This job has no WAV' not in window.tabs.tabToolTip(0)


def test_session_restore_and_legacy_migration(window, tmp_path):
    window.current.editor.setPlainText('Unsaved work')
    window.current.receive('Pending revisions', [])
    window.current.toggle_view()
    window.duplicate_tab()
    window.set_processing_model('deepseek-v4-pro')
    window.persist_session()
    restored = main.TranscriptEditor(session_path=tmp_path/'session.json', legacy_dir=tmp_path)
    assert restored.tabs.count() == 2 and restored.current.document.model == 'deepseek-v4-pro'
    assert restored.current.document.original == 'Unsaved work' and restored.current.document.view == 1
    restored.close()
    (tmp_path/'original.txt').write_text('Legacy')
    (tmp_path/'incoming.txt').write_text('Legacy incoming')
    legacy = main.TranscriptEditor(session_path=tmp_path/'other-session.json', legacy_dir=tmp_path)
    assert legacy.current.document.native is None
    assert (tmp_path/'original.txt').read_text() == 'Legacy'
    legacy.close()


def test_close_dirty_and_running_tabs(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Cancel)
    window.close_tab(0)
    assert window.tabs.count() == 1
    window.current.set_busy(True)
    assert not window.close()
    window.close_tab(0)
    assert window.tabs.count() == 1
    window.current.set_busy(False)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Discard)
    old_id = window.current.document.id
    window.close_tab(0)
    assert window.tabs.count() == 1 and window.current.document.id != old_id


def test_diff_review_and_busy_scroll(window):
    view = window.current
    view.editor.setPlainText('Shared\nOriginal')
    view.receive('Shared\nIncoming', [])
    view.set_busy(True)
    assert not view.diff_view.isEnabled()
    assert all(e.isReadOnly() for e in view.diff_view.findChildren(QPlainTextEdit))
    assert all(not b.isEnabled() for b in view.diff_view.findChildren(QPushButton))
    view.set_busy(False)
    button = next(b for b in view.diff_view.findChildren(QPushButton) if b.text() == 'Accept')
    button.click()
    try:
        assert view.document.busy
        assert view.diff_view.cards[0].isHidden()
        assert 'Updating preview' in view.diff_view.count.text()
    finally:
        wait_for_review(view)
    assert not view.document.busy
    assert view.document.original == view.document.incoming == 'Shared\nIncoming'
    assert view.original_stack.currentWidget().editor is view.editor


def wait_for_review(view):
    deadline = monotonic() + 5
    while view.document.busy and monotonic() < deadline:
        QTest.qWait(5)
    assert not view.document.busy


@pytest.mark.parametrize('action', ['Accept', 'Reject'])
def test_next_suggestion_is_shown_and_focused_before_preview_is_ready(window, action):
    view = window.current
    middle = '\n'.join(f'Shared paragraph {i}.' for i in range(55))
    original = f'The witness saw a truck.\n{middle}\nThe report mentions a dog.'
    incoming = f'The witness saw a bicycle.\n{middle}\nThe report mentions a horse.'
    view.editor.setPlainText(original)
    view.receive(incoming, [])
    panel = view.diff_view
    first, second = panel.cards
    start, *_ = panel.changes[1].ranges[0]
    panel.select(0)
    button = next(b for b in first.findChildren(QPushButton) if b.text() == action)

    button.click()
    try:
        assert view.document.busy
        assert view.document.original == original and view.document.incoming == incoming
        assert first.isHidden() and not second.isHidden()
        assert panel.current == 1
        assert 'horse' in second.findChild(QLabel, 'comparison').text()
        assert all(not b.isEnabled() for b in second.findChildren(QPushButton))
        assert view.inline_editor.source_position() == ('original', start)
        assert view.inline_editor.verticalScrollBar().value() > 0
    finally:
        wait_for_review(view)

    assert len(panel.changes) == 1
    assert 'horse' in panel.cards[0].findChild(QLabel, 'comparison').text()
    start, *_ = panel.changes[0].ranges[0]
    assert view.inline_editor.source_position() == ('original', start)
    assert all(b.isEnabled() for b in panel.cards[0].findChildren(QPushButton))


def test_recovered_scroll_position_is_not_overwritten(tmp_path, monkeypatch):
    from app.src.documents import Document, save_session, load_session
    app = QApplication.instance() or QApplication([])
    text = '\n'.join(f'Line {i}' for i in range(300))
    from app.tests.test_native_projects import native_doc
    doc, _ = native_doc(tmp_path, monkeypatch)
    doc.set_text('original', text)
    doc.set_text('incoming', text)
    doc.center_line = 150
    session = tmp_path/'session.json'
    save_session(session, [doc], doc.id)
    w = main.TranscriptEditor(session_path=session, legacy_dir=tmp_path)
    try:
        assert w.current.document.center_line == 150
        w.show()
        app.processEvents()
        w.persist_session()
        assert abs(load_session(session)[0][0].center_line - 150) < 3
    finally:
        w.close()


def test_reorder_and_active_tab_survive_recovery(window, tmp_path):
    first = window.current
    window.new_tab()
    second = window.current
    window.tabs.tabBar().moveTab(1, 0)
    window.persist_session()
    from app.src.documents import load_session
    documents, active = load_session(tmp_path/'session.json')
    assert [d.id for d in documents] == [second.document.id, first.document.id]
    assert active == second.document.id


def test_saved_name_conflict_and_close_save_cancel_preserve_tabs(window, tmp_path, monkeypatch):
    path = tmp_path/'taken.txt'
    path.write_text('Keep this')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), ''))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)
    assert not window.save_current()
    assert path.read_text() == 'Keep this' and window.current.document.dirty
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Save)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: ('', ''))
    identifier = window.current.document.id
    window.close_tab(0)
    assert window.current.document.id == identifier


def test_replacing_wav_is_tab_local(window, tmp_path):
    first = window.current
    window.duplicate_tab()
    second = window.current
    before = second.document.original
    wav = tmp_path/'replacement.wav'
    wav.write_bytes(b'wav')
    window.attach_wav(1, str(wav))
    assert second.document.original == before
    assert first.document.wav_path is None
    second.set_busy(True)
    window.set_processing_model('deepseek-v4-pro')
    assert second.document.model == 'gemini-3.8-flash'
    second.set_busy(False)


def test_unreadable_recovery_is_preserved_and_reported(tmp_path):
    app = QApplication.instance() or QApplication([])
    session = tmp_path/'session.json'
    session.write_text('bad json')
    w = main.TranscriptEditor(session_path=session, legacy_dir=tmp_path)
    try:
        assert w.current.document.warnings
        backups = list(tmp_path.glob('session.json.unreadable-*'))
        assert len(backups) == 1 and backups[0].read_text() == 'bad json'
    finally:
        w.close()


def test_header_alignment_and_editor_resize_grip(window):
    from PySide6.QtWidgets import QStatusBar
    for width in (720, 1100, 1600):
        window.resize(width, 800)
        QApplication.processEvents()
        heights = {button.height() for button in (window.file_btn, window.edit_btn,
            window.settings_btn, window.bababui_btn, window.toggle_view_btn, window.progress)}
        assert len(heights) == 1
        plus, bar = window.plus_btn.geometry(), window.tabs.tabBar().geometry()
        assert plus.top() == bar.top() and plus.height() == bar.height()
        assert plus.width() == plus.height() and plus.right() == window.tabs.width()-1
        assert not window.findChildren(QStatusBar)
        assert window.tabs.geometry().bottom() == window.height()-1
        grip = window.tabs.resize_grip
        assert grip.parentWidget() is window.tabs
        assert grip.geometry().bottomRight() == window.tabs.rect().bottomRight()
    window.show_status('Processing audio...')
    assert window.status_label.text() == 'Processing audio...'
