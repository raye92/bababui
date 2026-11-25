"""Choose which parts of an existing recording to process again."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel,
                               QRadioButton, QVBoxLayout, QWidget)

from app.src.jobs import RunSteps


class RerunDialog(QDialog):
    def __init__(self, recording, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Reprocess recording')
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(6)

        heading = QLabel('Run BABABUI again?')
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        filename = QLabel(recording)
        filename.setTextFormat(Qt.PlainText)
        filename.setWordWrap(True)
        layout.addWidget(filename)
        layout.addSpacing(10)

        self.clean = QRadioButton('Clean fresh rerun')
        self.custom = QRadioButton('Choose steps')
        self.clean.setChecked(True)
        layout.addWidget(self.clean)
        explanation = QLabel('Delete the cached files for this recording and run all three steps.')
        explanation.setWordWrap(True)
        explanation.setContentsMargins(21, 0, 0, 0)
        layout.addWidget(explanation)
        layout.addSpacing(8)
        layout.addWidget(self.custom)

        choices = QWidget()
        options = QVBoxLayout(choices)
        options.setContentsMargins(21, 0, 0, 0)
        options.setSpacing(6)
        self.transcribe = QCheckBox('Transcription')
        self.format = QCheckBox('Formatting')
        self.review = QCheckBox('Automated review')
        for checkbox, tip in (
            (self.transcribe, 'Transcribe the audio again and save a new raw transcript.'),
            (self.format, 'Format the new or saved raw transcript into Incoming.'),
            (self.review, 'Review the edits in Incoming using your automated edit settings.'),
        ):
            checkbox.setChecked(True)
            checkbox.setToolTip(tip)
            checkbox.setAccessibleDescription(tip)
            options.addWidget(checkbox)
            checkbox.toggled.connect(self._update_action)
        layout.addWidget(choices)
        choices.setEnabled(False)
        self.custom.toggled.connect(choices.setEnabled)
        self.custom.toggled.connect(self._update_action)
        dependency = QLabel('Formatting always runs automated review.')
        dependency.setWordWrap(True)
        dependency.setContentsMargins(21, 0, 0, 0)
        layout.addWidget(dependency)
        layout.addSpacing(12)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.run_button = buttons.button(QDialogButtonBox.Ok)
        self.run_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_action()
        self.clean.setFocus()

    def _update_action(self):
        clean = self.clean.isChecked()
        if self.format.isChecked():
            self.review.setChecked(True)
        self.review.setEnabled(not self.format.isChecked())
        self.run_button.setText('Start clean rerun' if clean else 'Run selected steps')
        self.run_button.setEnabled(clean or any(box.isChecked() for box in (self.transcribe, self.format, self.review)))

    @classmethod
    def choose(cls, parent, recording):
        dialog = cls(recording, parent)
        try:
            if dialog.exec() != QDialog.Accepted:
                return None
            if dialog.clean.isChecked():
                return RunSteps(audio_cache='clean')
            transcribe = dialog.transcribe.isChecked()
            return RunSteps(transcribe, dialog.format.isChecked(), dialog.review.isChecked(),
                            'refresh' if transcribe else 'reuse')
        finally:
            dialog.deleteLater()
