"""Tabbed transcript editor with explicit saves and independent processing."""
import sys
from pathlib import Path
import shutil
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QToolBar, QMessageBox,
    QWidget, QHBoxLayout, QPushButton, QToolButton, QMenu, QTabWidget, QProgressBar,
    QFileDialog, QSizePolicy, QLabel, QInputDialog)
from app.src.processing import MODELS, DEFAULT_MODEL, PROMPT_FILE, APP_DIR, load_config
from app.src.ai_review import DEFAULT_REVIEW_MODEL
from app.src.audio_pipeline import AUDIO_MODEL
from app.src.documents import (Document, canonical, save_document, open_document,
    suggested_path, save_session, load_session, import_casecat)
from app.src.casecat.archive import inspect_archive
from app.src.document_view import DocumentView, ImportView
from app.src.tab_bar import AudioTabBar, NewTabButton, EditorTabs
from app.src.jobs import JobManager, Request


class TranscriptEditor(QMainWindow):
    def __init__(self, *, session_path=None, legacy_dir=None, jobs=None):
        super().__init__()
        self.setWindowTitle('BABABUI')
        self.resize(1100, 800)
        self.setMinimumWidth(720)
        self.session_path = Path(session_path) if session_path is not None else APP_DIR/'data'/'session.json'
        self.legacy_dir = Path(legacy_dir) if legacy_dir is not None else Path(__file__).parent
        self.preferences = QSettings(str(self.session_path.with_name('settings.ini')), QSettings.IniFormat)
        self.disabled_auto_accept_rules = set()
        self._restoring = True
        self._recovery_enabled = True
        self._last_view = None
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setSingleShot(True)
        self._recovery_timer.setInterval(300)
        self._recovery_timer.timeout.connect(self.persist_session)
        self.jobs = jobs if jobs is not None else JobManager(self)
        self.jobs.succeeded.connect(self._succeeded)
        self.jobs.reviewed.connect(self._reviewed)
        self.jobs.failed.connect(self._failed)
        self.jobs.progress.connect(self._progress)
        self.jobs.completed.connect(self._completed)
        self.tabs = EditorTabs()
        self.tabs.setTabBar(AudioTabBar())
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        bar = self.tabs.tabBar()
        bar.attach_requested.connect(self.choose_zip)
        bar.zip_dropped.connect(self.import_zip)
        bar.duplicate_requested.connect(self.duplicate_tab)
        bar.replace_requested.connect(self.choose_zip)
        bar.close_requested.connect(self.close_tab)
        bar.tabMoved.connect(lambda *_: self.schedule_recovery())
        self.plus_btn = NewTabButton(self.tabs)
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
            ('Import CaseCAT ZIP', '', lambda: self.choose_zip(self.tabs.currentIndex())),
            ('Export CaseCAT ZIP', '', self.export_casecat),
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
        self.edit_btn, edit = self._menu_button('Edit', row)
        edit.addAction('Attach WAV...', lambda: self.choose_wav(self.tabs.currentIndex()))
        edit.addAction('Undo review', lambda: self.current.undo_review())
        edit.addAction('Redo review', lambda: self.current.redo_review())
        insert = edit.addMenu('Insert')
        insert.addAction('Field...', lambda: self.native_edit_action('insert_native_field'))
        insert.addAction('Insert Format Symbols...', lambda: self.native_edit_action('choose_native_symbol'))
        edit.addAction('Fill In Field...', lambda: self.native_edit_action('edit_native_field'))
        edit.addAction('Change Format Symbol...', lambda: self.native_edit_action('change_native_symbol'))
        self.settings_btn, settings = self._menu_button('Settings', row)
        automated_edits = settings.addMenu('Automated edits')
        for rule, label in (
            ('punctuation', 'Accept punctuation'),
            ('capitalization', 'Accept capitalization'),
            ('contractions', 'Accept contractions'),
            ('short_common_words', 'Accept short/common words'),
            ('off_record', 'Filter off-record discussion'),
        ):
            action = automated_edits.addAction(label)
            action.setCheckable(True)
            enabled = self.preferences.value(f'auto_accept/{rule}', True, type=bool)
            action.setChecked(enabled)
            if not enabled:
                self.disabled_auto_accept_rules.add(rule)
            action.toggled.connect(lambda checked, key=rule: self.set_auto_accept_rule(key, checked))
        ai_review = automated_edits.addMenu('AI-assisted review')
        self.ai_review_enabled = ai_review.addAction('Enabled')
        self.ai_review_enabled.setCheckable(True)
        self.ai_review_enabled.setChecked(self.preferences.value('ai_review/enabled', True, type=bool))
        self.ai_review_enabled.toggled.connect(
            lambda checked: self.preferences.setValue('ai_review/enabled', checked))
        review_models = ai_review.addMenu('Model')
        review_group = QActionGroup(self)
        review_group.setExclusive(True)
        self.ai_review_model = self.preferences.value('ai_review/model', DEFAULT_REVIEW_MODEL, type=str)
        if self.ai_review_model not in MODELS:
            self.ai_review_model = DEFAULT_REVIEW_MODEL
        for model, label in MODELS.items():
            action = review_models.addAction(label)
            action.setCheckable(True)
            action.setChecked(model == self.ai_review_model)
            review_group.addAction(action)
            action.triggered.connect(lambda checked, key=model: self.set_ai_review_model(key))
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
        self.status_label = QLabel()
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.status_label, 1)
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
        header_height = self.bababui_btn.sizeHint().height()
        for control in (self.file_btn, self.edit_btn, self.settings_btn,
                        self.bababui_btn, self.toggle_view_btn, self.progress):
            control.setFixedHeight(header_height)
        self.toolbar.addWidget(container)

    def native_edit_action(self, method):
        editor = self.current.active_editor() if self.current else None
        if editor and self.current.document.native and not editor.isReadOnly():
            getattr(editor, method)()

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
        view = (DocumentView(document, disabled_auto_accept_rules=self.disabled_auto_accept_rules)
                if document.native else ImportView(document))
        if isinstance(view, ImportView):
            view.import_requested.connect(lambda v=view: self.choose_zip(self.tabs.indexOf(v)))
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
        tooltip = f'Project: {doc.save_path or "Unsaved"}\nWAV: {doc.wav_path or "No audio"}'
        if doc.native:
            tooltip += f'\nCaseCAT job: {doc.native.job.key}'
        else:
            tooltip += '\nClick or drop a CaseCAT ZIP to import.'
        if doc.status:
            tooltip += '\n' + doc.status
        if doc.warnings:
            tooltip += '\n' + '\n'.join(doc.warnings)
        self.tabs.setTabToolTip(index, tooltip)
        self.tabs.tabBar().setTabData(index, {'wav_path': doc.wav_path, 'native': bool(doc.native), 'busy': doc.busy})
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
        self.edit_btn.setEnabled(bool(doc.native) and not doc.busy)
        self.settings_btn.setEnabled(not doc.busy)
        self.bababui_btn.setVisible(not doc.busy)
        self.bababui_btn.setEnabled(not doc.busy and bool(doc.wav_path))
        self.progress.setVisible(doc.busy)
        self.progress.setToolTip(doc.status)
        self.progress.setAccessibleDescription(doc.status)
        self.toggle_view_btn.setText('Back to Original' if doc.view else 'Show Incoming')
        self.model_actions[doc.model].setChecked(True)
        for name in ('Save', 'Save As', 'Export CaseCAT ZIP'):
            self.file_actions[name].setEnabled(bool(doc.native) and not doc.busy)
        self.toggle_view_btn.setEnabled(bool(doc.native))
        self.file_actions['Close Tab'].setEnabled(not doc.busy)
        self.file_actions['Import CaseCAT ZIP'].setEnabled(not doc.busy)
        self.file_actions['Export CaseCAT ZIP'].setEnabled(not doc.busy and bool(doc.native))
        message = doc.status
        visible_warnings = [warning for warning in doc.warnings
                            if not doc.native or warning != doc.native.job.warnings[0]]
        if visible_warnings:
            message += ' ' + ' '.join(visible_warnings)
        self.show_status(message)
        self.status_label.setToolTip('\n'.join([doc.status, *doc.warnings]))
        self.setWindowTitle(f'{doc.title}{" *" if doc.dirty else ""} - BABABUI')

    def show_status(self, message):
        self.status_label.setText(message)
        self.status_label.setToolTip(message)

    def set_auto_accept_rule(self, rule, enabled):
        if enabled:
            self.disabled_auto_accept_rules.discard(rule)
        else:
            self.disabled_auto_accept_rules.add(rule)
        self.preferences.setValue(f'auto_accept/{rule}', enabled)
        self.preferences.sync()

    def set_ai_review_model(self, model):
        self.ai_review_model = model
        self.preferences.setValue('ai_review/model', model)

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

    def choose_zip(self, index):
        view = self.tabs.widget(index)
        if not view or view.document.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Import CaseCAT ZIP', '', 'CaseCAT archives (*.zip *.ZIP)')
        if path:
            self.import_zip(index, path)

    def confirm_native_replace(self, view):
        box = QMessageBox(self)
        box.setWindowTitle('Replace transcript')
        box.setText('Importing this job replaces Original, Incoming and the attached audio. Save the current work first?')
        save = box.addButton('Save', QMessageBox.AcceptRole)
        replace = box.addButton('Replace', QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(save)
        box.exec()
        return 'save' if box.clickedButton() is save else 'replace' if box.clickedButton() is replace else 'cancel'

    def import_zip(self, index, path):
        view = self.tabs.widget(index)
        if not view or view.document.busy:
            return False
        try:
            bundle = inspect_archive(path)
            key = bundle.jobs[0]
            if len(bundle.jobs) > 1:
                key, chosen = QInputDialog.getItem(self, 'Choose CaseCAT job', 'Job to edit:', bundle.jobs, 0, False)
                if not chosen:
                    return False
            # Parsing and managed extraction finish before replacement is offered.
            candidate = import_casecat(bundle, key)
            if view.document.original or view.document.incoming or view.document.native:
                answer = self.confirm_native_replace(view)
                if answer == 'cancel' or (answer == 'save' and not self.save_view(view)):
                    return False
            candidate.model = view.document.model
            candidate.transcription_model = view.document.transcription_model
            replacement = DocumentView(candidate, disabled_auto_accept_rules=self.disabled_auto_accept_rules)
            replacement.changed.connect(lambda v=replacement: self.document_changed(v))
            self._last_view = None
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, replacement, candidate.title)
            self.tabs.setCurrentIndex(index)
            view.deleteLater()
            self.document_changed(replacement)
            self.persist_session()
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Could not import CaseCAT ZIP', str(exc))
            return False

    def export_casecat(self):
        view = self.current
        if not view or not view.document.native or view.document.busy:
            return False
        doc = view.document
        suggestion = Path(doc.save_path).parent if doc.save_path else Path.home()/'Documents'
        target, _ = QFileDialog.getSaveFileName(self, 'Export reviewed Original to CaseCAT ZIP',
            str(suggestion / doc.native.bundle.export_name), 'CaseCAT archives (*.zip)',
            options=QFileDialog.DontConfirmOverwrite)
        if not target:
            return False
        if not Path(target).suffix:
            target += '.zip'
        try:
            overwrite = Path(target).exists()
            if overwrite:
                answer = QMessageBox.question(self, 'Replace exported ZIP', 'Replace the existing destination ZIP?',
                                               QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                if answer != QMessageBox.Yes:
                    return False
            doc.export_casecat(target, overwrite=overwrite)
            doc.status = 'CaseCAT ZIP exported. Working project save status is unchanged.'
            self.document_changed(view)
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Could not export CaseCAT ZIP', str(exc))
            return False

    def attach_wav(self, index, path):
        view = self.tabs.widget(index)
        if not view or not view.document.native or view.document.busy:
            return
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower() != '.wav':
            return
        view.document.audio_override = view.document.wav_path = str(path)
        view.document.update_warnings(view.document.warnings)
        if view.playback:
            view.playback.stop()
            view.layout().removeWidget(view.playback)
            view.playback.deleteLater()
            view.playback = None
        view.setup_playback(view.layout())
        view.document.status = 'WAV attached. Click BABABUI to process.'
        view.edited()
        self.tabs.setCurrentWidget(view)

    def open_file(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, 'Open CaseCAT working project', '',
                                                 'BABABUI projects (*.bababui)')
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
                'BABABUI projects (*.bababui)',
                options=QFileDialog.DontConfirmOverwrite)
            if not target:
                return False
            if not Path(target).suffix:
                target += '.bababui'
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
            self.show_status('Wait for this tab to finish processing before closing it.')
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
        if not doc.native or not doc.wav_path:
            doc.status = 'Import a CaseCAT ZIP with audio or attach a WAV to an imported job.'
            self.document_changed(view)
            return
        try:
            request = Request(doc.id, doc.wav_path, doc.model, doc.transcription_model,
                              PROMPT_FILE.read_text(encoding='utf-8'), dict(load_config()),
                              original=doc.native.original,
                              review_model=self.ai_review_model if self.ai_review_enabled.isChecked() else None,
                              disabled_rules=frozenset(self.disabled_auto_accept_rules))
            view.set_busy(True)
            doc.status = 'Starting...'
            doc.update_warnings()
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

    def _reviewed(self, identifier, result, warnings):
        view = self.find_view(identifier)
        if view:
            view.receive_reviewed(result, warnings)

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
            self.show_status(f'Could not save recovery: {exc}')
            return False

    def closeEvent(self, event):
        if any(v.document.busy for v in self.views()):
            self.show_status('Wait for processing tabs to finish before closing BABABUI.')
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
