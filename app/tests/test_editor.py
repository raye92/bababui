import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtCore import QSettings, QMimeData, QUrl, Qt, QPoint
from PySide6.QtGui import QDropEvent, QFontDatabase, QFont
import pytest
import main


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    # The offscreen Windows plugin does not discover system fonts automatically.
    if os.name == 'nt':
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/cour.ttf')
        app.setFont(QFont('Segoe UI', 9))
    monkeypatch.setattr(main, 'ORIGINAL_FILE', str(tmp_path / 'original.txt'))
    monkeypatch.setattr(main, 'INCOMING_FILE', str(tmp_path / 'incoming.txt'))
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    w = main.TranscriptEditor(settings=settings)
    w.resize(1000, 800)
    w.show()
    app.processEvents()
    yield w
    w.close()


def test_toolbar_center_and_order(window):
    assert not window.toolbar.isMovable() and not window.toolbar.isFloatable()
    center = window.wav_input.mapTo(window, window.wav_input.rect().center()).x()
    assert abs(center-window.width()/2) <= 3
    assert window.manual_btn.x() < window.settings_btn.x()
    assert window.bababui_btn.text() == 'BABABUI'
    assert window.bababui_btn.mapTo(window, QPoint()).x() < window.toggle_view_btn.mapTo(window, QPoint()).x()


def test_click_and_drop_file(window, tmp_path, monkeypatch):
    wav = tmp_path / 'recording.wav'
    wav.write_bytes(b'placeholder')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(wav), ''))
    window.wav_input.click()
    assert window.wav_input.path == wav
    assert 'recording.wav' in window.wav_input.text()
    other = tmp_path / 'other.WAV'
    other.write_bytes(b'placeholder')
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(other))])
    event = QDropEvent(window.wav_input.rect().center(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.wav_input.dropEvent(event)
    assert event.isAccepted() and window.wav_input.path == other


def test_success_preserves_original_and_creates_diff(window):
    window.editor.setPlainText('Original')
    window._on_bababui_succeeded('Speaker 1: Incoming', [])
    assert Path(main.ORIGINAL_FILE).read_text() == 'Original'
    assert Path(main.INCOMING_FILE).read_text() == 'Speaker 1: Incoming'
    assert window.original_stack.currentWidget() is window.diff_view


def test_settings_persist(window):
    window.set_processing_model('deepseek-v4-pro')
    assert window.settings.value('processing_model') == 'deepseek-v4-pro'


def test_busy_blocks_mutation_and_close(window):
    window.set_busy(True)
    assert window.editor.isReadOnly() and window.incoming_editor.isReadOnly()
    assert not window.manual_btn.isEnabled() and not window.wav_input.isEnabled()
    assert window.toggle_view_btn.isEnabled()
    window.set_busy(False)
    assert not window.editor.isReadOnly()


def test_toolbar_remains_centered_when_switched_and_resized(window):
    for width in (780, 1000, 1600):
        window.resize(width, 800)
        window.toggle_view()
        QApplication.processEvents()
        center = window.wav_input.mapTo(window, window.wav_input.rect().center()).x()
        assert abs(center-window.width()/2) <= 3


def test_invalid_drop_is_ignored(window, tmp_path):
    path = tmp_path/'not-audio.txt'
    path.write_text('text')
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(window.wav_input.rect().center(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.wav_input.dropEvent(event)
    assert not event.isAccepted() and window.wav_input.path is None


def test_worker_pipeline_is_audio_only(window, tmp_path, monkeypatch):
    calls, results = [], []
    class Pipeline:
        def __init__(self, *args):
            pass
        def run(self, path, progress):
            calls.append(path)
            return 'Speaker 1: Audio words', []
    class Processor:
        def __init__(self, *args):
            pass
        def check_ready(self):
            pass
        def complete(self, text, prompt):
            calls.append(text)
            return 'Formatted audio'
    monkeypatch.setattr(main, 'AudioPipeline', Pipeline)
    monkeypatch.setattr(main, 'ProcessingClient', Processor)
    window.editor.setPlainText('Secret original')
    worker = main._BababuiWorker('recording.wav', 'gemini-3.8-flash', {})
    worker.succeeded.connect(lambda text, warnings: results.append(text))
    worker.run()
    assert calls == ['recording.wav', 'Speaker 1: Audio words']
    assert results == ['Formatted audio']


def test_failure_preserves_both_files(window, monkeypatch):
    window.editor.setPlainText('Original')
    Path(main.INCOMING_FILE).write_text('Previous incoming', encoding='utf-8')
    monkeypatch.setattr(main.QMessageBox, 'warning', lambda *args: None)
    window._on_bababui_failed('Network unavailable')
    assert Path(main.ORIGINAL_FILE).read_text() == 'Original'
    assert Path(main.INCOMING_FILE).read_text() == 'Previous incoming'


def test_busy_diff_can_scroll_but_cannot_edit(window):
    from PySide6.QtWidgets import QPlainTextEdit, QPushButton
    window.editor.setPlainText('Shared\nOriginal')
    window._on_bababui_succeeded('Shared\nIncoming', [])
    window.set_busy(True)
    assert window.diff_view.isEnabled()
    assert all(e.isReadOnly() for e in window.diff_view.findChildren(QPlainTextEdit))
    assert all(not b.isEnabled() for b in window.diff_view.findChildren(QPushButton))
    window.toggle_view()
    window.toggle_view()
    assert all(e.isReadOnly() for e in window.diff_view.findChildren(QPlainTextEdit))
    window.set_busy(False)
