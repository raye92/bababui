"""Settings and keyboard reference in the editor's tab strip."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from app.src.native_dialogs import FormatSymbolDialog
from app.src.playback import DEFAULT_FORWARD_SECONDS, PLAYBACK_SHORTCUTS
from app.src.processing import MODELS


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
        model_form.addRow('Transcription model:', QLabel('Gemini 3.5 Transcribe'))
        options.addWidget(models)
        options.addStretch()

        hotkeys = QGroupBox('Hotkeys')
        key_form = QFormLayout(hotkeys)
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
            for label, key, _ in PLAYBACK_SHORTCUTS))
        self._add_hotkeys(key_form, 'Transcript editing', ((label, QKeySequence(key)) for label, key in (
            ('Undo', QKeySequence.Undo), ('Redo', QKeySequence.Redo), ('Cut', QKeySequence.Cut),
            ('Copy', QKeySequence.Copy), ('Paste', QKeySequence.Paste), ('Select all', QKeySequence.SelectAll))))
        self._add_hotkeys(key_form, 'Format Symbols dialog', (
            *((label, QKeySequence(key.upper())) for label, key, _ in FormatSymbolDialog.SYMBOLS),
            ('Confirm symbol', QKeySequence('Enter')),
        ))
        columns.addWidget(hotkeys, 1, Qt.AlignTop)

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
