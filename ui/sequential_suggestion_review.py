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

from diff_view import _EqualBlock
from transcript_pipeline.apply_suggestions import apply_accepted_suggestion
from transcript_pipeline.models import (
    ReviewSession,
    Segment,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
)
from transcript_pipeline.parser import parse_zoom_line, serialize_zoom_segment, sync_document_source_text
from ui.styles import (
    ACTION_BAR_BG,
    CAPTION_COLOR,
    MARKER_WIDTH,
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


class _ActiveSuggestionHunk(QWidget):
    resolved = Signal(str, object)

    def __init__(
        self,
        segment: Segment,
        suggestion: Suggestion,
        font: QFont,
        body_start_line: int,
        parent=None,
    ):
        super().__init__(parent)
        self.segment = segment
        self.suggestion = suggestion
        self._body_start_line = body_start_line

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if segment.timestamp:
            layout.addWidget(self._timestamp_row(segment.timestamp, font))

        layout.addWidget(make_diff_row(f"- {suggestion.original_text}", "delete", font))
        layout.addWidget(make_diff_row(f"+ {suggestion.replacement_text}", "insert", font))

        meta = QLabel(
            f"{_TYPE_LABELS.get(suggestion.type, suggestion.type.value)} · "
            f"{suggestion.confidence:.0%}"
        )
        meta.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:11px; padding-left:{MARKER_WIDTH}px;")
        layout.addWidget(meta)

        if suggestion.reason:
            reason = QLabel(suggestion.reason)
            reason.setWordWrap(True)
            reason.setStyleSheet(
                f"color:{CAPTION_COLOR}; font-size:11px; padding-left:{MARKER_WIDTH}px;"
            )
            layout.addWidget(reason)

        bar = QWidget()
        bar.setStyleSheet(f"background:{ACTION_BAR_BG};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(MARKER_WIDTH, 3, 8, 3)
        bar_layout.setSpacing(6)

        caption = QLabel(_TYPE_LABELS.get(suggestion.type, suggestion.type.value))
        caption.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:11px;")

        accept = make_action_button("\u2713 Accept", "accept")
        reject = make_action_button("\u2717 Reject", "reject")
        accept.clicked.connect(self._accept)
        reject.clicked.connect(self._reject)

        bar_layout.addWidget(caption)
        bar_layout.addStretch(1)
        bar_layout.addWidget(accept)
        bar_layout.addWidget(reject)
        layout.addWidget(bar)

        self._body_block = _EqualBlock(
            [segment.text if segment.text else ""],
            font,
            body_start_line,
        )
        layout.addWidget(self._body_block)

    def body_block(self) -> _EqualBlock:
        return self._body_block

    def _timestamp_row(self, timestamp: str, font: QFont) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(MARKER_WIDTH, 0, 0, 0)
        layout.setSpacing(0)
        label = QLabel(timestamp)
        label.setFont(font)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(label)
        return row

    def _accept(self):
        self.resolved.emit(self.suggestion.id, SuggestionStatus.ACCEPTED)

    def _reject(self):
        self.resolved.emit(self.suggestion.id, SuggestionStatus.REJECTED)


class SequentialSuggestionReviewView(QScrollArea):
    """Step-through inline suggestion review with DiffView-style hunks."""

    suggestion_resolved = Signal(str, object)
    transcript_changed = Signal(str)
    counts_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._session: ReviewSession | None = None
        self._active_hunk: QWidget | None = None

        self._mono = QFont("Courier New", 12)
        self._mono.setStyleHint(QFont.Monospace)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
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

    def _segment_index(self) -> dict[str, int]:
        if self._session is None:
            return {}
        return {
            segment.id: index
            for index, segment in enumerate(self._session.document.segments)
        }

    def _first_pending(self) -> Suggestion | None:
        if self._session is None:
            return None
        order = self._segment_index()
        pending = sorted(self._session.pending(), key=lambda item: order.get(item.location.segment_id, 0))
        return pending[0] if pending else None

    def _clear_blocks(self):
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._active_hunk = None

    def _render(self):
        self._clear_blocks()

        if self._session is None or not self._session.document.segments:
            empty = QLabel("Paste a Zoom transcript and click Analyze Suggestions.")
            empty.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:12px; padding:12px;")
            self._layout.insertWidget(0, empty)
            self.counts_changed.emit({"pending": 0, "accepted": 0, "rejected": 0})
            return

        active = self._first_pending()
        insert_at = 0
        line_no = 1

        for segment in self._session.document.segments:
            if active is not None and active.location.segment_id == segment.id:
                body_line = line_no + (1 if segment.timestamp else 0)
                hunk = _ActiveSuggestionHunk(segment, active, self._mono, body_line)
                hunk.resolved.connect(self._on_resolved)
                hunk.body_block().saved.connect(
                    lambda lines, seg_id=segment.id: self._on_body_block_saved(seg_id, lines)
                )
                hunk.body_block().needs_rerender.connect(self._render)
                self._layout.insertWidget(insert_at, hunk)
                self._active_hunk = hunk
                insert_at += 1
                line_no += 2 if segment.timestamp else 1
                continue

            line = serialize_zoom_segment(segment)
            block = _EqualBlock([line], self._mono, line_no)
            block.saved.connect(
                lambda lines, seg_id=segment.id: self._on_equal_block_saved(seg_id, lines)
            )
            block.needs_rerender.connect(self._render)
            self._layout.insertWidget(insert_at, block)
            insert_at += 1
            line_no += 1

        self._emit_counts()

        if self._active_hunk is not None:
            self.ensureWidgetVisible(self._active_hunk)

    def _find_segment(self, segment_id: str) -> Segment | None:
        if self._session is None:
            return None
        for segment in self._session.document.segments:
            if segment.id == segment_id:
                return segment
        return None

    def _apply_line_to_segment(self, segment: Segment, line: str) -> None:
        timestamp, speaker, text = parse_zoom_line(line)
        if speaker is not None:
            segment.timestamp = timestamp
            segment.speaker = speaker
            segment.text = text
        else:
            segment.text = text

    def _on_equal_block_saved(self, segment_id: str, lines: list[str]):
        segment = self._find_segment(segment_id)
        if segment is None or self._session is None:
            return
        self._apply_line_to_segment(segment, "\n".join(lines))
        sync_document_source_text(self._session.document)
        self.transcript_changed.emit(self._session.document.source_text)

    def _on_body_block_saved(self, segment_id: str, lines: list[str]):
        segment = self._find_segment(segment_id)
        if segment is None or self._session is None:
            return
        segment.text = "\n".join(lines).strip()
        sync_document_source_text(self._session.document)
        self.transcript_changed.emit(self._session.document.source_text)

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
