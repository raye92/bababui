"""One review decision with its preview and speaker evidence."""
from bisect import bisect_right
from collections import Counter
from html import escape
from PySide6.QtCore import QEvent, Signal, Qt
from PySide6.QtWidgets import (QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QFrame, QLabel, QPushButton, QToolButton, QComboBox, QProgressBar, QSizePolicy)
from app.src.addressees import note_spans
from app.src.suggestion_filter import LABEL, speaker_choices, speaker_name_key
from app.src.suggestions import preview_context, preview_ranges
from shared.speaker_review import WITNESS, label_changes, label_flags, label_key, label_units


def speaker_paragraphs(text):
    """(start, end, label start, label end, speaker) for each labeled speech paragraph.
    Q is the examiner on the BY line in effect and A is the witness."""
    units = label_units(text)
    starts = [text.rfind('\n', 0, u.label_start) + 1 for u in units]
    result = []
    for k, unit in enumerate(units):
        speaker = unit.examiner if unit.kind == 'q' else WITNESS if unit.kind == 'a' else label_key(unit.label)
        end = starts[k + 1] if k + 1 < len(units) else len(text)
        result.append((starts[k], end, unit.label_start, unit.label_end, speaker))
    return result


def _speakers_in(paragraphs, start, end):
    """Speakers of the paragraphs a range covers, and whether it covers one of their labels."""
    found = [p for p in paragraphs if (p[0] < end and start < p[1]) or (start == end and p[0] <= start < p[1])]
    return {p[4] for p in found}, any(start < p[3] and end > p[2] for p in found)


def speaker_change(change, original_paragraphs, incoming_paragraphs):
    """True when a decision gives words to a different known speaker: a label such as
    Q replaced by THE WITNESS:, or a paragraph split or join that moves words between
    Q and A. Renaming an unresolved SPEAKER N is attribution, not this."""
    for a, b, c, d in change.ranges:
        before, label_before = _speakers_in(original_paragraphs, a, b)
        after, label_after = _speakers_in(incoming_paragraphs, c, d)
        if not before or not after or None in before | after:
            continue
        if any(x.startswith('SPEAKER ') for x in before | after):
            continue
        if (label_before or label_after) and before != after:
            return True
    return False


def speaker_note(info):
    """One line on a card: Gemini's label, the proposed label and why."""
    text = f"AI speaker review: Gemini had {info['gemini'] or 'no label'}, proposed {info['proposed']}."
    if info.get('reason'):
        text += f" {info['reason'].rstrip('.')}."
    if info.get('checks'):
        text += ' Checks: ' + '; '.join(info['checks']) + '.'
    return text


def flag_note(flag):
    """One line on a card for a turn the speaker review could not settle."""
    note = (flag.get('note') or '').strip().rstrip('.')
    text = (flag.get('text') or '').strip()
    if not note:
        return 'AI speaker review could not settle who spoke this turn. Check the audio.'
    return f'AI speaker review: “{text}” {note}. Check the audio.' if text else \
        f'AI speaker review: this turn {note}. Check the audio.'


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
            parts.extend((escape(original[position:a]), _highlight(original[a:b], False),
                          _highlight(incoming[c:d], True)))
            position = b
        parts.append(escape(suffix))
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


def _attribution_edits(model, locations, needs_check, flagged=None):
    """Find pending label replacements and uncertain labels in the actual diff.

    Edits at labels that only the AI disputes, without voice or context
    agreement, are added to `flagged` when a set is given.
    """
    pending = sorted((p for p in locations if not p['resolved'] and p['start'] < p['end']),
                     key=lambda p: p['start'])
    if not pending:
        return {}
    ends = [p['end'] for p in pending]
    original, incoming = model.original.text, model.incoming.text
    by_speaker = {}
    for index, edit in enumerate(model.edits):
        for a, b, c, d in edit.ranges:
            if c == d:
                continue
            first = bisect_right(ends, c)
            for i in range(first, len(pending)):
                location = pending[i]
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
                mismatch = bool(observed)
                if before and incoming.rfind('\n', 0, c) == incoming.rfind('\n', 0, start):
                    label_start, label_end = (line_start + pos for pos in before.span('name'))
                    if (a < label_end and b > label_start) or (a == b and label_start <= a <= label_end):
                        if speaker_name_key(before['name']) == current:
                            continue
                        mismatch = True
                if mismatch or speaker in needs_check:
                    by_speaker.setdefault(speaker, set()).add(index)
                if flagged is not None and location.get('decision') == 'flag':
                    by_speaker.setdefault(speaker, set()).add(index)
                    flagged.add(index)
    return by_speaker


