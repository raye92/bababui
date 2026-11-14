"""One exact review decision with fixed navigation and speaker evidence."""
from html import escape
import re
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QToolButton, QComboBox, QProgressBar)
from app.src.casecat.fields import field_values


def visible_text(text, empty):
    if not text:
        return empty
    if not text.strip():
        return text.replace(' ', '·').replace('\t', '⇥').replace('\n', '↵\n')
    return text.replace('\n', ' ↵\n')


def change_diff(change):
    """Flow exact removed/added ranges through one copy of their context."""
    original, incoming = change.original.text, change.incoming.text
    if not change.ranges:
        before, after = dict(change.original.definitions), dict(change.incoming.definitions)
        names = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        if names:
            return [('change', escape(name)+': '+_highlight(before.get(name, '(undefined)'), False)
                     +_highlight(after.get(name, '(undefined)'), True)) for name in names]
        return [('change', _highlight('Existing native fields and symbols', False)+' '
                 +_highlight('Proposed native fields and symbols', True))]
    # Linked fields can occur far apart. Keep their paragraphs separate, but
    # apply every linked occurrence within a displayed paragraph together.
    spans = []
    for span in change.ranges:
        if spans and (not change.field or '\n' not in original[spans[-1][-1][1]:span[0]]):
            spans[-1].append(span)
        else:
            spans.append([span])
    rows = []
    for group in spans:
        if not group:
            continue
        left = original.rfind('\n', 0, group[0][0]) + 1
        right = original.find('\n', group[-1][1])
        right = len(original) if right < 0 else right
        prefix = suffix = ''
        before = list(re.finditer(r'\S+', original[left:group[0][0]]))
        after = list(re.finditer(r'\S+', original[group[-1][1]:right]))
        if len(before) > 8:
            left += before[-8].start()
            prefix = '… '
        if len(after) > 8:
            right = group[-1][1]+after[7].end()
            suffix = ' …'
        parts = [escape(prefix)]
        position = left
        for a, b, c, d in group:
            parts.extend((escape(original[position:a]), _highlight(original[a:b], False),
                          _highlight(incoming[c:d], True)))
            position = b
        parts.append(escape(original[position:right]+suffix))
        rows.append(('change', ''.join(parts)))
    return rows


def _highlight(text, incoming):
    if not text:
        return ''
    background, foreground = ('#ccffd8', '#116329') if incoming else ('#ffd7d5', '#82071e')
    value = escape(visible_text(text, ''))
    return f'<b style="background:{background}; color:{foreground}">{value}</b>'


