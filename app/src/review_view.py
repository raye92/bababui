"""One review decision with its preview and speaker evidence."""
from bisect import bisect_right
from collections import Counter
from html import escape
from PySide6.QtCore import QEvent, QRectF, Signal, Qt
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import (QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QFrame, QLabel, QPushButton, QToolButton, QComboBox, QProgressBar, QSizePolicy)
from app.src.suggestion_filter import LABEL, speaker_choices, speaker_name_key
from app.src.suggestions import preview_context, preview_ranges, preview_start
from app.src.speech_alignment import WORD


def visible_text(text, empty):
    if not text:
        return empty
    if not text.strip():
        return text.replace(' ', '·').replace('\t', '⇥').replace('\n', '↵\n')
    return text.replace('\n', ' ↵\n')


def change_diff(change):
    """Show whole-word replacements and preserve exact structural edits."""
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
    for span in preview_ranges(change):
        if spans and (not change.field or '\n' not in original[spans[-1][-1][1]:span[0]]):
            spans[-1].append(span)
        else:
            spans.append([span])
    rows = []
    for group in spans:
        if not group:
            continue
        position = group[0][0]
        prefix, suffix = preview_context(original, position, group[-1][1])
        parts = [escape(prefix)]
        for a, b, c, d in group:
            parts.extend((escape(original[position:a]), _highlight(original[a:b], False, a),
                          _highlight(incoming[c:d], True, c)))
            position = b
        parts.append(escape(suffix))
        rows.append(('change', ''.join(parts)))
    return rows


def _highlight(text, incoming, start=None):
    if not text:
        return ''
    background, foreground = ('#ccffd8', '#116329') if incoming else ('#ffd7d5', '#82071e')
    parts, offset = [], 0
    if start is not None:
        side = 'incoming' if incoming else 'original'
        for word in WORD.finditer(text):
            parts.append(escape(text[offset:word.start()]))
            parts.append(f'<a href="{side}:{start + word.start()}" style="color:{foreground}; '
                         f'text-decoration:none">{escape(word.group())}</a>')
            offset = word.end()
    parts.append(escape(text[offset:]))
    value = visible_text(''.join(parts), '')
    return f'<b style="background:{background}; color:{foreground}">{value}</b>'


class ReviewCard(QWidget):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class SpeakerCombo(QComboBox):
    def event(self, event):
        if (event.type() == QEvent.ShortcutOverride and event.modifiers() == Qt.NoModifier
                and event.text().isalpha()):
            # Keep letter keys for speaker lookup while this control has focus.
            event.accept()
            return True
        return super().event(event)

    def wheelEvent(self, event):
        # Wheel motion over the closed control scrolls the speaker list.
        event.ignore()