class QuestionCard(QFrame):
    """One speaker decision: an unresolved voice, or one uncertain turn."""

    def __init__(self, question, names, parent=None):
        super().__init__(parent)
        from app.src.speaker_questions import VOICE
        from app.src.playback import timestamp
        self.question = question
        self.setObjectName('speakerQuestion')
        self.setFrameShape(QFrame.StyledPanel)
        rows = QVBoxLayout(self)
        rows.setContentsMargins(6, 4, 6, 4)
        rows.setSpacing(4)
        if question.kind == VOICE:
            title = f'Unresolved voice · {question.speaker} · {question.turns} linked turns'
        else:
            title = f'Who said this? · {question.speaker}' if question.speaker else 'Who said this?'
        heading = QLabel(title)
        heading.setObjectName('questionTitle')
        heading.setTextFormat(Qt.PlainText)
        heading.setWordWrap(True)
        rows.addWidget(heading)
        when = f' · {timestamp(int(question.time * 1000))}' if question.time is not None else ''
        clip = QLabel(f'“{question.text}”{when}')
        clip.setObjectName('questionClip')
        clip.setTextFormat(Qt.PlainText)
        clip.setWordWrap(True)
        rows.addWidget(clip)
        if question.suggestion:
            hint = QLabel(f'Suggested: {question.suggestion}')
            hint.setObjectName('questionSuggestion')
            hint.setTextFormat(Qt.PlainText)
            rows.addWidget(hint)
        self.combo = SpeakerCombo()
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.addItem('Choose a participant', None)
        for name in names:
            self.combo.addItem(name, name)
        self.combo.setCurrentIndex(max(0, self.combo.findData(question.suggestion)))
        rows.addWidget(self.combo)
        buttons = QHBoxLayout()
        self.review_button = QPushButton('Review')
        self.review_button.setToolTip('Go to the identifying clip and play it with the exchange around it.')
        self.this_button = QPushButton('Assign this turn')
        self.all_button = QPushButton(f'Assign all {question.turns} linked turns')
        self.all_button.setVisible(question.kind == VOICE and question.turns > 1)
        for button in (self.review_button, self.this_button, self.all_button):
            buttons.addWidget(button)
        rows.addLayout(buttons)
        self.combo.currentIndexChanged.connect(self._enable)
        self._enable()

    def _enable(self):
        chosen = self.combo.currentData() is not None
        self.this_button.setEnabled(chosen)
        self.all_button.setEnabled(chosen)


