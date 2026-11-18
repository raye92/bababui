"""Tabbed transcript editor with explicit saves and independent processing."""
import sys
from pathlib import Path
import shutil
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QSignalBlocker, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QToolBar, QMessageBox,
    QWidget, QHBoxLayout, QPushButton, QToolButton, QMenu, QProgressBar,
    QFileDialog, QSizePolicy, QLabel, QInputDialog)
from app.src.processing import MODELS, DEFAULT_MODEL, PROMPT_FILE, APP_DIR, load_config
from app.src.ai_review import DEFAULT_REVIEW_MODEL
from app.src.audio_pipeline import AUDIO_MODEL
from app.src.documents import (Document, canonical, save_document, open_document,
    suggested_path, save_session, load_session_state, import_casecat)
from app.src.casecat.archive import inspect_archive
from app.src.casecat.retiming import AudioExportError
from app.src.document_view import DocumentView, ImportView
from app.src.playback import DEFAULT_FORWARD_SECONDS
from app.src.settings_page import SettingsPage
from app.src.tab_bar import AudioTabBar, NewTabButton, EditorTabs
from app.src.jobs import JobManager, Request
from app.src.notice_dialog import NoticeWizard, read_notice
from app.src.notice_model import NoticeDetails


class TranscriptEditor(QMainWindow):
    def __init__(self, *, session_path=None, legacy_dir=None, jobs=None):
        super().__init__()
        self.setWindowTitle('BABABUI')
        self.resize(1100, 800)
        self.setMinimumWidth(720)
        self.session_path = Path(session_path) if session_path is not None else APP_DIR/'data'/'session.json'
        self.legacy_dir = Path(legacy_dir) if legacy_dir is not None else Path(__file__).parent
        self.disabled_auto_accept_rules = set()
        self._restoring = True
        self._recovery_enabled = True
        self._last_view = None
        self._last_document_id = None
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
        documents, active, notice, self.settings = self._read_session()
        self._build_toolbar()
        self._build_settings()
        self._restore(documents, active, notice)
        self._restoring = False
        self._tab_changed(self.tabs.currentIndex())
        self.persist_session()

    @property
    def current(self):
        return self.document_tab(self.tabs.currentIndex())

    def document_tab(self, index):
        page = self.tabs.widget(index)
        return page if isinstance(page, (DocumentView, ImportView)) else None

    def views(self):
        return [view for i in range(self.tabs.count()) if (view := self.document_tab(i)) is not None]

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
        menu.addSeparator()
        self.accept_all_preview_action = menu.addAction('Preview Accept All')
        self.accept_all_preview_action.setCheckable(True)
        self.accept_all_preview_action.triggered.connect(self.toggle_accept_all_preview)
        self.edit_btn, edit = self._menu_button('Edit', row)
        edit.addAction('Attach WAV...', lambda: self.choose_wav(self.tabs.currentIndex()))
        self.notice_action = edit.addAction('Attach or replace notice PDF…', lambda: self.attach_notice(self.current))
        self.undo_review_action = edit.addAction('Undo review', lambda: self.current.undo_review())
        self.addAction(self.undo_review_action)
        edit.addAction('Redo review', lambda: self.current.redo_review())
        edit.addSeparator()
        self.review_actions = []
        for label, shortcut, callback in (
            ('Accept suggestion', 'A', lambda v: v.diff_view.request_current(True)),
            ('Reject suggestion', 'D', lambda v: v.diff_view.request_current(False)),
            ('Replay current edit', 'W', lambda v: v.replay_current_edit()),
            ('Fast forward', 'S', lambda v: v.playback.skip_forward() if v.playback else None),
        ):
            action = edit.addAction(label)
            action.setShortcut(QKeySequence(shortcut))
            action.setAutoRepeat(False)
            action.triggered.connect(lambda _, cb=callback: self._run_suggestion_action(cb))
            self.addAction(action)
            self.review_actions.append(action)
        self.bulk_review_actions = []
        for caption, accept in (('Accept All', True), ('Reject All', False)):
            action = edit.addAction(caption)
            action.triggered.connect(
                lambda _, accepted=accept: self.current.review(None, accepted, background=True))
            self.bulk_review_actions.append(action)
        edit.addSeparator()
        insert = edit.addMenu('Insert')
        insert.addAction('Field...', lambda: self.native_edit_action('insert_native_field'))
        insert.addAction('Insert Format Symbols...', lambda: self.native_edit_action('choose_native_symbol'))
        edit.addAction('Fill In Field...', lambda: self.native_edit_action('edit_native_field'))
        edit.addAction('Change Format Symbol...', lambda: self.native_edit_action('change_native_symbol'))
        self.settings_btn = QToolButton()
        self.settings_btn.setText('Settings')
        self.settings_btn.clicked.connect(self.open_settings)
        row.addWidget(self.settings_btn)
        self.status_label = QLabel()
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.status_label, 1)
        self.bababui_btn = QPushButton('BABABUI')
        self.button_sound = QMediaPlayer(self)
        self.button_sound.setAudioOutput(QAudioOutput(self.button_sound))
        self.button_sound.setSource(QUrl.fromLocalFile(str(APP_DIR / 'assets' / 'BABABUI.mp3')))
        self.bababui_btn.clicked.connect(self._play_button_sound)
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

    def _play_button_sound(self):
        self.button_sound.setPosition(0)
        self.button_sound.play()

    def _build_settings(self):
        self.settings_page = page = SettingsPage(self.file_actions.values(), self.review_actions)
        for rule, checkbox in page.auto_accept.items():
            enabled = self._load_setting(f'auto_accept/{rule}', True)
            checkbox.setChecked(enabled)
            if not enabled:
                self.disabled_auto_accept_rules.add(rule)
            checkbox.toggled.connect(lambda checked, key=rule: self.set_auto_accept_rule(key, checked))

        trailing = page.trailing_whitespace
        delete_whitespace = self._load_setting('auto_accept/trailing_whitespace', True)
        trailing.setCurrentIndex(trailing.findData(delete_whitespace))
        if not delete_whitespace:
            self.disabled_auto_accept_rules.add('trailing_whitespace')
        trailing.currentIndexChanged.connect(
            lambda _: self.set_auto_accept_rule('trailing_whitespace', trailing.currentData()))

        page.ai_review_enabled.setChecked(self._load_setting('ai_review/enabled', True))
        page.ai_review_enabled.toggled.connect(lambda checked: self._set_setting('ai_review/enabled', checked))
        page.recognize_file_number.setChecked(self._load_setting('notice/recognize_file_number', False))
        page.recognize_file_number.toggled.connect(lambda checked: self._set_setting('notice/recognize_file_number', checked))
        review_model = self._load_setting('ai_review/model', DEFAULT_REVIEW_MODEL)
        review_model = review_model if review_model in MODELS else DEFAULT_REVIEW_MODEL
        page.ai_review_model.setCurrentIndex(page.ai_review_model.findData(review_model))
        page.ai_review_model.currentIndexChanged.connect(
            lambda _: self._set_setting('ai_review/model', page.ai_review_model.currentData()))
        page.processing_model.currentIndexChanged.connect(
            lambda _: self.set_processing_model(page.processing_model.currentData()))

        seconds = self._load_setting('playback/forward_seconds', DEFAULT_FORWARD_SECONDS)
        if page.forward_seconds.minimum() <= seconds <= page.forward_seconds.maximum():
            page.forward_seconds.setValue(seconds)
        page.forward_seconds.valueChanged.connect(self.set_forward_seconds)

    def open_settings(self):
        index = self.tabs.indexOf(self.settings_page)
        if index < 0:
            index = self.tabs.addTab(self.settings_page, 'Settings')
            self.tabs.tabBar().setTabData(index, {'settings': True})
        self.tabs.setCurrentIndex(index)

    def _processing_model_view(self):
        return self.current or self.find_view(self._last_document_id) or next(iter(self.views()), None)

    def native_edit_action(self, method):
        editor = self.current.active_editor() if self.current else None
        if editor and self.current.document.native and not editor.isReadOnly():
            getattr(editor, method)()

    def _read_session(self):
        documents, active = [], None
        notice = ''
        settings = {}
        if self.session_path.exists():
            try:
                documents, active, settings = load_session_state(self.session_path)
            except (OSError, ValueError) as exc:
                try:
                    backup = self.session_path.with_name(self.session_path.name + f'.unreadable-{time.time_ns()}')
                    shutil.copy2(self.session_path, backup)
                except OSError:
                    self._recovery_enabled = False
                notice = str(exc)
        return documents, active, notice, settings

    def _restore(self, documents, active, notice):
        for document in documents:
            self.add_document(document)
        if not documents:
            self.new_tab(status=notice, warnings=[notice] if notice else [])
        target = self.find_view(active)
        if target:
            self.tabs.setCurrentWidget(target)

    def add_document(self, document):
        if document.model not in MODELS or document.transcription_model != AUDIO_MODEL:
            document.model, document.transcription_model = DEFAULT_MODEL, AUDIO_MODEL
            document.dirty = True
            document.warnings.append('Unsupported saved model selection was reset to the defaults.')
        view = self._create_document_view(document)
        index = self.tabs.addTab(view, document.title)
        self.tabs.setCurrentIndex(index)
        self.document_changed(view)
        return view

    def _create_document_view(self, document):
        if document.native:
            view = DocumentView(document, disabled_auto_accept_rules=self.disabled_auto_accept_rules,
                                forward_seconds=self.settings_page.forward_seconds.value())
            view.notice_requested.connect(self._attach_requested_notice)
            view.diff_view.selection_changed.connect(self._update_suggestion_actions)
        else:
            view = ImportView(document)
            view.import_requested.connect(lambda v=view: self.choose_zip(self.tabs.indexOf(v)))
        view.changed.connect(lambda v=view: self.document_changed(v))
        return view

    def new_tab(self, **document_fields):
        model = self._load_setting('processing/model', DEFAULT_MODEL)
        return self.add_document(Document(model=model if model in MODELS else DEFAULT_MODEL, **document_fields))

    def duplicate_tab(self, index=None):
        view = self.document_tab(index) if index is not None else self.current
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
            if doc.native.notice:
                tooltip += f'\nNotice: {doc.native.notice.filename}'
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
        if self.current in (view, None):
            self.update_controls()
        self.schedule_recovery()

    def _tab_changed(self, index):
        if self._last_view is not None:
            self._last_view.capture_position()
        self._last_view = self.current
        if self.current:
            self._last_document_id = self.current.document.id
            self.current.schedule_restore()
        if hasattr(self, 'settings_page'):
            self.update_controls()
        self.schedule_recovery()

    def update_controls(self):
        view = self.current
        doc = view.document if view else None
        busy = bool(doc and doc.busy)
        editable = isinstance(view, DocumentView) and not busy
        self.edit_btn.setEnabled(editable)
        self.notice_action.setEnabled(editable)
        pending_review = isinstance(view, DocumentView) and bool(view.review_model.edits)
        self.undo_review_action.setShortcut(QKeySequence(QKeySequence.Undo) if pending_review else QKeySequence())
        self.undo_review_action.setEnabled(editable)
        self._update_suggestion_actions()
        for action in self.bulk_review_actions:
            action.setEnabled(pending_review and editable)
        self.bababui_btn.setVisible(not busy)
        self.bababui_btn.setEnabled(bool(doc and doc.wav_path) and not busy)
        self.progress.setVisible(busy)
        self.toggle_view_btn.setEnabled(isinstance(view, DocumentView))
        self.accept_all_preview_action.setEnabled(isinstance(view, DocumentView))
        with QSignalBlocker(self.accept_all_preview_action):
            self.accept_all_preview_action.setChecked(isinstance(view, DocumentView) and view.accept_all_preview)
        for name in ('Save', 'Save As', 'Export CaseCAT ZIP'):
            self.file_actions[name].setEnabled(editable)
        self.file_actions['Close Tab'].setEnabled(not busy)
        self.file_actions['Import CaseCAT ZIP'].setEnabled(bool(doc) and not busy)
        self.file_actions['Duplicate Tab'].setEnabled(bool(doc))
        if not doc:
            self._update_processing_model_picker()
            self.toggle_view_btn.setText('Show Incoming')
            self.show_status('')
            self.setWindowTitle('Settings - BABABUI')
            return
        self.progress.setToolTip(doc.status)
        self.progress.setAccessibleDescription(doc.status)
        self.toggle_view_btn.setText('Back to Original' if doc.view else 'Show Incoming')
        message = doc.status
        visible_warnings = [warning for warning in doc.warnings
                            if not doc.native or warning != doc.native.job.warnings[0]]
        if visible_warnings:
            message += ' ' + ' '.join(visible_warnings)
        self.show_status(message)
        self.status_label.setToolTip('\n'.join([doc.status, *doc.warnings]))
        self.setWindowTitle(f'{doc.title}{" *" if doc.dirty else ""} - BABABUI')

    def _active_suggestion_view(self):
        view = self.current
        if isinstance(view, DocumentView) and not view.document.busy and view.diff_view.has_current:
            return view

    def _update_suggestion_actions(self):
        view = self._active_suggestion_view()
        accept, reject, replay, forward = self.review_actions
        accept.setEnabled(view is not None)
        reject.setEnabled(view is not None)
        forward.setEnabled(bool(view and view.playback))
        replay.setEnabled(bool(view and view.playback and view.playback.timing is not None
                               and view.diff_view.changes[view.diff_view.current].ranges))

    def _run_suggestion_action(self, callback):
        view = self._active_suggestion_view()
        if view:
            callback(view)

    def _update_processing_model_picker(self):
        view = self._processing_model_view()
        picker = self.settings_page.processing_model
        with QSignalBlocker(picker):
            picker.setCurrentIndex(picker.findData(view.document.model) if view else -1)
        picker.setEnabled(bool(view and not view.document.busy))
        context = f'Applies to {view.document.title} and new tabs.' if view else 'Open a document tab to set its processing model.'
        self.settings_page.processing_context.setText(context)

    def show_status(self, message):
        self.status_label.setText(message)
        self.status_label.setToolTip(message)

    def _load_setting(self, key, default):
        value = self.settings.get(key, default)
        return value if type(value) is type(default) else default

    def _set_setting(self, key, value):
        self.settings[key] = value
        self.schedule_recovery()

    def set_auto_accept_rule(self, rule, enabled):
        if enabled:
            self.disabled_auto_accept_rules.discard(rule)
        else:
            self.disabled_auto_accept_rules.add(rule)
        self._set_setting(f'auto_accept/{rule}', enabled)

    def set_forward_seconds(self, seconds):
        self._set_setting('playback/forward_seconds', seconds)
        for view in self.views():
            if isinstance(view, DocumentView):
                view.set_forward_seconds(seconds)

    def set_processing_model(self, model):
        view = self._processing_model_view()
        if view and not view.document.busy and model in MODELS:
            self._set_setting('processing/model', model)
            if view.document.model != model:
                view.document.model = model
                view.edited()

    def choose_wav(self, index):
        view = self.document_tab(index)
        if not view or view.document.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choose WAV recording',
            str(Path(view.document.wav_path).parent) if view.document.wav_path else '', 'WAV audio (*.wav *.WAV)')
        if path:
            self.attach_wav(index, path)

    def choose_zip(self, index):
        view = self.document_tab(index)
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
        view = self.document_tab(index)
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
            replacement = self._create_document_view(candidate)
            self._last_view = None
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, replacement, candidate.title)
            self.tabs.setCurrentIndex(index)
            view.deleteLater()
            self.document_changed(replacement)
            replacement.offer_notice()
            self.persist_session()
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Could not import CaseCAT ZIP', str(exc))
            return False

    def _attach_requested_notice(self):
        self.attach_notice(self.sender())

    def attach_notice(self, view):
        if not isinstance(view, DocumentView) or view.document.busy:
            return False
        doc, state = view.document, view.document.native
        folder = Path(state.bundle.source_path).parent if state.bundle.source_path else ''
        filename, _ = QFileDialog.getOpenFileName(self, 'Attach notice PDF', str(folder), 'PDF documents (*.pdf *.PDF)')
        if not filename:
            return False
        try:
            from app.src.casecat.cover import existing_cover
            pdf, extracted = read_notice(filename, self)
            bundle, job = state.edited_job(state.original)
            known, pages, _ = existing_cover(bundle, job)
            # The native text supplies manual changes made since the last notice.
            prior = state.notice.details.to_dict() if state.notice else {}
            existing = NoticeDetails.from_dict({**prior, **known})
            wizard = NoticeWizard(filename, extracted, existing, state.recording,
                                  self.settings_page.recognize_file_number.isChecked(), self,
                                  previously_attached=state.notice is not None)
            try:
                if not wizard.exec():
                    return False
                details = wizard.details()
            finally:
                wizard.deleteLater()
            native = state.with_notice(filename, pdf, details, pages)
            from dataclasses import replace
            view.capture_position()
            candidate = replace(doc, native=native, dirty=True, status='Notice applied.')
            replacement = self._create_document_view(candidate)
            index = self.tabs.indexOf(view)
            self._last_view = None
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, replacement, candidate.title)
            self.tabs.setCurrentIndex(index)
            view.deleteLater()
            self.document_changed(replacement)
            self.persist_session()
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Could not apply notice PDF', str(exc))
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
            try:
                doc.export_casecat(target, overwrite=overwrite)
                doc.status = ('CaseCAT ZIP exported with corrected audio timing.' if doc.native.alignment
                              else 'CaseCAT ZIP exported.')
            except AudioExportError as exc:
                answer = QMessageBox.question(self, 'Corrected audio timing unavailable',
                    f'{exc}\n\nExport with the original CaseCAT audio timing?',
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                if answer != QMessageBox.Yes:
                    return False
                doc.export_casecat(target, overwrite=overwrite, corrected_audio=False)
                doc.status = 'CaseCAT ZIP exported with original audio timing.'
            self.document_changed(view)
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Could not export CaseCAT ZIP', str(exc))
            return False

    def attach_wav(self, index, path):
        view = self.document_tab(index)
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
        if self.tabs.widget(index) is self.settings_page:
            if self.tabs.currentWidget() is self.settings_page:
                target = self._processing_model_view()
                if target:
                    self.tabs.setCurrentWidget(target)
            self.tabs.removeTab(index)
            return
        view = self.document_tab(index)
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
        if not self.views():
            self.new_tab()
        elif self.current is None:
            self.update_controls()
        self.persist_session()

    def toggle_view(self):
        if self.current:
            self.current.toggle_view()

    def toggle_accept_all_preview(self, enabled):
        if isinstance(self.current, DocumentView):
            self.current.set_accept_all_preview(enabled)

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
                              review_model=(self.settings_page.ai_review_model.currentData()
                                            if self.settings_page.ai_review_enabled.isChecked() else None),
                              disabled_rules=frozenset(self.disabled_auto_accept_rules),
                              bundle=doc.native.bundle, job=doc.native.job,
                              body_start=doc.native.body_position(doc.native.original),
                              vocabulary=(doc.native.notice.details.with_current_names(doc.native.original).vocabulary()
                                          if doc.native.notice else ()))
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

    def _succeeded(self, identifier, text, warnings, alignment):
        view = self.find_view(identifier)
        if view:
            view.receive(text, warnings, alignment)

    def _reviewed(self, identifier, result, warnings, alignment):
        view = self.find_view(identifier)
        if view:
            view.receive_reviewed(result, warnings, alignment)

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
            views = self.views()
            for view in views:
                view.capture_position()
            active = self._processing_model_view()
            save_session(self.session_path, [view.document for view in views],
                         active.document.id if active else None, settings=self.settings)
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