class SpeakerMatchBar(QProgressBar):
    def paintEvent(self, event):
        fraction = max(0, self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = bounds.height() / 2
        track = QPainterPath()
        track.addRoundedRect(bounds, radius, radius)
        accent = self.palette().accent().color()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(accent)
        painter.drawPath(track)
        painter.setClipRect(QRectF(0, 0, self.width() * fraction, self.height()))
        painter.fillPath(track, accent)


def _attribution_edits(model, locations, needs_check, mappings):
    """Find pending label replacements and uncertain labels in the actual diff."""
    pending = [p for p in locations if not p['resolved'] and p['start'] < p['end']]
    assigned = {(p['start'], p['end']): p['speaker'] for p in pending}
    uncertain = sorted((p for p in pending if p['speaker'] in needs_check), key=lambda p: p['start'])
    ends = [p['end'] for p in uncertain]
    original, incoming = model.original.text, model.incoming.text
    by_speaker = {}
    for index, edit in enumerate(model.edits):
        if edit.kind == 'speaker' and len(edit.ranges) == 1:
            _, _, start, end = edit.ranges[0]
            speaker = assigned.get((start, end))
            if speaker is None:
                # A formatter can also supply a name directly, without a numbered tag.
                name = speaker_name_key(incoming[start:end])
                candidates = [key for key, value in mappings.items() if value and speaker_name_key(value) == name]
                speaker = candidates[0] if len(candidates) == 1 else None
            if speaker:
                by_speaker.setdefault(speaker, set()).add(index)
            continue
        for a, b, c, d in edit.ranges:
            if c == d:
                continue
            first = bisect_right(ends, c)
            for i in range(first, len(uncertain)):
                location = uncertain[i]
                start, end = location['start'], location['end']
                if start >= d:
                    break
                speaker = location['speaker']
                current = speaker_name_key(incoming[start:end])
                observed = location.get('original_name')
                if observed and speaker_name_key(observed) == current:
                    continue
                line_start = original.rfind('\n', 0, a) + 1
                line_end = original.find('\n', a)
                before = LABEL.match(original[line_start:line_end if line_end >= 0 else len(original)])
                if before and incoming.rfind('\n', 0, c) == incoming.rfind('\n', 0, start):
                    label_start, label_end = (line_start + pos for pos in before.span('name'))
                    if (a < label_end and b > label_start) or (a == b and label_start <= a <= label_end):
                        if speaker_name_key(before['name']) == current:
                            continue
                by_speaker.setdefault(speaker, set()).add(index)
    return by_speaker


class ReviewView(QWidget):
    requested = Signal(int, bool)
    selected = Signal(int)
    selection_changed = Signal()
    navigated = Signal()
    passage_clicked = Signal(str, int)
    mapping_requested = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.changes, self.cards, self.visible_indices = [], [], []
        self.current = 0
        self.speaker_filter = None
        self.review = self._shown_review = None
        self.speaker_edits = {}
        self.needs_review = frozenset()
        self.unmatched_speaker_ranges = ()
        self.live_location = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 4, 8, 4)
        self.count = QLabel()
        self.summary = QToolButton(self)
        self.summary.setCheckable(True)
        self.summary.setChecked(True)
        self.summary.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.summary.setArrowType(Qt.DownArrow)
        self.layout.addWidget(self.summary)
        self.speaker_scroll = QScrollArea()
        self.speaker_scroll.setFrameShape(QFrame.NoFrame)
        self.speaker_scroll.setWidgetResizable(True)
        self.speaker_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.speaker_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.speaker_scroll.hide()
        self.layout.addWidget(self.speaker_scroll, 2)
        self.summary.toggled.connect(self.speaker_scroll.setVisible)
        self.summary.toggled.connect(lambda on: self.summary.setArrowType(Qt.DownArrow if on else Qt.RightArrow))
        self.all_button = QPushButton('Show all suggestions')
        self.all_button.clicked.connect(lambda: self.filter_speaker(None))
        self.layout.addWidget(self.all_button)
        self.layout.addWidget(self.count)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.layout.addWidget(self.scroll, 1)
        decisions = QHBoxLayout()
        self.decision_buttons = []
        for caption, accept, key in (('Accept', True, 'Alt+A'), ('Reject', False, 'Alt+D')):
            button = QPushButton(caption)
            button.setEnabled(False)
            button.clicked.connect(lambda _, accepted=accept: self.request_current(accepted))
            description = 'Apply the proposed change' if accept else 'Keep the original for this change'
            button.setToolTip(f'{description} ({key}).')
            color = '#1f883d' if accept else '#cf222e'
            button.setStyleSheet('QPushButton { padding: 4px; border-radius: 3px; } '
                                 f'QPushButton:enabled {{ background: {color}; color: white; }}')
            decisions.addWidget(button)
            self.decision_buttons.append(button)
        self.layout.addLayout(decisions)
        navigation = QHBoxLayout()
        self.navigation_buttons = []
        for caption, delta in (('Previous', -1), ('Next', 1)):
            button = QPushButton(caption)
            button.clicked.connect(lambda _, step=delta: self.navigate(step))
            navigation.addWidget(button)
            self.navigation_buttons.append(button)
        self.layout.addLayout(navigation)
        self.layout.addStretch()

    @property
    def has_changes(self):
        return bool(self.changes)

    @property
    def has_current(self):
        return self.current in self.visible_indices

    def set_revisions(self, original, incoming, *, review=None, page_lines=()):
        """Compatibility entry point for isolated review previews."""
        from app.src.review_model import build_review
        self.set_model(build_review(original, incoming), review=review, page_lines=page_lines)

    def set_model(self, model, *, review=None, page_lines=()):
        self.model = model
        self.changes = model.edits
        self._page_lines, self._location_side = page_lines, 'original'
        for button in self.decision_buttons:
            button.setDown(False)
        self.review = review
        self._speakers(model.original)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.cards = []
        for index in range(len(self.changes)):
            card = ReviewCard()
            card.clicked.connect(lambda i=index, c=card:
                                 self._activate(i) if i < len(self.cards) and self.cards[i] is c else None)
            card.setObjectName(f'suggestion{index}')
            rows = QVBoxLayout(card)
            rows.setContentsMargins(8, 6, 8, 6)
            rows.setSpacing(6)
            card.heading = QLabel()
            card.heading.setWordWrap(True)
            rows.addWidget(card.heading)
            card.detail = QLabel()
            rows.addWidget(card.detail)
            card.comparisons = []
            layout.addWidget(card)
            self.cards.append(card)
            self._render_card(index)
        layout.addStretch()
        old = self.scroll.takeWidget()
        if old:
            old.deleteLater()
        self.scroll.setWidget(root)
        self.current = max(0, min(self.current, len(self.changes)-1))
        self.filter_speaker(self.speaker_filter, select=False)

    def amend_model(self, model, review):
        count = len(model.edits)
        if count > len(self.cards):
            self.set_model(model, review=review)
            return
        self.model, self.changes, self.review = model, model.edits, review
        self._page_lines = ()
        if count < len(self.cards):
            for card in self.cards[count:]:
                card.hide()
                self.scroll.widget().layout().removeWidget(card)
                card.deleteLater()
            del self.cards[count:]
            self._speakers(model.original)
            self.current = max(0, min(self.current, count-1))
            self.filter_speaker(self.speaker_filter, select=False)
        elif self.has_current:
            self._render_card(self.current)
            self._update_heading()
            self._size_comparison()

    def _render_card(self, index):
        card, change = self.cards[index], self.changes[index]
        attributed = index in self.needs_review or any(index in ids for ids in self.speaker_edits.values())
        detail = ''
        if attributed:
            title = 'Speaker attribution · Needs review'
        elif change.kind == 'metadata':
            title = 'Native fields and symbols'
        elif change.kind == 'structure':
            old = sum(change.original.text.count('\n', a, b) for a, b, _, _ in change.ranges)
            new = sum(change.incoming.text.count('\n', c, d) for _, _, c, d in change.ranges)
            title = 'Insert paragraph break' if new > old else 'Join paragraphs' if new < old else 'Paragraph change'
        else:
            title = 'Linked field' if change.field else 'Wording'
        if change.field:
            detail = f'{len(change.ranges)} linked occurrences'
        elif change.kind == 'speaker' and len(change.ranges) == 1:
            a, b, c, d = change.ranges[0]
            if change.original.text[a:b] == change.incoming.text[c:d]:
                fields = [next((e.name for e in rev.elements if e.kind == 'field' and (e.start, e.end) == span), None)
                          for rev, span in ((change.original, (a, b)), (change.incoming, (c, d)))]
                if all(fields):
                    detail = ' → '.join(fields)
        card.title = title
        card.heading.setText(title)
        card.detail.setText(detail)
        card.detail.setVisible(bool(detail))
        parts = change_diff(change)
        while len(card.comparisons) > len(parts):
            label = card.comparisons.pop()
            label.hide()
            card.layout().removeWidget(label)
            label.deleteLater()
        for row, (_, content) in enumerate(parts):
            if row == len(card.comparisons):
                label = QLabel()
                label.setStyleSheet('padding:4px;')
                label.setObjectName('comparison')
                label.setTextFormat(Qt.RichText)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
                label.linkActivated.connect(lambda link, i=index, w=card:
                                            self._click_word(self.model, i, link)
                                            if i < len(self.cards) and self.cards[i] is w else None)
                card.layout().addWidget(label)
                card.comparisons.append(label)
            card.comparisons[row].setText('<span style="white-space:pre-wrap; font-size:large">'
                                          + content.replace('\n', '<br>') + '</span>')

    def _speakers(self, original):
        box = QWidget()
        rows = QVBoxLayout(box)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(8)
        box.setStyleSheet(
            'QFrame#speakerSection { border: 1px solid palette(placeholder-text); border-radius: 4px; }'
            'QLabel#speakerHeading { font-weight: bold; }'
        )
        summaries = (self.review or {}).get('evidence', {}).get('speakers', {})
        overrides = (self.review or {}).get('overrides', {})
        choices = speaker_choices(original) if summaries else {}
        names = sorted((choice.name for choice in choices.values()), key=str.casefold)
        mappings = {}
        for speaker, summary in summaries.items():
            name = overrides.get(speaker, summary['mapped'])
            choice = choices.get(speaker_name_key(name)) if name else None
            mappings[speaker] = choice.name if choice else None
        uses = Counter(name for name in mappings.values() if name)
        matches_by_speaker = {}
        needs_check = set()
        for speaker, summary in summaries.items():
            mapped = mappings[speaker]
            matches = sum(count for name, count in summary['counts'].items()
                          if mapped and speaker_name_key(name) == speaker_name_key(mapped))
            matches_by_speaker[speaker] = matches
            if matches < 2 or (speaker not in overrides and uses[mapped] > 1):
                needs_check.add(speaker)
        locations = (self.review or {}).get('locations', ())
        self.speaker_edits = _attribution_edits(self.model, locations, needs_check, mappings)
        self.needs_review = frozenset(i for i, edit in enumerate(self.changes) if edit.kind == 'speaker')
        self.unmatched_speaker_ranges = tuple(sorted(
            (p['start'], p['end']) for p in locations
            if not p['resolved'] and p['start'] < p['end'] and mappings.get(p['speaker']) is None))

        total_matches = 0
        for speaker, summary in summaries.items():
            mapped = mappings[speaker]
            matches = matches_by_speaker[speaker]
            mismatches = len(self.needs_review.intersection(self.speaker_edits.get(speaker, ())))
            total_matches += matches
            section = QFrame()
            section.setObjectName('speakerSection')
            rows.addWidget(section)
            content = QVBoxLayout(section)
            content.setContentsMargins(10, 8, 10, 10)
            content.setSpacing(5)
            heading = QHBoxLayout()
            label = QLabel(speaker)
            label.setObjectName('speakerHeading')
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            heading.addWidget(label, 1)
            button = QPushButton('Review')
            button.setAccessibleName(f'Review {speaker}')
            button.setToolTip('Review pending attribution differences for this speaker.')
            button.setEnabled(bool(self.speaker_edits.get(speaker)))
            button.clicked.connect(lambda _, s=speaker: self.filter_speaker(s))
            heading.addWidget(button, 0, Qt.AlignRight)
            content.addLayout(heading)
            combo = SpeakerCombo()
            combo.setAccessibleName(f'Assigned name for {speaker}')
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.addItem('Needs review', None)
            for name in names:
                combo.addItem(name, name)
            combo.setCurrentIndex(max(0, combo.findData(mapped)))
            automatic = summary['mapped']
            if automatic:
                combo.setToolTip(f'Automatic match: {automatic}')
            combo.activated.connect(lambda i, s=speaker, c=combo, snapshot=box:
                                    self.mapping_requested.emit(s, c.itemData(i))
                                    if self.speaker_scroll.widget() is snapshot else None)
            assignment = QHBoxLayout()
            assignment.addWidget(QLabel('Assigned to'))
            assignment.addWidget(combo, 1)
            content.addLayout(assignment)
            bar = SpeakerMatchBar()
            bar.setRange(0, max(1, matches+mismatches))
            bar.setValue(matches)
            counts = (f'{matches} {"match" if matches == 1 else "matches"} · '
                      f'{mismatches} {"mismatch" if mismatches == 1 else "mismatches"}')
            bar.setAccessibleName(f'Matches for {speaker}')
            bar.setFormat(counts)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            votes = '\n'.join(f'{name}: {count}' for name, count in summary['counts'].items())
            bar.setToolTip('Mismatches are pending speaker changes.\nSpeaker identification votes\n' + votes)
            count_label = QLabel(counts)
            count_label.setToolTip(bar.toolTip())
            match_row = QHBoxLayout()
            match_row.addWidget(bar, 1)
            match_row.addWidget(count_label)
            content.addLayout(match_row)
        scrollbar = self.speaker_scroll.verticalScrollBar()
        position = scrollbar.value() if self.review is self._shown_review else 0
        self._shown_review = self.review
        old = self.speaker_scroll.takeWidget()
        if old:
            # A mapping change refreshes the list before combo activation returns.
            old.hide()
            old.setParent(self.speaker_scroll)
            old.deleteLater()
        self.speaker_scroll.setWidget(box)
        self._size_speaker_list()
        self.speaker_scroll.setVisible(bool(summaries) and self.summary.isChecked())
        scrollbar.setValue(position)
        self.summary.setVisible(bool(summaries or self.needs_review))
        self.summary.setEnabled(bool(summaries))
        self.summary.setArrowType((Qt.DownArrow if self.summary.isChecked() else Qt.RightArrow)
                                  if summaries else Qt.NoArrow)
        self.summary.setText(f'Speakers · {total_matches} matches · {len(self.needs_review)} to review')

    def _size_speaker_list(self):
        box = self.speaker_scroll.widget()
        if box:
            self.speaker_scroll.setMaximumHeight(min(box.sizeHint().height(), self.height() * 5 // 12))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._size_speaker_list()
        self._size_comparison()

    def _size_comparison(self):
        root = self.scroll.widget()
        if root:
            margins = self.layout.contentsMargins()
            frame = 2 * self.scroll.frameWidth()
            width = self.contentsRect().width() - margins.left() - margins.right() - frame
            layout = root.layout()
            height = (layout.totalHeightForWidth(max(1, width)) if layout.hasHeightForWidth()
                      else layout.sizeHint().height())
            self.scroll.setMaximumHeight(height + frame)

    def filter_speaker(self, speaker, *, select=True):
        self.speaker_filter = speaker
        self.visible_indices = (list(range(len(self.changes))) if speaker is None else
                                sorted(self.speaker_edits.get(speaker, ())))
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
            target = self.visible_indices[(index+step) % len(self.visible_indices)]
            if target != self.current:
                self._activate(target)

    def _activate(self, index):
        self.select(index)
        self.navigated.emit()

    def _click_word(self, model, index, link):
        if self.model is model and self.current == index:
            side, position = link.split(':')
            self.passage_clicked.emit(side, int(position))

    def set_page_lines(self, page_lines, side):
        self._page_lines, self._location_side = page_lines, side
        self._update_heading()
        self._size_comparison()

    def _update_heading(self):
        if not self.has_current:
            return
        card, change = self.cards[self.current], self.changes[self.current]
        title = card.title
        line = self.live_location(change) if self.live_location and change.ranges else None
        if line is None and self._page_lines and change.ranges:
            start = preview_start(change, self._location_side)
            text = getattr(change, self._location_side).text
            qt_start = len(text[:start].encode('utf-16-le')) // 2
            index = bisect_right(self._page_lines, qt_start, key=lambda line: line.position) - 1
            if index >= 0:
                line = self._page_lines[index]
        if line is not None:
            title += f' · Page {line.page}, line {line.number}'
        card.heading.setText(title)

    def _mark_selected(self):
        for button in self.decision_buttons:
            button.setEnabled(self.has_current)
        for button in self.navigation_buttons:
            button.setEnabled(len(self.visible_indices) > 1)
        for i,card in enumerate(self.cards):
            card.setVisible(i == self.current and i in self.visible_indices)
            card.setStyleSheet(f'QWidget#suggestion{i} {{ border-left: 3px solid #91bce9; }}' if i == self.current else '')
        if self.has_current:
            self._render_card(self.current)
        self._update_heading()
        self._size_comparison()
        self.selection_changed.emit()

    def request_current(self, accept):
        if self.isEnabled() and self.has_current:
            self.requested.emit(self.current, accept)

    def show_next_pending(self, index):
        self.count.setText('Updating preview…')
        remaining = [i for i in self.visible_indices if i != index]
        if remaining:
            self.select(next((i for i in remaining if i > index), remaining[-1]))
        else:
            self.current = -1
            self._mark_selected()

    def select(self, index, *, focus_passage=True):
        if 0 <= index < len(self.changes):
            if index not in self.visible_indices:
                self.filter_speaker(None, select=False)
            self.current = index
            self._mark_selected()
            self.scroll.verticalScrollBar().setValue(0)
            if focus_passage:
                self.selected.emit(index)

    def center_line(self): return self.current
    def scroll_to_center_line(self, line): self.select(min(line, len(self.changes)-1))