class ReviewView(QWidget):
    requested = Signal(int, bool)
    selected = Signal(int)
    selection_changed = Signal()
    navigated = Signal()
    mapping_requested = Signal(str, object)
    # A participant name and the question it answers; True assigns every linked turn.
    assign_requested = Signal(object, str, bool)
    question_review_requested = Signal(object)
    speaker_undo_requested = Signal()

    def __init__(self):
        super().__init__()
        self.changes, self.cards, self.visible_indices = [], [], []
        self.current = 0
        self.speaker_filter = None
        self.review = self._shown_review = None
        self.speaker_edits = {}
        self.needs_review = frozenset()
        self.unmatched_speaker_ranges = ()
        self.corrected_speaker_ranges = ()
        self.speaker_label_ranges = ()
        self.speaker_changes = self.missing = frozenset()
        self.questions, self.resolved_speakers = [], {}
        self.question_cards = []
        self.show_resolved = False
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
        for caption, accept, key in (('Accept', True, 'A'), ('Reject', False, 'D')):
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
        for button in self.decision_buttons:
            button.setDown(False)
        self.review = review
        original, incoming = model.original, model.incoming
        self._speakers(original)
        # Yellow labels: speakers the AI review corrected against Gemini, plus unmatched labels.
        reviewed = label_changes((review or {}).get('speaker_review'), incoming.text)
        # Q/A or colloquy labels changed by whom a turn addressed, with why.
        addressed = note_spans((review or {}).get('addressees'), incoming.text)
        self.corrected_speaker_ranges = tuple((a, b) for a, b, _ in reviewed)
        self.speaker_label_ranges = tuple(sorted(set(self.unmatched_speaker_ranges)
                                                 | set(self.corrected_speaker_ranges)))
        attribution = set().union(*self.speaker_edits.values())
        before_paragraphs, after_paragraphs = speaker_paragraphs(original.text), speaker_paragraphs(incoming.text)
        # A passage missing from the AI draft is not a speaker change, whatever labels it holds.
        self.missing = frozenset(getattr(model, 'missing', ()))
        self.speaker_changes = frozenset(index for index, change in enumerate(self.changes)
                                         if index not in attribution and index not in self.missing
                                         and speaker_change(change, before_paragraphs, after_paragraphs))
        # A label change at a turn the speaker review could not settle rests on
        # Gemini's label alone, so it needs review like an AI-only attribution.
        flags = label_flags((review or {}).get('speaker_review'), incoming.text)
        unsettled = {index: flag for index in sorted(self.speaker_changes | attribution)
                     for a, b, flag in flags
                     if any(c < b and d > a for _, _, c, d in self.changes[index].ranges)}
        self.needs_review = self.needs_review | frozenset(unsettled)
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
            needs_review = index in self.needs_review
            if needs_review:
                title = 'Speaker attribution · Needs review'
            elif index in attribution:
                title = 'Speaker attribution'
            elif index in self.speaker_changes:
                title = 'Speaker'
            else:
                title = 'Linked field' if change.field else 'Wording'
            if change.kind == 'metadata':
                title = 'Native fields and symbols'
            if (change.kind == 'structure' and index not in attribution and index not in self.speaker_changes
                    and index not in self.missing):
                title = 'Insert paragraph break' if after.count('\n') > before.count('\n') else 'Join paragraphs' if before.count('\n') > after.count('\n') else 'Paragraph change'
            if index in self.missing:
                title = 'Missing from AI draft'
            addressee = next((note for a, b, note in addressed
                              if any(c < b and d > a or c == d and a <= c < b for _, _, c, d in change.ranges)), None)
            if addressee is not None and title == 'Wording':
                title = 'Q/A or colloquy'
            if change.ranges:
                start = change.ranges[0][0]
                qt_start = len(original.text[:start].encode('utf-16-le')) // 2
                line = next((p for p in reversed(page_lines) if p.position <= qt_start), None)
                if line:
                    title += f' · Page {line.page}, line {line.number}'
            heading = QLabel(title)
            heading.setWordWrap(True)
            rows.addWidget(heading)
            if index in self.missing:
                note = QLabel('The AI draft has no words for this passage, so the transcription probably missed this '
                              'audio. Listen before removing it. Accept All keeps your text.')
                note.setObjectName('missingNote')
                note.setTextFormat(Qt.PlainText)
                note.setWordWrap(True)
                rows.addWidget(note)
            for a, b, info in reviewed:
                if info and any(c < b and d > a or c == d and a <= c <= b for _, _, c, d in change.ranges):
                    reason = QLabel(speaker_note(info))
                    reason.setObjectName('speakerReason')
                    reason.setTextFormat(Qt.PlainText)
                    reason.setWordWrap(True)
                    rows.addWidget(reason)
                    break
            if index in unsettled:
                reason = QLabel(flag_note(unsettled[index]))
                reason.setObjectName('speakerFlag')
                reason.setTextFormat(Qt.PlainText)
                reason.setWordWrap(True)
                rows.addWidget(reason)
            if addressee is not None:
                reason = QLabel(addressee['why'])
                reason.setObjectName('addresseeReason')
                reason.setTextFormat(Qt.PlainText)
                reason.setWordWrap(True)
                rows.addWidget(reason)
            if change.field:
                rows.addWidget(QLabel(f'{len(change.ranges)} linked occurrences'))
            for _, text in change_diff(change):
                text = text.replace('\n', '<br>')
                label = QLabel(f'<span style="white-space:pre-wrap; font-size:large">{text}</span>')
                label.setStyleSheet('padding:4px;')
                label.setObjectName('comparison')
                label.setTextFormat(Qt.RichText)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.NoTextInteraction)
                rows.addWidget(label)
            layout.addWidget(card)
            self.cards.append(card)
        layout.addStretch()
        old = self.scroll.takeWidget()
        if old:
            old.deleteLater()
        self.scroll.setWidget(root)
        self.current = max(0, min(self.current, len(self.changes)-1))
        self.filter_speaker(self.speaker_filter, select=False)

    def _speakers(self, original):
        box = QWidget()
        rows = QVBoxLayout(box)
        rows.setContentsMargins(0, 0, 0, 0)
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
        flagged = set()
        self.speaker_edits = _attribution_edits(self.model, locations, needs_check, flagged)
        self.needs_review = frozenset(index for speaker in needs_check
                                      for index in self.speaker_edits.get(speaker, ())) | flagged
        self.unmatched_speaker_ranges = tuple(sorted(
            (p['start'], p['end']) for p in locations
            if not p['resolved'] and p['start'] < p['end'] and mappings.get(p['speaker']) is None))

        from app.src.speaker_questions import questions
        self.questions, self.resolved_speakers = questions(self.review, self.model.incoming.text)
        self.question_cards = []
        for question in self.questions:
            card = QuestionCard(question, names)
            card.review_button.clicked.connect(
                lambda _, q=question, snapshot=box: self._review_question(q) if self.speaker_scroll.widget() is snapshot else None)
            card.this_button.clicked.connect(
                lambda _, c=card, snapshot=box: self.assign_requested.emit(c.question, c.combo.currentData(), False)
                if self.speaker_scroll.widget() is snapshot else None)
            card.all_button.clicked.connect(
                lambda _, c=card, snapshot=box: self.assign_requested.emit(c.question, c.combo.currentData(), True)
                if self.speaker_scroll.widget() is snapshot else None)
            rows.addWidget(card)
            self.question_cards.append(card)
        tools = QHBoxLayout()
        self.resolved_toggle = QToolButton()
        self.resolved_toggle.setCheckable(True)
        self.resolved_toggle.setChecked(self.show_resolved)
        self.resolved_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.resolved_toggle.setArrowType(Qt.DownArrow if self.show_resolved else Qt.RightArrow)
        self.resolved_toggle.setText(f'Resolved speakers ({len(set(summaries) - {q.speaker for q in self.questions})})')
        tools.addWidget(self.resolved_toggle, 1)
        self.undo_button = QPushButton('Undo')
        self.undo_button.setToolTip('Undo the last speaker assignment or review decision.')
        self.undo_button.clicked.connect(self.speaker_undo_requested)
        self.undo_button.setEnabled(False)
        tools.addWidget(self.undo_button, 0, Qt.AlignRight)
        rows.addLayout(tools)
        resolved = QWidget()
        resolved.setObjectName('resolvedSpeakers')
        resolved_rows = QVBoxLayout(resolved)
        resolved_rows.setContentsMargins(0, 0, 0, 0)
        resolved.setVisible(self.show_resolved)
        self.resolved_toggle.toggled.connect(lambda on, w=resolved: self._toggle_resolved(on, w))
        rows.addWidget(resolved)
        asked = {q.speaker for q in self.questions}

        total_matches = 0
        for speaker, summary in summaries.items():
            mapped = mappings[speaker]
            matches = matches_by_speaker[speaker]
            mismatches = sum(summary['counts'].values())-matches if mapped else 0
            total_matches += matches
            if speaker in asked:
                continue  # Its open question is shown above instead.
            target = resolved_rows
            heading = QHBoxLayout()
            label = QLabel(f'{speaker} → {mapped or "Needs review"}')
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            heading.addWidget(label, 1)
            button = QPushButton('Review')
            button.setToolTip('Review pending attribution differences for this speaker.')
            button.setEnabled(bool(self.speaker_edits.get(speaker)))
            button.clicked.connect(lambda _, s=speaker: self.filter_speaker(s))
            heading.addWidget(button, 0, Qt.AlignRight)
            target.addLayout(heading)
            combo = SpeakerCombo()
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
            target.addWidget(combo)
            bar = QProgressBar()
            bar.setRange(0, max(1, matches+mismatches))
            bar.setValue(matches)
            bar.setFormat(f'{matches} {"match" if matches == 1 else "matches"} · '
                          f'{mismatches} {"mismatch" if mismatches == 1 else "mismatches"}')
            bar.setToolTip('Agreement with existing labels, not verified identity.\n'+'\n'.join(f'{n}: {v}' for n,v in summary['counts'].items()))
            target.addWidget(bar)
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
        shown = bool(summaries or self.questions)
        self.speaker_scroll.setVisible(shown and self.summary.isChecked())
        scrollbar.setValue(position)
        self.summary.setVisible(shown)
        affected = sum(q.turns for q in self.questions)
        unresolved = len(self.questions)
        self.summary.setText(f'Speakers · {unresolved} unresolved · {affected} '
                             f'{"turn" if affected == 1 else "turns"} · {total_matches} matches')

    def _toggle_resolved(self, on, widget):
        self.show_resolved = on
        widget.setVisible(on)
        self.resolved_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self._size_speaker_list()

    def _review_question(self, question):
        if question.speaker and question.speaker in self.speaker_edits:
            self.filter_speaker(question.speaker)
        self.question_review_requested.emit(question)

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
                self.select(target)
                self.navigated.emit()

    def _mark_selected(self):
        for button in self.decision_buttons:
            button.setEnabled(self.has_current)
        for button in self.navigation_buttons:
            button.setEnabled(len(self.visible_indices) > 1)
        for i,card in enumerate(self.cards):
            card.setVisible(i == self.current and i in self.visible_indices)
            card.setStyleSheet(f'QWidget#suggestion{i} {{ border-left: 3px solid #91bce9; }}' if i == self.current else '')
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

    def select(self, index):
        if 0 <= index < len(self.changes):
            if index not in self.visible_indices:
                self.filter_speaker(None, select=False)
            self.current = index
            self._mark_selected()
            self.scroll.verticalScrollBar().setValue(0)
            self.selected.emit(index)

    def center_line(self): return self.current
    def scroll_to_center_line(self, line): self.select(min(line, len(self.changes)-1))
