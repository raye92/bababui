import os
from pathlib import Path
import sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPlainTextEdit, QPushButton
from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtGui import QDropEvent, QFontDatabase, QFont
from PySide6.QtTest import QTest
import pytest
import main


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    if os.name == 'nt':
        for font in ('segoeui.ttf', 'cour.ttf'):
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
        app.setFont(QFont('Segoe UI', 9))
    w = main.TranscriptEditor(session_path=tmp_path/'session.json', legacy_dir=tmp_path)
    w.show()
    app.processEvents()
    yield w
    for view in w.views():
        view.set_busy(False)
    w.close()


def test_toolbar_tabs_shortcuts_and_dirty_dot(window):
    assert not window.toolbar.isMovable() and not window.toolbar.isFloatable()
    assert window.tabs.count() == 1 and window.current.document.dirty
    assert '●' in window.tabs.tabText(0)
    assert window.tabs.tabBar().is_empty(0)
    QTest.keyClick(window, Qt.Key_T, Qt.ControlModifier)
    assert window.tabs.count() == 2
    assert window.file_btn.text() == 'File'


def test_click_and_drop_tab_wav(window, tmp_path, monkeypatch):
    wav = tmp_path/'meeting.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(wav), ''))
    bar = window.tabs.tabBar()
    QTest.mouseClick(bar, Qt.LeftButton, pos=bar.tabRect(0).center())
    assert window.current.document.wav_path == str(wav)
    assert 'meeting.wav' in window.tabs.tabText(0) and not bar.is_empty(0)
    window.new_tab()
    QApplication.processEvents()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(wav))])
    event = QDropEvent(bar.tabRect(1).center(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    bar.dropEvent(event)
    assert event.isAccepted() and window.current.document.wav_path == str(wav)


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
    target = tmp_path/'version.txt'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
    assert target.read_text() == 'Reviewed' and not second.document.dirty
    assert window.tabs.tabText(1) == 'version.txt'
    window.open_file(target)
    assert window.tabs.count() == 2 and window.current is second


def test_background_results_route_by_id_and_lock_only_one_tab(window, tmp_path, monkeypatch):
    wav = tmp_path/'test.wav'
    wav.write_bytes(b'wav')
    first = window.current
    window.attach_wav(0, str(wav))
    first.editor.setPlainText('First original')
    requests = []
    monkeypatch.setattr(window.jobs, 'start', requests.append)
    window.run_bababui()
    assert first.document.busy and first.editor.isReadOnly()
    assert window.progress.isVisible() and not window.bababui_btn.isVisible()
    window.new_tab()
    second = window.current
    second.editor.setPlainText('Second original')
    assert window.bababui_btn.isEnabled() and window.manual_btn.isEnabled()
    window.attach_wav(1, str(wav))
    window.run_bababui()
    window.jobs.succeeded.emit(second.document.id, 'Second result', [])
    window.jobs.completed.emit(second.document.id)
    window.jobs.succeeded.emit(first.document.id, 'First result', ['Review speakers'])
    window.jobs.completed.emit(first.document.id)
    assert first.document.original == 'First original' and first.document.incoming == 'First result'
    assert second.document.original == 'Second original' and second.document.incoming == 'Second result'
    assert window.current is second and len(requests) == 2
    assert first.document.warnings == ['Review speakers']


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
    assert legacy.current.document.original == 'Legacy' and legacy.current.document.incoming == 'Legacy incoming'
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
    assert view.diff_view.isEnabled()
    assert all(e.isReadOnly() for e in view.diff_view.findChildren(QPlainTextEdit))
    assert all(not b.isEnabled() for b in view.diff_view.findChildren(QPushButton))
    view.set_busy(False)
    button = next(b for b in view.diff_view.findChildren(QPushButton) if 'Accept' in b.text())
    button.click()
    assert view.document.original == view.document.incoming == 'Shared\nIncoming'
    assert view.original_stack.currentWidget() is view.editor


def test_recovered_scroll_position_is_not_overwritten(tmp_path):
    from app.src.documents import Document, save_session, load_session
    app = QApplication.instance() or QApplication([])
    text = '\n'.join(f'Line {i}' for i in range(300))
    doc = Document(original=text, incoming=text, center_line=150)
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


def test_manual_operations_and_replacing_wav_are_tab_local(window, tmp_path):
    first = window.current
    first.editor.setPlainText('Unchanged')
    window.new_tab()
    second = window.current
    window.insert_sample_text()
    assert first.document.original == 'Unchanged'
    before = second.document.original
    wav = tmp_path/'replacement.wav'
    wav.write_bytes(b'wav')
    window.attach_wav(1, str(wav))
    assert second.document.original == before and second.document.dirty
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
