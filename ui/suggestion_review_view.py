from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from transcript_pipeline.models import ReviewSession, SuggestionStatus
from ui.suggestion_card import SuggestionCard
from ui.styles import CAPTION_COLOR


class SuggestionReviewView(QScrollArea):
    suggestion_resolved = Signal(str, object)
    accept_all_requested = Signal()
    reject_all_requested = Signal()
    counts_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._session: ReviewSession | None = None
        self._cards: dict[str, SuggestionCard] = {}

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)

        self._empty_label = QLabel("No suggestions yet. Paste a transcript and click Analyze.")
        self._empty_label.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:12px;")
        self._layout.addWidget(self._empty_label)

        self._footer = QLabel("")
        self._footer.setStyleSheet(f"color:{CAPTION_COLOR}; font-size:11px;")
        self._layout.addWidget(self._footer)
        self._layout.addStretch(1)
        self.setWidget(self._container)

    def set_session(self, session: ReviewSession | None):
        self._session = session
        self._render()

    def session(self) -> ReviewSession | None:
        return self._session

    def _clear_cards(self):
        for card in self._cards.values():
            self._layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    def _render(self):
        self._clear_cards()

        if self._session is None or not self._session.suggestions:
            self._empty_label.show()
            self._footer.setText("")
            self.counts_changed.emit({"pending": 0, "accepted": 0, "rejected": 0})
            return

        self._empty_label.hide()

        for suggestion in self._session.suggestions:
            card = SuggestionCard(suggestion)
            card.resolved.connect(self._on_card_resolved)
            self._cards[suggestion.id] = card
            self._layout.insertWidget(self._layout.count() - 2, card)

        self._update_footer()

    def _on_card_resolved(self, suggestion_id: str, status: SuggestionStatus):
        if self._session is None:
            return
        self._session.resolve(suggestion_id, status)
        card = self._cards.get(suggestion_id)
        if card is not None:
            for suggestion in self._session.suggestions:
                if suggestion.id == suggestion_id:
                    card.update_suggestion(suggestion)
                    break
        self._update_footer()
        self.suggestion_resolved.emit(suggestion_id, status)

    def accept_all_pending(self):
        if self._session is None:
            return
        self._session.accept_all_pending()
        for suggestion in self._session.suggestions:
            card = self._cards.get(suggestion.id)
            if card is not None:
                card.update_suggestion(suggestion)
        self._update_footer()
        self.accept_all_requested.emit()

    def reject_all_pending(self):
        if self._session is None:
            return
        self._session.reject_all_pending()
        for suggestion in self._session.suggestions:
            card = self._cards.get(suggestion.id)
            if card is not None:
                card.update_suggestion(suggestion)
        self._update_footer()
        self.reject_all_requested.emit()

    def _update_footer(self):
        if self._session is None:
            return
        summary = self._session.summary()
        self._footer.setText(
            f"{summary['accepted']} accepted · "
            f"{summary['rejected']} rejected · "
            f"{summary['pending']} pending"
        )
        self.counts_changed.emit(summary)