class ReviewCard(QWidget):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ReviewView(QWidget):
    requested = Signal(int, bool)
    selected = Signal(int)
    mapping_requested = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.changes, self.cards, self.visible_indices = [], [], []
        self.current = 0
        self.speaker_filter = None
        self.review = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 4, 8, 4)
        self.count = QLabel()
        self.summary = QToolButton(self)
        self.summary.setCheckable(True)
        self.summary.setChecked(True)
        self.summary.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.summary.setArrowType(Qt.DownArrow)
        self.layout.addWidget(self.summary)
        self.speaker_box = QWidget()
        self.layout.addWidget(self.speaker_box)
        self.summary.toggled.connect(self.speaker_box.setVisible)
        self.summary.toggled.connect(lambda on: self.summary.setArrowType(Qt.DownArrow if on else Qt.RightArrow))
        self.all_button = QPushButton('Show all suggestions')
        self.all_button.clicked.connect(lambda: self.filter_speaker(None))
        self.layout.addWidget(self.all_button)
        self.layout.addWidget(self.count)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.layout.addWidget(self.scroll, 1)
        navigation = QHBoxLayout()
        self.navigation_buttons = []
        for caption, delta in (('Previous', -1), ('Next', 1)):
            button = QPushButton(caption)
            button.clicked.connect(lambda _, step=delta: self.navigate(step))
            navigation.addWidget(button)
            self.navigation_buttons.append(button)
        self.layout.addLayout(navigation)

    @property
    def has_changes(self):
        return bool(self.changes)

    def set_revisions(self, original, incoming, *, review=None, page_lines=()):
        """Compatibility entry point for isolated review previews."""
        from app.src.review_model import build_review
        self.set_model(build_review(original, incoming), review=review, page_lines=page_lines)

    def set_model(self, model, *, review=None, page_lines=()):
        self.model = model
        self.changes = model.edits
        self.review = review
        original, incoming = model.original, model.incoming
        self.original, self.incoming = original, incoming
        self._speakers(original)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.cards = []
        for index, change in enumerate(self.changes):
            card = ReviewCard()
            card.clicked.connect(lambda i=index, snapshot=model:
                                 self.select(i) if self.model is snapshot else None)
            card.setObjectName(f'suggestion{index}')
            rows = QVBoxLayout(card)
            rows.setContentsMargins(8, 6, 8, 6)
            rows.setSpacing(6)
            before = '\n'.join(original.text[a:b] for a, b, _, _ in change.ranges)
            after = '\n'.join(incoming.text[c:d] for _, _, c, d in change.ranges)
            title = 'Speaker attribution' if self._speaker_for(change) else 'Linked field' if change.field else 'Wording'
            if change.kind == 'metadata':
                title = 'Native fields and symbols'
            if change.kind == 'structure':
                title = 'Insert paragraph break' if after.count('\n') > before.count('\n') else 'Join paragraphs' if before.count('\n') > after.count('\n') else 'Paragraph change'
            if change.ranges:
                start = change.ranges[0][0]
                qt_start = len(original.text[:start].encode('utf-16-le')) // 2
                line = next((p for p in reversed(page_lines) if p.position <= qt_start), None)
                if line:
                    title += f' · Page {line.page}, line {line.number}'
            heading = QLabel(title)
            heading.setWordWrap(True)
            rows.addWidget(heading)
            if change.field:
                rows.addWidget(QLabel(f'{len(change.ranges)} linked occurrences'))
            for _, text in change_diff(change):
                text = text.replace('\n', '<br>')
                label = QLabel(f'<span style="white-space:pre-wrap">{text}</span>')
                label.setObjectName('comparison')
                label.setTextFormat(Qt.RichText)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.NoTextInteraction)
                label.setStyleSheet('padding:4px;')
                rows.addWidget(label)
            buttons = QHBoxLayout()
            for caption, keep in (('Keep', True), ('Undo', False)):
                button = QPushButton(caption)
                button.clicked.connect(lambda _, i=index, accepted=keep, snapshot=model:
                                       self.requested.emit(i, accepted) if self.model is snapshot else None)
                button.setToolTip('Keep the proposed change.' if keep else 'Restore the original wording for this change.')
                color = '#1f883d' if keep else '#cf222e'
                button.setStyleSheet(f'background:{color}; color:white; padding:4px; border-radius:3px;')
                buttons.addWidget(button)
            rows.addLayout(buttons)
            layout.addWidget(card)
            self.cards.append(card)
        layout.addStretch()
        old = self.scroll.takeWidget()
        if old:
            old.deleteLater()
        self.scroll.setWidget(root)
        self.current = min(self.current, max(0, len(self.changes)-1))
        self.filter_speaker(self.speaker_filter, select=False)
        self._mark_selected()

    def _speakers(self, original):
        old = self.speaker_box
        box = QWidget()
        rows = QVBoxLayout(box)
        rows.setContentsMargins(0, 0, 0, 0)
        summaries = (self.review or {}).get('evidence', {}).get('speakers', {})
        total_matches = 0
        values = field_values(original)
        names = sorted(value for value in set(values.values()) if value and sum(v == value for v in values.values()) == 1 and any(e.kind == 'field' and e.name in values and values[e.name] == value for e in original.elements))
        for speaker, summary in summaries.items():
            mapped = self.review.get('overrides', {}).get(speaker, summary['mapped'])
            leading = mapped or summary['leader']
            matches = summary['counts'].get(leading, 0)
            mismatches = sum(summary['counts'].values())-matches
            total_matches += matches
            label = QLabel(f'{speaker} → {mapped or "Unresolved"}' + (f' (leading: {leading})' if not mapped and leading else ''))
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            rows.addWidget(label)
            combo = QComboBox()
            combo.addItem('Keep generic label', None)
            for name in names:
                combo.addItem(name, name)
            combo.setCurrentIndex(max(0, combo.findData(mapped)))
            combo.activated.connect(lambda i, s=speaker, c=combo: self.mapping_requested.emit(s, c.itemData(i)))
            rows.addWidget(combo)
            bar = QProgressBar()
            bar.setRange(0, max(1, matches+mismatches))
            bar.setValue(matches)
            bar.setFormat(f'{matches} matches · {mismatches} mismatches')
            bar.setToolTip('Agreement with existing labels, not verified identity.\n'+'\n'.join(f'{n}: {v}' for n,v in summary['counts'].items()))
            rows.addWidget(bar)
            if summary['unresolved']:
                rows.addWidget(QLabel(f'{summary["unresolved"]} unaligned occurrences'))
            button = QPushButton('Review attribution differences')
            button.clicked.connect(lambda _, s=speaker: self.filter_speaker(s))
            rows.addWidget(button)
        self.layout.replaceWidget(old, box)
        self.speaker_box = box
        old.deleteLater()
        box.setVisible(bool(summaries) and self.summary.isChecked())
        self.summary.setVisible(bool(summaries))
        self.summary.setText(f'Speakers · {total_matches} matches')
        try:
            self.summary.toggled.disconnect()
        except RuntimeError:
            pass
        self.summary.toggled.connect(box.setVisible)
        self.summary.toggled.connect(lambda on: self.summary.setArrowType(Qt.DownArrow if on else Qt.RightArrow))

    def _speaker_for(self, change):
        if not self.review:
            return None
        for location in self.review.get('locations', []):
            if not location['resolved'] and any(c < location['end'] and d > location['start'] for _,_,c,d in change.ranges):
                return location['speaker']
        if self.review.get('locations'):
            return None
        # Useful for isolated evidence previews before positions are attached.
        for speaker, summary in self.review['evidence']['speakers'].items():
            mapped = self.review.get('overrides', {}).get(speaker, summary['mapped'])
            if mapped and any(self.incoming.text[c:d] == mapped and self.original.text[a:b] != mapped for a,b,c,d in change.ranges):
                return speaker
        return None

    def filter_speaker(self, speaker, *, select=True):
        self.speaker_filter = speaker
        self.visible_indices = [i for i,c in enumerate(self.changes) if speaker is None or self._speaker_for(c) == speaker]
        for i,card in enumerate(self.cards):
            card.setVisible(i == self.current and i in self.visible_indices)
        if self.visible_indices and self.current not in self.visible_indices:
            self.current = self.visible_indices[0]
        self._mark_selected()
        self.all_button.setVisible(speaker is not None)
        self.count.setText(f'{len(self.changes)} suggestions remaining' + (f' · {len(self.visible_indices)} shown' if speaker else ''))
        if select and self.visible_indices:
            self.select(self.visible_indices[0])

    def navigate(self, step):
        if self.visible_indices:
            index = self.visible_indices.index(self.current) if self.current in self.visible_indices else -1
            self.select(self.visible_indices[(index+step) % len(self.visible_indices)])

    def _mark_selected(self):
        for button in self.navigation_buttons:
            button.setEnabled(len(self.visible_indices) > 1)
        for i,card in enumerate(self.cards):
            card.setVisible(i == self.current and i in self.visible_indices)
            card.setStyleSheet(f'QWidget#suggestion{i} {{ border-left: 3px solid #91bce9; }}' if i == self.current else '')

    def select(self, index):
        if 0 <= index < len(self.changes):
            if index not in self.visible_indices:
                self.filter_speaker(None, select=False)
            self.current = index
            self._mark_selected()
            self.scroll.ensureWidgetVisible(self.cards[index])
            self.selected.emit(index)

    def center_line(self): return self.current
    def scroll_to_center_line(self, line): self.select(min(line, len(self.changes)-1))
