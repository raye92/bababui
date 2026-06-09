from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from transcript_pipeline.apply_suggestions import apply_accepted_suggestion
from transcript_pipeline.models import (
    ReviewSession,
    Segment,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
    suggestion_sort_key,
)
from transcript_pipeline.parser import serialize_zoom_segment, sync_document_source_text
from ui.styles import (
    ACTION_BAR_BG,
    CAPTION_COLOR,
    make_action_button,
    make_diff_row,
)

_TYPE_LABELS = {
    SuggestionType.SPEAKER_CORRECTION: "Speaker correction",
    SuggestionType.PUNCTUATION: "Punctuation",
    SuggestionType.CAPITALIZATION: "Capitalization",
    SuggestionType.FORMATTING: "Formatting",
    SuggestionType.TERMINOLOGY: "Terminology",
    SuggestionType.OTHER: "Other",
}


def _bracketed_diff_row(text: str, kind: str, font: QFont) -> QWidget:
    label = f"[- {text} -]" if kind == "delete" else f"[+ {text} +]"
    return make_diff_row(label, kind, font)


class _InlineSuggestionBlock(QWidget):
    resolved = Signal(str, object)

    def __init__(self, segment: Segment, suggestion: Suggestion, font: QFont, parent=None):
        super().__init__(parent)
        self.segment = segment
        self.suggestion = suggestion

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        if segment.timestamp:
            timestamp = QLabel(segment.timestamp)
            timestamp.setFont(font)
            timestamp.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(timestamp)

        caption = QLabel(
            f"{_TYPE_LABELS.get(suggestion.type, suggestion.type.value)} · "
            f"Confidence: {suggestion.confidence:.0%}"
        )
        caption.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:11px;")
        layout.addWidget(caption)

        layout.addWidget(_bracketed_diff_row(suggestion.original_text, "delete", font))
        layout.addWidget(_bracketed_diff_row(suggestion.replacement_text, "insert", font))

        body = QLabel(segment.text if segment.text else " ")
        body.setFont(font)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)

        if suggestion.reason:
            reason = QLabel(suggestion.reason)
            reason.setWordWrap(True)
            reason.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:11px;")
            layout.addWidget(reason)

        bar = QWidget()
        bar.setStyleSheet(f"background:{ACTION_BAR_BG};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 4, 8, 4)
        bar_layout.setSpacing(6)
        bar_layout.addStretch(1)

        accept = make_action_button("\u2713 Accept", "accept")
        reject = make_action_button("\u2717 Reject", "reject")
        accept.clicked.connect(self._accept)
        reject.clicked.connect(self._reject)
        bar_layout.addWidget(accept)
        bar_layout.addWidget(reject)
        layout.addWidget(bar)

    def _accept(self):
        self.resolved.emit(self.suggestion.id, SuggestionStatus.ACCEPTED)

    def _reject(self):
        self.resolved.emit(self.suggestion.id, SuggestionStatus.REJECTED)


class _PlainSegmentBlock(QWidget):
    def __init__(self, line: str, font: QFont, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        label = QLabel(line if line else " ")
        label.setFont(font)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(label)


class InlineSuggestionReviewView(QScrollArea):
    """Primary Zoom transcript review surface with inline suggestions."""

    suggestion_resolved = Signal(str, object)
    transcript_changed = Signal(str)
    counts_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._session: ReviewSession | None = None

        self._mono = QFont("Courier New", 12)
        self._mono.setStyleHint(QFont.Monospace)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self.setWidget(self._container)

    def set_session(self, session: ReviewSession | None):
        self._session = session
        self._render()

    def session(self) -> ReviewSession | None:
        return self._session

    def canonical_transcript(self) -> str:
        if self._session is None:
            return ""
        return self._session.document.source_text

    def accept_all_pending(self):
        if self._session is None:
            return
        for suggestion in list(self._session.pending()):
            suggestion.status = SuggestionStatus.ACCEPTED
            apply_accepted_suggestion(self._session.document, suggestion)
        sync_document_source_text(self._session.document)
        self.transcript_changed.emit(self._session.document.source_text)
        self._render()

    def reject_all_pending(self):
        if self._session is None:
            return
        self._session.reject_all_pending()
        self._render()

    def _clear_blocks(self):
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _suggestions_for_segment(self, segment_id: str) -> list[Suggestion]:
        if self._session is None:
            return []
        return sorted(
            [
                suggestion
                for suggestion in self._session.suggestions
                if suggestion.location.segment_id == segment_id
            ],
            key=suggestion_sort_key,
        )

    def _pending_suggestion(self, segment_id: str) -> Suggestion | None:
        for suggestion in self._suggestions_for_segment(segment_id):
            if suggestion.status == SuggestionStatus.PENDING:
                return suggestion
        return None

    def _render(self):
        self._clear_blocks()

        if self._session is None or not self._session.document.segments:
            empty = QLabel("Paste a Zoom transcript and click Analyze Suggestions.")
            empty.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:12px;")
            self._layout.insertWidget(0, empty)
            self.counts_changed.emit({"pending": 0, "accepted": 0, "rejected": 0})
            return

        insert_at = 0
        for segment in self._session.document.segments:
            pending = self._pending_suggestion(segment.id)

            if pending is not None:
                block = _InlineSuggestionBlock(segment, pending, self._mono)
                block.resolved.connect(self._on_resolved)
                self._layout.insertWidget(insert_at, block)
                insert_at += 1
                continue

            line = serialize_zoom_segment(segment)
            self._layout.insertWidget(insert_at, _PlainSegmentBlock(line, self._mono))
            insert_at += 1

        self._emit_counts()

    def _on_resolved(self, suggestion_id: str, status: SuggestionStatus):
        if self._session is None:
            return

        self._session.resolve(suggestion_id, status)
        suggestion = next(
            (item for item in self._session.suggestions if item.id == suggestion_id),
            None,
        )
        if suggestion is None:
            return

        if status == SuggestionStatus.ACCEPTED:
            apply_accepted_suggestion(self._session.document, suggestion)
            sync_document_source_text(self._session.document)
            self.transcript_changed.emit(self._session.document.source_text)

        self._render()
        self.suggestion_resolved.emit(suggestion_id, status)

    def _emit_counts(self):
        if self._session is None:
            self.counts_changed.emit({"pending": 0, "accepted": 0, "rejected": 0})
            return
        self.counts_changed.emit(self._session.summary())
