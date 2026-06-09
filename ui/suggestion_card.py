from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from transcript_pipeline.models import Suggestion, SuggestionStatus, SuggestionType
from ui.styles import ACTION_BAR_BG, CAPTION_COLOR, make_action_button, make_diff_row

_TYPE_LABELS = {
    SuggestionType.SPEAKER_CORRECTION: "Speaker Correction",
    SuggestionType.PUNCTUATION: "Punctuation",
    SuggestionType.CAPITALIZATION: "Capitalization",
    SuggestionType.FORMATTING: "Formatting",
    SuggestionType.TERMINOLOGY: "Terminology",
    SuggestionType.OTHER: "Other",
}


class SuggestionCard(QWidget):
    resolved = Signal(str, object)

    def __init__(self, suggestion: Suggestion, parent=None):
        super().__init__(parent)
        self.suggestion = suggestion

        mono = QFont("Courier New", 12)
        mono.setStyleHint(QFont.Monospace)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        self.setStyleSheet("background:#ffffff; border:1px solid #d0d7de; border-radius:4px;")

        header = QHBoxLayout()
        title = QLabel(_TYPE_LABELS.get(suggestion.type, suggestion.type.value))
        title.setStyleSheet("font-weight:600; font-size:13px;")
        confidence = QLabel(f"Confidence: {suggestion.confidence:.0%}")
        confidence.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:11px;")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(confidence)
        root.addLayout(header)

        root.addWidget(make_diff_row(suggestion.original_text, "delete", mono))
        root.addWidget(make_diff_row(suggestion.replacement_text, "insert", mono))

        reason = QLabel(f"Reason: {suggestion.reason}")
        reason.setWordWrap(True)
        reason.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:11px;")
        root.addWidget(reason)

        if suggestion.location.context_after:
            context = QLabel(f"Context: {suggestion.location.context_after}")
            context.setWordWrap(True)
            context.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:11px;")
            root.addWidget(context)

        bar = QWidget()
        bar.setStyleSheet(f"background:{ACTION_BAR_BG};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)
        bar_layout.setSpacing(6)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:11px;")

        self.accept_btn = make_action_button("\u2713 Accept", "accept")
        self.reject_btn = make_action_button("\u2717 Reject", "reject")
        self.accept_btn.clicked.connect(self._accept)
        self.reject_btn.clicked.connect(self._reject)

        bar_layout.addWidget(self.status_label)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self.accept_btn)
        bar_layout.addWidget(self.reject_btn)
        root.addWidget(bar)

        self._refresh_status()

    def _accept(self):
        self.resolved.emit(self.suggestion.id, SuggestionStatus.ACCEPTED)

    def _reject(self):
        self.resolved.emit(self.suggestion.id, SuggestionStatus.REJECTED)

    def update_suggestion(self, suggestion: Suggestion):
        self.suggestion = suggestion
        self._refresh_status()

    def _refresh_status(self):
        if self.suggestion.status == SuggestionStatus.PENDING:
            self.status_label.setText("Pending review")
            self.accept_btn.setEnabled(True)
            self.reject_btn.setEnabled(True)
            self.setStyleSheet("background:#ffffff; border:1px solid #d0d7de; border-radius:4px;")
            return

        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        if self.suggestion.status == SuggestionStatus.ACCEPTED:
            self.status_label.setText("Accepted")
            self.setStyleSheet(
                "background:#f6ffed; border:1px solid #1f883d; border-radius:4px;"
            )
        else:
            self.status_label.setText("Rejected")
            self.setStyleSheet(
                "background:#fff5f5; border:1px solid #cf222e; border-radius:4px;"
            )
