"""Settings and keyboard reference in the editor's tab strip."""
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QScrollArea, QSpinBox, QVBoxLayout, QWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QLineEdit,
    QFileDialog, QPushButton, QToolButton, QMenu)

from app.src.native_dialogs import FormatSymbolDialog
from app.src.playback import DEFAULT_FORWARD_SECONDS, PLAYBACK_SHORTCUTS
from app.src.processing import MODELS
from app.src.smart_keys import binding_dependency, default_profile, event_key, import_profile


AUTO_ACCEPT_OPTIONS = (
    ('punctuation', 'Accept punctuation'),
    ('capitalization', 'Accept capitalization'),
    ('contractions', 'Accept contractions'),
    ('short_common_words', 'Accept short/common words'),
    ('date_ordinals', 'Accept ordinal suffix changes'),
    ('positive_confirmations', 'Accept equivalent confirmations'),
    ('number_forms', 'Accept equivalent number forms'),
    ('off_record', 'Filter off-record discussion'),
)


class SettingsPage(QScrollArea):
    profileChanged = Signal(object)

    def __init__(self, file_actions, review_actions):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.setWidget(content)
        columns = QHBoxLayout(content)
        columns.setContentsMargins(16, 16, 16, 16)
        columns.setSpacing(16)
        options = QVBoxLayout()
        columns.addLayout(options, 1)

        automated = QGroupBox('Automated edits')
        edits = QVBoxLayout(automated)
        self.auto_accept = {}
        for rule, label in AUTO_ACCEPT_OPTIONS:
            self.auto_accept[rule] = checkbox = QCheckBox(label)
            edits.addWidget(checkbox)
        self.trailing_whitespace = QComboBox()
        self.trailing_whitespace.addItem('Keep', False)
        self.trailing_whitespace.addItem('Delete', True)
        trailing = QFormLayout()
        trailing.addRow('Trailing whitespace:', self.trailing_whitespace)
        edits.addLayout(trailing)
        options.addWidget(automated)

        models = QGroupBox('AI models')
        model_form = QFormLayout(models)
        self.ai_review_enabled = QCheckBox('Enable AI-assisted review')
        model_form.addRow(self.ai_review_enabled)
        self.ai_review_model = self._model_picker()
        model_form.addRow('AI review model:', self.ai_review_model)
        self.processing_model = self._model_picker()
        model_form.addRow('LLM processing model:', self.processing_model)
        self.processing_context = QLabel()
        self.processing_context.setTextFormat(Qt.PlainText)
        self.processing_context.setWordWrap(True)
        model_form.addRow('', self.processing_context)
        model_form.addRow('Transcription models:', QLabel('Gemini 3.5 Transcribe + Gemini 3.8 Flash'))
        options.addWidget(models)
        notices = QGroupBox('Notice PDFs')
        notice_options = QVBoxLayout(notices)
        self.recognize_file_number = QCheckBox('Auto recognize case number from notice PDF name')
        notice_options.addWidget(self.recognize_file_number)
        example = QLabel('261110thaler 1757905.pdf → File number 1757905')
        example.setWordWrap(True)
        notice_options.addWidget(example)
        options.addWidget(notices)
        options.addStretch()

        hotkeys = QGroupBox('Hotkeys')
        key_layout = QVBoxLayout(hotkeys)
        tabs = QTabWidget()
        key_layout.addWidget(tabs)
        profile_page = QWidget()
        tabs.addTab(profile_page, 'Case CATalyst')
        profile_layout = QVBoxLayout(profile_page)
        self.profile_name = QLabel()
        self.profile_name.setTextFormat(Qt.PlainText)
        profile_layout.addWidget(self.profile_name)

        actions = QHBoxLayout()
        choose = QToolButton()
        choose.setText('Import…')
        choose.setPopupMode(QToolButton.MenuButtonPopup)
        choose.clicked.connect(lambda: self.import_keyboard())
        menu = QMenu(choose)
        menu.addAction('Import keyboard with separate Macros folder…',
                       lambda: self.import_keyboard(choose_folder=True))
        choose.setMenu(menu)
        self.restore_defaults = QPushButton('Restore defaults')
        self.restore_defaults.clicked.connect(lambda: self._apply_profile(default_profile()))
        self.relink_macro = QPushButton('Relink macro…')
        self.relink_macro.clicked.connect(self._relink_macro)
        for button in (choose, self.relink_macro, self.restore_defaults):
            actions.addWidget(button)
        actions.addStretch()
        profile_layout.addLayout(actions)
        self.profile_error = QLabel()
        self.profile_error.setTextFormat(Qt.PlainText)
        self.profile_error.setWordWrap(True)
        self.profile_error.hide()
        profile_layout.addWidget(self.profile_error)
        self.profile_search = QLineEdit()
        self.profile_search.setPlaceholderText('Search keys, assignments or status')
        self.profile_search.setClearButtonEnabled(True)
        profile_layout.addWidget(self.profile_search)
        self.profile_table = QTableWidget(0, 3)
        self.profile_table.setHorizontalHeaderLabels(['Key', 'Assignment', 'Status'])
        self.profile_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.profile_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.profile_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.profile_table.setAlternatingRowColors(True)
        self.profile_table.verticalHeader().hide()
        self.profile_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.profile_table.horizontalHeader().setStretchLastSection(True)
        self.profile_table.setColumnWidth(0, 140)
        self.profile_table.setColumnWidth(1, 195)
        self.profile_table.setMinimumHeight(290)
        profile_layout.addWidget(self.profile_table)
        self.profile_status = QLabel()
        self.profile_status.setTextFormat(Qt.PlainText)
        self.profile_status.setWordWrap(True)
        profile_layout.addWidget(self.profile_status)
        self.profile_table.itemSelectionChanged.connect(self._show_selection)
        self.profile_search.textChanged.connect(self._filter_profile)
        self.space_playback = QCheckBox('Use Space to play or pause audio in Smart Keys mode')
        self.space_playback.toggled.connect(self._update_space_row)
        profile_layout.addWidget(self.space_playback)
        modes = QLabel('Press / to switch between Typing and Smart Keys. Use Ctrl+Shift+/ to type a slash.')
        modes.setWordWrap(True)
        profile_layout.addWidget(modes)
        self._app_keys = {'Ctrl+a': 'Select all', 'Ctrl+y': 'Redo', 'Ctrl+Shift+z': 'Redo'}
        file_actions = list(file_actions)
        review_actions = list(review_actions)
        for action in file_actions + review_actions:
            sequence = action.shortcut()
            if sequence.count() == 1:
                combination = sequence[0]
                key = event_key(QKeyEvent(QEvent.KeyPress, combination.key(),
                                          combination.keyboardModifiers()))
                self._app_keys[key] = action.text()

        shortcuts = QWidget()
        tabs.addTab(shortcuts, 'App shortcuts')
        key_form = QFormLayout(shortcuts)
        self.forward_seconds = QSpinBox()
        self.forward_seconds.setRange(1, 60)
        self.forward_seconds.setValue(DEFAULT_FORWARD_SECONDS)
        self.forward_seconds.setSuffix(' s')
        self._add_hotkeys(key_form, 'File', ((action.text(), action.shortcut())
            for action in file_actions if not action.shortcut().isEmpty()))
        self._add_hotkeys(key_form, 'Suggestion review', ((action.text(), action.shortcut())
            for action in review_actions))
        key_form.addRow('Fast forward by:', self.forward_seconds)
        self._add_hotkeys(key_form, 'Audio playback', ((label, QKeySequence(key))
            for label, key, _ in PLAYBACK_SHORTCUTS if key != 'Space'))
        self._add_hotkeys(key_form, 'Typing', ((label, QKeySequence(key)) for label, key in (
            ('Undo', QKeySequence.Undo), ('Redo', QKeySequence.Redo), ('Cut', QKeySequence.Cut),
            ('Copy', QKeySequence.Copy), ('Paste', QKeySequence.Paste), ('Select all', QKeySequence.SelectAll))))
        self._add_hotkeys(key_form, 'Format Symbols dialog', (
            *((label, QKeySequence(key.upper())) for label, key, _ in FormatSymbolDialog.SYMBOLS),
            ('Confirm symbol', QKeySequence('Enter')),
        ))
        columns.addWidget(hotkeys, 2)
        self.set_profile(default_profile())

    def set_profile(self, profile):
        self.profile = profile
        table = self.profile_table
        table.clearSelection()
        table.setRowCount(len(profile.bindings))
        self.profile_name.setText(f'{profile.name} · {len(profile.bindings)} keys')
        self.profile_error.clear()
        self.profile_error.hide()
        for i, binding in enumerate(profile.bindings):
            assignment = binding.value
            if binding.kind == 'macro':
                assignment = 'Macro: ' + assignment
            elif binding.kind == 'literal':
                assignment = 'Literal: ' + ('Space' if assignment == ' ' else repr(assignment))
            elif binding.kind == 'unassigned':
                assignment = 'Unassigned'
            for col, value in enumerate((binding.key, assignment, self._status(binding))):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                table.setItem(i, col, item)
        self._filter_profile(self.profile_search.text())
        self._show_selection()

    def _status(self, binding):
        reason = binding_dependency(binding)
        if binding.key == '<Space>' and self.space_playback.isChecked():
            return 'Overrides this assignment to play or pause audio in Smart Keys mode.'
        if binding.key == '/' and (binding.kind, binding.value) != ('command', 'Change Keyboard Mode'):
            return 'Reserved for switching between Typing and Smart Keys.'
        if binding.key == 'Ctrl+Shift+/' and (binding.kind, binding.value) != ('literal', '/'):
            return 'Reserved for typing a literal slash.'
        if reason:
            status = 'Unavailable: ' + reason
        elif binding.note:
            status = binding.note
        elif binding.kind == 'unassigned':
            status = 'Unassigned'
        elif binding.value in ('Play Audio', 'Stop Audio'):
            status = 'Requires attached audio'
        elif binding.value == 'Play Last Macro':
            status = 'Requires a previously played macro'
        else:
            status = 'Available'
        if action := self._app_keys.get(binding.key):
            if (binding.kind, binding.value) not in (('command', action), ('command', f'{action} File')):
                status += f' · Takes precedence over {action} in Smart Keys mode'
        if binding.key == 'Ctrl+Shift+0' and binding.kind != 'unassigned':
            status += ' · Windows may reserve this key for switching input languages.'
        return status

    def _update_space_row(self):
        for i, binding in enumerate(self.profile.bindings):
            if binding.key == '<Space>':
                item = self.profile_table.item(i, 2)
                status = self._status(binding)
                item.setText(status)
                item.setToolTip(status)
                self._filter_profile(self.profile_search.text())
                self._show_selection()
                break

    def _filter_profile(self, query):
        query = query.casefold()
        table = self.profile_table
        for row in range(table.rowCount()):
            match = any(query in table.item(row, i).text().casefold() for i in range(3))
            table.setRowHidden(row, not match)
        self._show_selection()

    def _show_selection(self):
        row = self.profile_table.currentRow()
        if row < 0 or row >= len(self.profile.bindings) or self.profile_table.isRowHidden(row):
            self.relink_macro.setEnabled(False)
            self.profile_status.clear()
            return
        binding = self.profile.bindings[row]
        self.relink_macro.setEnabled(binding.kind == 'macro')
        self.profile_status.setText(f'{binding.key} · {binding.value or "Unassigned"} · {self._status(binding)}')

    def _apply_profile(self, profile):
        self.set_profile(profile)
        self.profileChanged.emit(profile)

    def _error(self, error):
        self.profile_error.setText(str(error))
        self.profile_error.show()

    def import_keyboard(self, *, choose_folder=False):
        path, _ = QFileDialog.getOpenFileName(self, 'Import Case CATalyst keyboard', '',
                                              'Keyboard maps (*.sgkbd)')
        if not path:
            return
        folder = None
        if choose_folder:
            folder = QFileDialog.getExistingDirectory(self, 'Choose the Macros folder')
            if not folder:
                return
        try:
            profile = import_profile(path, folder)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return
        self._apply_profile(profile)

    def _relink_macro(self):
        row = self.profile_table.currentRow()
        if row < 0:
            return
        key = self.profile.bindings[row].key
        path, _ = QFileDialog.getOpenFileName(self, f'Relink macro for {key}', '', 'Macros (*.sgmac)')
        if not path:
            return
        try:
            profile = self.profile.relink(key, path)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return
        self._apply_profile(profile)

    @staticmethod
    def _model_picker():
        picker = QComboBox()
        for model, label in MODELS.items():
            picker.addItem(label, model)
        return picker

    @staticmethod
    def _add_hotkeys(form, title, bindings):
        heading = QLabel(title)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        heading.setContentsMargins(0, 6, 0, 0)
        form.addRow(heading)
        for label, key in bindings:
            form.addRow(label + ':', QLabel(key.toString(QKeySequence.NativeText)))
