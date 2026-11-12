"""Review controls shared by list and page presentation."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from app.src.suggestions import suggestions


class ReviewView(QScrollArea):
    requested = Signal(int, bool)
    selected = Signal(int)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.changes = []
        self.cards = []
        self.current = 0

    @property
    def has_changes(self):
        return bool(self.changes)

    def set_revisions(self, original, incoming):
        self.changes = suggestions(original, incoming)
        root = QWidget()
        layout = QVBoxLayout(root)
        self.cards = []
        for index, change in enumerate(self.changes):
            card = QWidget()
            rows = QVBoxLayout(card)
            before = '\n'.join(original.text[a:b] for a, b, _, _ in change.ranges)
            after = '\n'.join(incoming.text[c:d] for _, _, c, d in change.ranges)
            if change.kind == 'metadata':
                before, after = 'Existing field/symbol definitions', 'Proposed field/symbol definitions'
            for text, color in ((before or '(insertion)', '#ffd7d5'), (after or '(deletion)', '#ccffd8')):
                label = QLabel(text)
                label.setWordWrap(True)
                label.setStyleSheet(f'background:{color}; color:#24292f; padding:4px;')
                rows.addWidget(label)
            buttons = QHBoxLayout()
            for caption, callback in (('Show', lambda _, i=index: self.select(i)),
                                      ('Accept', lambda _, i=index: self.requested.emit(i, True)),
                                      ('Reject', lambda _, i=index: self.requested.emit(i, False))):
                button = QPushButton(caption)
                button.clicked.connect(callback)
                buttons.addWidget(button)
            rows.addLayout(buttons)
            layout.addWidget(card)
            self.cards.append(card)
        layout.addStretch()
        old = self.takeWidget()
        if old:
            old.deleteLater()
        self.setWidget(root)
        self.current = min(self.current, max(0, len(self.changes)-1))

    def select(self, index):
        if 0 <= index < len(self.changes):
            self.current = index
            self.ensureWidgetVisible(self.cards[index])
            self.selected.emit(index)

    def center_line(self):
        return self.current

    def scroll_to_center_line(self, line):
        self.select(min(line, len(self.changes)-1))
