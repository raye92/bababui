"""Tabbed transcript editor with explicit saves and independent processing."""
import sys
from pathlib import Path
import shutil
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QToolBar, QMessageBox,
    QWidget, QHBoxLayout, QPushButton, QToolButton, QMenu, QTabWidget, QProgressBar,
    QFileDialog, QSizePolicy)
from app.src.formatter import Formatter
from app.src.processing import MODELS, DEFAULT_MODEL, PROMPT_FILE, APP_DIR, load_config
from app.src.audio_pipeline import AUDIO_MODEL
from app.src.documents import (Document, canonical, save_document, open_document,
    suggested_path, save_session, load_session)
from app.src.document_view import DocumentView
from app.src.tab_bar import AudioTabBar
from app.src.jobs import JobManager, Request
from app.src.sample_text import SAMPLE


class TranscriptEditor(QMainWindow):
    def __init__(self, *, session_path=None, legacy_dir=None, jobs=None):
        super().__init__()
        self.setWindowTitle('BABABUI')
        self.resize(1100, 800)
        self.setMinimumWidth(720)
        self.formatter = Formatter()
        self.session_path = Path(session_path) if session_path is not None else APP_DIR/'data'/'session.json'
        self.legacy_dir = Path(legacy_dir) if legacy_dir is not None else Path(__file__).parent
        self._restoring = True
        self._recovery_enabled = True
        self._last_view = None
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setSingleShot(True)
        self._recovery_timer.setInterval(300)
        self._recovery_timer.timeout.connect(self.persist_session)
        self.jobs = jobs if jobs is not None else JobManager(self)
        self.jobs.succeeded.connect(self._succeeded)
        self.jobs.failed.connect(self._failed)
        self.jobs.progress.connect(self._progress)
        self.jobs.completed.connect(self._completed)
        self.tabs = QTabWidget()
        self.tabs.setTabBar(AudioTabBar())
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        bar = self.tabs.tabBar()
        bar.attach_requested.connect(self.choose_wav)
        bar.wav_dropped.connect(self.attach_wav)
        bar.duplicate_requested.connect(self.duplicate_tab)
        bar.replace_requested.connect(self.choose_wav)
        bar.close_requested.connect(self.close_tab)
        bar.tabMoved.connect(lambda *_: self.schedule_recovery())
        self.plus_btn = QToolButton()
        self.plus_btn.setText('+')
        self.plus_btn.setToolTip('New tab (Ctrl+T)')
        self.plus_btn.clicked.connect(lambda: self.new_tab())
        self.tabs.setCornerWidget(self.plus_btn, Qt.TopRightCorner)
        self._build_toolbar()
        self._restore()
        self._restoring = False
        self._tab_changed(self.tabs.currentIndex())
        self.persist_session()

    @property
    def current(self):
        return self.tabs.currentWidget()

    def views(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def find_view(self, identifier):
        return next((v for v in self.views() if v.document.id == identifier), None)

    def _menu_button(self, title, layout):
        button = QToolButton()
        button.setText(title)
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        button.setMenu(menu)
        layout.addWidget(button)
        return button, menu

    def _build_toolbar(self):
        self.toolbar = QToolBar('BABABUI', self)
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setAllowedAreas(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, self.toolbar)
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row = QHBoxLayout(container)
        row.setContentsMargins(4, 2, 4, 2)
        self.file_btn, menu = self._menu_button('File', row)
        self.file_actions = {}
        for label, shortcut, callback in (
            ('New Tab', 'Ctrl+T', lambda: self.new_tab()),
            ('Open', 'Ctrl+O', lambda: self.open_file()),
            ('Save', 'Ctrl+S', lambda: self.save_current()),
            ('Save As', 'Ctrl+Shift+S', lambda: self.save_current(save_as=True)),
            ('Duplicate Tab', '', lambda: self.duplicate_tab()),
            ('Close Tab', 'Ctrl+W', lambda: self.close_tab(self.tabs.currentIndex()))):
            action = QAction(label, self)
            action.triggered.connect(callback)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            self.addAction(action)
            menu.addAction(action)
            self.file_actions[label] = action
        self.manual_btn, manual = self._menu_button('Manual', row)
        for label, callback in (('Strip Formatting', self.strip_formatting),
                                ('Apply Standards', self.apply_formatting),
                                ('Insert Sample', self.insert_sample_text),
                                ('Batch Strip', self.batch_strip_formatting)):
            manual.addAction(label, callback)
        self.settings_btn, settings = self._menu_button('Settings', row)
        processing = settings.addMenu('LLM processing model')
        group = QActionGroup(self)
        group.setExclusive(True)
        self.model_actions = {}
        for model, label in MODELS.items():
            action = processing.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, m=model: self.set_processing_model(m))
            group.addAction(action)
            self.model_actions[model] = action
        audio = settings.addMenu('AI transcription model').addAction('Gemini 3.5 Transcribe')
        audio.setCheckable(True)
        audio.setChecked(True)
        audio.triggered.connect(lambda: audio.setChecked(True))
        row.addStretch()
        self.bababui_btn = QPushButton('BABABUI')
        self.bababui_btn.clicked.connect(self.run_bababui)
        row.addWidget(self.bababui_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(180)
        self.progress.setAccessibleName('BABABUI processing progress')
        self.progress.hide()
        row.addWidget(self.progress)
        self.toggle_view_btn = QPushButton('Show Incoming')
        self.toggle_view_btn.clicked.connect(self.toggle_view)
        row.addWidget(self.toggle_view_btn)
        self.toolbar.addWidget(container)

    def _restore(self):
        documents, active = [], None
        notice = ''
        if self.session_path.exists():
            try:
                documents, active = load_session(self.session_path)
            except (OSError, ValueError) as exc:
                try:
                    backup = self.session_path.with_name(self.session_path.name + f'.unreadable-{time.time_ns()}')
                    shutil.copy2(self.session_path, backup)
                except OSError:
                    self._recovery_enabled = False
                notice = str(exc)
        else:
            original, incoming = self.legacy_dir/'original.txt', self.legacy_dir/'incoming.txt'
            if original.exists() or incoming.exists():
                try:
                    text = original.read_text(encoding='utf-8') if original.exists() else ''
                    proposed = incoming.read_text(encoding='utf-8') if incoming.exists() else text
                    documents = [Document(original=text, incoming=proposed or text,
                                          status='Imported the previous working transcript. Save it as a named file.')]
                except (OSError, UnicodeError) as exc:
                    notice = f'Could not import the previous transcript: {exc}'
        for document in documents:
            self.add_document(document)
        if not documents:
            self.add_document(Document(status=notice, warnings=[notice] if notice else []))
        target = self.find_view(active)
        if target:
            self.tabs.setCurrentWidget(target)

    def add_document(self, document):
        if document.model not in MODELS or document.transcription_model != AUDIO_MODEL:
            document.model, document.transcription_model = DEFAULT_MODEL, AUDIO_MODEL
            document.dirty = True
            document.warnings.append('Unsupported saved model selection was reset to the defaults.')
        view = DocumentView(document)
        view.changed.connect(lambda v=view: self.document_changed(v))
        index = self.tabs.addTab(view, document.title)
        self.tabs.setCurrentIndex(index)
        self.document_changed(view)
        return view

    def new_tab(self):
        return self.add_document(Document())

    def duplicate_tab(self, index=None):
        view = self.tabs.widget(index) if index is not None else self.current
        if view:
            view.capture_position()
            return self.add_document(view.document.duplicate())

    def document_changed(self, view):
        index = self.tabs.indexOf(view)
        if index < 0:
            return
        doc = view.document
        label = doc.title + (' ●' if doc.dirty else '') + (' [Working]' if doc.busy else '')
        self.tabs.setTabText(index, label)
        tooltip = f'Text: {doc.save_path or "Unsaved"}\nWAV: {doc.wav_path or "Click or drop a WAV"}'
        if doc.status:
            tooltip += '\n' + doc.status
        if doc.warnings:
            tooltip += '\n' + '\n'.join(doc.warnings)
        self.tabs.setTabToolTip(index, tooltip)
        self.tabs.tabBar().setTabData(index, {'wav_path': doc.wav_path, 'busy': doc.busy})
        for side in (AudioTabBar.LeftSide, AudioTabBar.RightSide):
            button = self.tabs.tabBar().tabButton(index, side)
            if button:
                button.setEnabled(not doc.busy)
        self.tabs.tabBar().update()
        if view is self.current:
            self.update_controls()
        self.schedule_recovery()

    def _tab_changed(self, index):
        if self._last_view is not None:
            self._last_view.capture_position()
        self._last_view = self.current
        if self.current:
            self.current.schedule_restore()
        if hasattr(self, 'bababui_btn'):
            self.update_controls()
        self.schedule_recovery()

    def update_controls(self):
        view = self.current
        if not view:
            return
        doc = view.document
        self.manual_btn.setEnabled(not doc.busy)
        self.settings_btn.setEnabled(not doc.busy)
        self.bababui_btn.setVisible(not doc.busy)
        self.bababui_btn.setEnabled(not doc.busy)
        self.progress.setVisible(doc.busy)
        self.progress.setToolTip(doc.status)
        self.progress.setAccessibleDescription(doc.status)
        self.toggle_view_btn.setText('Back to Original' if doc.view else 'Show Incoming')
        self.model_actions[doc.model].setChecked(True)
        self.file_actions['Close Tab'].setEnabled(not doc.busy)
        message = doc.status
        if doc.warnings:
            message += ' ' + ' '.join(doc.warnings)
        self.statusBar().showMessage(message)
        self.setWindowTitle(f'{doc.title}{" *" if doc.dirty else ""} - BABABUI')

    def set_processing_model(self, model):
        if self.current and not self.current.document.busy and model in MODELS:
            if self.current.document.model != model:
                self.current.document.model = model
                self.current.edited()

    def choose_wav(self, index):
        view = self.tabs.widget(index)
        if not view or view.document.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choose WAV recording',
            str(Path(view.document.wav_path).parent) if view.document.wav_path else '', 'WAV audio (*.wav *.WAV)')
        if path:
            self.attach_wav(index, path)

    def attach_wav(self, index, path):
        view = self.tabs.widget(index)
        if not view or view.document.busy:
            return
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower() != '.wav':
            return
        view.document.wav_path = str(path)
        view.document.status = 'WAV attached. Click BABABUI to process.'
        view.edited()
        self.tabs.setCurrentWidget(view)

    def open_file(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, 'Open transcript', '', 'Text files (*.txt)')
        if not path:
            return
        existing = next((v for v in self.views() if v.document.save_path
                         and canonical(v.document.save_path) == canonical(path)), None)
        if existing:
            self.tabs.setCurrentWidget(existing)
            return
        try:
            self.add_document(open_document(path))
        except (OSError, ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, 'Could not open transcript', str(exc))

    def save_current(self, *, save_as=False):
        return self.save_view(self.current, save_as=save_as)

    def save_view(self, view, *, save_as=False):
        if not view:
            return False
        doc = view.document
        target = doc.save_path
        if save_as or not target:
            directory = Path(doc.save_path).parent if doc.save_path else Path.home()/'Documents'
            suggestion = suggested_path(doc, directory)
            target, _ = QFileDialog.getSaveFileName(self, 'Save transcript version', str(suggestion),
                'Text files (*.txt)', options=QFileDialog.DontConfirmOverwrite)
            if not target:
                return False
            if not Path(target).suffix:
                target += '.txt'
        try:
            if any(v is not view and v.document.save_path and canonical(v.document.save_path) == canonical(target)
                   for v in self.views()):
                raise ValueError('That file belongs to another open tab. Choose a different version name.')
            save_document(doc, target, save_as=save_as)
            doc.status = 'Saved.'
            self.document_changed(view)
            self.persist_session()
            return True
        except (OSError, ValueError) as exc:
            self.document_changed(view)
            QMessageBox.warning(self, 'Could not save transcript', str(exc))
            return False

    def close_tab(self, index):
        view = self.tabs.widget(index)
        if not view:
            return
        if view.document.busy:
            self.statusBar().showMessage('Wait for this tab to finish processing before closing it.')
            return
        if view.document.dirty:
            answer = QMessageBox.question(self, 'Unsaved changes', f'Save changes to {view.document.title}?',
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if answer == QMessageBox.Cancel or (answer == QMessageBox.Save and not self.save_view(view)):
                return
        self._last_view = None
        self.tabs.removeTab(index)
        view.deleteLater()
        if not self.tabs.count():
            self.new_tab()
        self.persist_session()

    def toggle_view(self):
        if self.current:
            self.current.toggle_view()

    def run_bababui(self):
        view = self.current
        if not view or view.document.busy:
            return
        doc = view.document
        if not doc.wav_path:
            doc.status = 'Attach a WAV to this tab first.'
            self.document_changed(view)
            return
        try:
            request = Request(doc.id, doc.wav_path, doc.model, doc.transcription_model,
                              PROMPT_FILE.read_text(encoding='utf-8'), dict(load_config()))
            view.set_busy(True)
            doc.status = 'Starting...'
            doc.warnings = []
            self.document_changed(view)
            self.persist_session()
            self.jobs.start(request)
        except (OSError, ValueError) as exc:
            view.set_busy(False)
            self._failed(doc.id, str(exc))

    def _progress(self, identifier, message):
        view = self.find_view(identifier)
        if view:
            view.document.status = message
            self.document_changed(view)

    def _succeeded(self, identifier, text, warnings):
        view = self.find_view(identifier)
        if view:
            view.receive(text, warnings)

    def _failed(self, identifier, message):
        view = self.find_view(identifier)
        if view:
            view.document.status = message
            self.document_changed(view)

    def _completed(self, identifier):
        view = self.find_view(identifier)
        if view:
            view.set_busy(False)
            self.document_changed(view)
            self.persist_session()

    def _manual_editor(self):
        view = self.current
        if not view or view.document.busy:
            return None
        editor = view.active_editor()
        if editor is None:
            view.document.status = 'Resolve the incoming changes first.'
            self.document_changed(view)
        return editor

    def insert_sample_text(self):
        editor = self._manual_editor()
        if editor is not None:
            editor.setPlainText(SAMPLE)

    def strip_formatting(self):
        editor = self._manual_editor()
        if editor is not None:
            editor.setPlainText(self.formatter.strip_formatting(editor.toPlainText()))

    def apply_formatting(self):
        editor = self._manual_editor()
        if editor is not None:
            text, pages = self.formatter.apply_formatting(editor.toPlainText())
            editor.setPlainText(text)
            self.current.document.status = f'Applied standards: {pages} pages generated.'
            self.document_changed(self.current)

    def batch_strip_formatting(self):
        view = self.current
        if not view or view.document.busy:
            return
        start = str(Path(view.document.save_path).parent) if view.document.save_path else ''
        folder = QFileDialog.getExistingDirectory(self, 'Choose folder of text files to strip', start)
        if not folder:
            return
        try:
            results = self.formatter.batch_strip_formatting(folder, str(Path(folder)/'stripped'))
            view.document.status = f'Batch strip: {len(results["processed"])} processed, {len(results["failed"])} failed.'
            self.document_changed(view)
        except (OSError, ValueError) as exc:
            view.document.status = str(exc)
            self.document_changed(view)

    def schedule_recovery(self):
        if not self._restoring:
            self._recovery_timer.start()

    def persist_session(self):
        if self._restoring or not self._recovery_enabled:
            return False
        self._recovery_timer.stop()
        try:
            for view in self.views():
                view.capture_position()
            save_session(self.session_path, [v.document for v in self.views()],
                         self.current.document.id if self.current else None)
            return True
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f'Could not save recovery: {exc}')
            return False

    def closeEvent(self, event):
        if any(v.document.busy for v in self.views()):
            self.statusBar().showMessage('Wait for processing tabs to finish before closing BABABUI.')
            event.ignore()
        elif not self.persist_session():
            QMessageBox.warning(self, 'Recovery could not be saved', 'Keep the app open and save your documents before trying again.')
            event.ignore()
        else:
            super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TranscriptEditor()
    window.show()
    sys.exit(app.exec())
