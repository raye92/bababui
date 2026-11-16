"""One structured document and its review transactions."""
from bisect import bisect_right
from copy import deepcopy
from PySide6.QtCore import Signal, Slot, QThread, QTimer, Qt
from PySide6.QtGui import QFont, QShortcut, QKeySequence, QTextCursor, QColor, QTextFormat
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QPushButton, QLabel, QSplitter, QTextEdit, QMessageBox
from app.src.native_editor import NativeTranscriptEditor
from app.src.review_view import ReviewView
from app.src.review_model import build_review
from app.src.review_colors import CHECK_BACKGROUND, CHECK_FOREGROUND
from app.src.inline_review import InlineReviewEditor
from app.src.page_view import PageView
from app.src.casecat.anchors import utf16_index
from app.src.casecat.presentation import presentation
from app.src.suggestions import preview_ranges, resolve, resolve_all, text_edits
from app.src.suggestion_filter import begin_review, override_speaker, track_decisions, auto_accept, questionable_speaker_defaults
from app.src.speech_alignment import WAV_CHANGED


class ImportView(QWidget):
    changed = Signal()
    import_requested = Signal()

    def __init__(self, document):
        super().__init__()
        self.document = document
        layout = QVBoxLayout(self)
        layout.addStretch()
        layout.addWidget(QLabel('Import a CaseCAT ZIP to start editing.'), alignment=Qt.AlignHCenter)
        button = QPushButton('Import CaseCAT ZIP')
        button.clicked.connect(self.import_requested)
        layout.addWidget(button, alignment=Qt.AlignHCenter)
        layout.addStretch()

    def capture_position(self): pass
    def schedule_restore(self): pass
    def active_editor(self): return None
    def undo_review(self): pass
    def redo_review(self): pass
    def edited(self): self.changed.emit()


class ReviewPreviewWorker(QThread):
    def __init__(self, bundle, job, before, decision, index, ranges, parent):
        super().__init__(parent)
        self.bundle, self.job = bundle, job
        self.before, self.decision, self.index, self.ranges = before, decision, index, ranges
        self.previews = {}
        self.error = None

    def run(self):
        try:
            self.revisions = self.decision()
            for side, old, revision in zip(('original', 'incoming'), self.before, self.revisions):
                if old != revision:
                    try:
                        self.previews[side] = presentation(self.job.with_revision(revision), self.bundle)
                    except ValueError:
                        self.previews[side] = (revision.text, {}, frozenset())
            self.model = build_review(*self.revisions)
        except Exception as exc:
            self.error = exc


class DocumentView(QWidget):
    changed = Signal()

    def __init__(self, document, *, disabled_auto_accept_rules=frozenset()):
        super().__init__()
        if document.native is None:
            raise ValueError('An editor requires an imported CaseCAT job.')
        self.document = document
        self.disabled_auto_accept_rules = disabled_auto_accept_rules
        automatic_before = None
        from app.src.suggestion_filter import LABEL, GENERIC
        if (document.native.review is None and document.native.original != document.native.incoming
                and any((m := LABEL.match(p)) and GENERIC.fullmatch(m['name']) for p in document.incoming.split('\n'))):
            automatic_before = begin_review(document.native, document.native.incoming.text,
                                            exclude_off_record='off_record' not in self.disabled_auto_accept_rules)
        self._updating = False
        self._position_pending = True
        self._native_history = {'original': {}, 'incoming': {}}
        self._review_undo, self._review_redo = [], []
        self._review_worker = None
        if document.native.original != document.native.incoming or automatic_before:
            self._automatic_review(automatic_before)
        self.stack = QStackedWidget()
        self.original_stack = QStackedWidget()
        font = QFont('Courier New', 12)
        self.editor = NativeTranscriptEditor(font)
        self.incoming_editor = NativeTranscriptEditor(font)
        self.inline_editor = InlineReviewEditor(font)
        self.inline_editor.set_source_editors(self.editor, self.incoming_editor)
        self.inline_editor.selected.connect(self.select_inline)
        self.inline_editor.history_requested.connect(lambda undo: self.undo_review() if undo else self.redo_review())
        self.inline_editor.source_activated.connect(self._seek_review_passage)
        self.diff_view = ReviewView()
        self.diff_view.requested.connect(self._start_review)
        self.diff_view.selected.connect(self.select_suggestion)
        self.diff_view.mapping_requested.connect(self.change_speaker_mapping)
        for side, editor in (('original', self.editor), ('incoming', self.incoming_editor)):
            editor.native_revision_at_step = lambda steps, s=side: self._native_history[s].get(steps)
            editor.whole_text_set.connect(lambda text, s=side, e=editor: self._native_whole_text(s, e, text))
            editor.document().contentsChange.connect(lambda p, r, a, s=side, e=editor: self._native_edit(s, e, p, r, a))
        self.original_page = PageView(self.editor)
        self.incoming_page = PageView(self.incoming_editor)
        self.original_stack.addWidget(self.original_page)
        self.inline_page = PageView(self.inline_editor)
        self.original_stack.addWidget(self.inline_page)
        self.stack.addWidget(self.original_stack)
        self.stack.addWidget(self.incoming_page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.review_splitter = QSplitter(Qt.Horizontal)
        self.review_splitter.addWidget(self.stack)
        self.review_splitter.addWidget(self.diff_view)
        self.diff_view.setMinimumWidth(260)
        self.review_splitter.setStretchFactor(0, 1)
        self.review_splitter.setStretchFactor(1, 1)
        self.review_splitter.setSizes([900, 380])
        layout.addWidget(self.review_splitter, 1)
        self.editor.transcript_clicked.connect(lambda: self.select_at_cursor(self.editor, 'original'))
        self.incoming_editor.transcript_clicked.connect(lambda: self.select_at_cursor(self.incoming_editor, 'incoming'))
        self.playback = None
        if document.native.alignment and not document.wav_path:
            self._validate_alignment(document.warnings)
        if document.wav_path:
            self.setup_playback(layout)
        self.editor.textChanged.connect(self._original_changed)
        self.incoming_editor.textChanged.connect(self._incoming_changed)
        self.refresh()
        self.stack.setCurrentIndex(document.view)
        self.schedule_restore()

    def setup_playback(self, layout):
        from app.src.playback import PlaybackBar
        doc = self.document
        self._validate_alignment(doc.warnings)
        self.playback = PlaybackBar(doc.wav_path, self._playback_timing(), self._playback_context, self)
        layout.addWidget(self.playback)
        if not getattr(self, '_playback_connected', False):
            self._playback_connected = True
            shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(lambda: self.playback.toggle())
            self.stack.currentChanged.connect(lambda _: self.playback.stop())
            for editor in (self.editor, self.incoming_editor):
                editor.transcript_clicked.connect(lambda: self.playback.seek_from_cursor())
            for key, method in (('Shift+F9', 'seek_from_cursor'), ('Ctrl+F9', 'stop')):
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(lambda m=method: getattr(self.playback, m)())

    def _validate_alignment(self, warnings):
        doc = self.document
        if doc.native.alignment and not doc.native.alignment.matches_wav(doc.wav_path):
            doc.native.alignment = None
            warnings.append(WAV_CHANGED)

    def _playback_timing(self):
        import wave
        from app.src.casecat.timing import AudioMap
        doc = self.document
        if doc.native.alignment:
            return doc.native.alignment.playback()
        try:
            return AudioMap.from_job(doc.native.bundle, doc.native.job, doc.wav_path)
        except (ValueError, OSError, wave.Error, EOFError):
            return None

    def active_view(self):
        return self.incoming_editor if self.stack.currentIndex() else (self.inline_editor if self.original_stack.currentWidget() is self.inline_page else self.editor)

    def _playback_context(self):
        editor = self.active_view()
        if editor is self.inline_editor:
            side, _ = editor.source_position()
            return editor, getattr(self.document.native, side)
        return editor, getattr(self.document.native, 'incoming' if self.stack.currentIndex() else 'original')

    def _seek_review_passage(self, side, position):
        if self.playback:
            revision = getattr(self.document.native, side)
            self.playback.seek_passage(revision, position)

    def capture_position(self):
        self.document.view = self.stack.currentIndex()
        if not self._position_pending:
            self.document.center_line = self.active_view().center_line()

    def schedule_restore(self, source_position=None):
        self._position_pending = True
        QTimer.singleShot(0, lambda: self.restore_position(source_position))

    def restore_position(self, source_position=None):
        editor = self.active_view()
        if source_position is None:
            editor.scroll_to_center_line(self.document.center_line)
        elif editor is self.inline_editor:
            editor.scroll_to_source_position(*source_position)
        else:
            side, offset = source_position
            position = len(getattr(self.document, side)[:offset].encode('utf-16-le')) // 2
            lines = editor.page_lines()
            editor.scroll_to_center_line(bisect_right([line.position for line in lines], position) - 1)
        self._position_pending = False
        if source_position is not None:
            self.capture_position()

    def _review_position(self):
        editor = self.active_view()
        if editor is self.inline_editor:
            return editor.center_source_position()
        side = 'incoming' if editor is self.incoming_editor else 'original'
        lines = editor.page_lines()
        position = lines[editor.center_line()].position if lines else 0
        return side, utf16_index(getattr(self.document, side), position)

    def _restore_review_position(self, anchor, before):
        side, position = anchor
        old = before[1 if side == 'incoming' else 0].text
        editor = self.active_view()
        if editor is not self.inline_editor:
            side = 'incoming' if editor is self.incoming_editor else 'original'
        new = getattr(self.document, side)
        shift = 0
        for a, b, c, d in text_edits(old, new):
            if position < a:
                break
            if position < b:
                self.schedule_restore((side, c + min(position - a, d - c)))
                return
            shift = d - b
        self.schedule_restore((side, position + shift))

    def _set_text(self, editor, text, prepared=None):
        side = 'original' if editor is self.editor else 'incoming'
        state = self.document.native
        revision = getattr(state, side)
        history = self._native_history[side]
        previous = history.get(editor.document().availableUndoSteps())
        changed = editor.toPlainText() != text or previous != revision
        editor.set_native_source(state.bundle, state.job.with_revision(revision))
        if changed:
            editor.setPlainText(text, prepared=prepared)
            steps = editor.document().availableUndoSteps()
            self._native_history[side] = {steps: revision}

    def _native_edit(self, side, editor, position, removed, added):
        doc = self.document
        if self._updating or editor.whole_text_update:
            return
        old = getattr(doc.native, side)
        new_text = editor.toPlainText()
        pending = getattr(editor, 'pending_native_revision', None)
        if new_text == old.text and pending is None and not editor.history_action:
            return  # Presentation-only changes do not create native transactions.
        steps = editor.document().availableUndoSteps()
        history = self._native_history[side]
        restored = history.get(steps) if editor.history_action else None
        if restored is not None and restored.text != new_text:
            return  # Qt is traversing an intermediate part of an atomic edit.
        if restored is not None and restored.text == new_text:
            revision = restored
        else:
            # Qt's setPlainText notifications can include its implicit final
            # paragraph terminator, which is not transcript content.
            old_length = len(old.text.encode('utf-16-le')) // 2
            new_length = len(new_text.encode('utf-16-le')) // 2
            start = min(position, old_length)
            end = min(position + removed, old_length)
            new_start = utf16_index(new_text, min(position, new_length))
            new_end = utf16_index(new_text, min(position + added, new_length))
            try:
                revision = pending or old.replace_utf16(start, end - start, new_text[new_start:new_end])
            except ValueError as exc:
                revision = old
                doc.status = str(exc)
            if (old.text[:utf16_index(old.text, start)] + new_text[new_start:new_end]
                    + old.text[utf16_index(old.text, end):]) != new_text:
                # A programmatic whole-document update is aligned by paragraph.
                revision = old.revise(new_text)
            if not editor.history_action:
                history = {key: value for key, value in history.items() if key <= steps}
                self._native_history[side] = history
            history[steps] = revision
        doc.set_text(side, revision.text, revision=revision)
        if side == 'original':
            doc.native.review = None
            doc.set_text('incoming', revision.text, revision=revision)

    def _native_whole_text(self, side, editor, text):
        doc = self.document
        if self._updating:
            return
        doc.set_text(side, text)
        revision = getattr(doc.native, side)
        editor.set_native_source(doc.native.bundle, doc.native.job.with_revision(revision))
        editor.sync_native_text(revision.text)
        editor.refresh_native_presentation()
        editor.document().clearUndoRedoStacks()
        self._native_history[side] = {editor.document().availableUndoSteps(): revision}
        if side == 'original':
            doc.native.review = None
            doc.set_text('incoming', revision.text, revision=revision)
        self.edited()

    def refresh(self, *, previews=None, model=None):
        self._updating = True
        doc = self.document
        previews = previews or {}
        self._set_text(self.editor, doc.original, previews.get('original'))
        self._set_text(self.incoming_editor, doc.incoming, previews.get('incoming'))
        self.review_model = model if model is not None else build_review(doc.native.original, doc.native.incoming)
        self.diff_view.set_model(self.review_model, review=doc.native.review, page_lines=self.editor.page_lines())
        self.inline_editor.set_model(
            self.review_model, unmatched_speakers=self.diff_view.unmatched_speaker_ranges)
        self.original_stack.setCurrentWidget(self.inline_page if self.review_model.edits else self.original_page)
        self.inline_page.fit_page()
        self.original_page.fit_page()
        self.incoming_page.fit_page()
        self.diff_view.setVisible(self.diff_view.has_changes or bool((doc.native.review or {}).get('evidence', {}).get('speakers')))
        self.highlight_suggestions()
        self._updating = False
        self.set_busy(doc.busy)

    def highlight_suggestions(self):
        for side, editor in (('original', self.editor), ('incoming', self.incoming_editor)):
            text = getattr(self.document, side)
            marks, insertions = [], []
            for index, change in enumerate(self.diff_view.changes):
                for a, b, c, d in preview_ranges(change):
                    start, end = (a, b) if side == 'original' else (c, d)
                    if index == self.diff_view.current:
                        focus = QTextEdit.ExtraSelection()
                        focus.cursor = QTextCursor(editor.document())
                        focus.cursor.setPosition(len(text[:start].encode('utf-16-le')) // 2)
                        focus.format.setBackground(QColor('#394b60'))
                        focus.format.setProperty(QTextFormat.FullWidthSelection, True)
                        marks.append(focus)
                    if start == end:
                        insertions.append((len(text[:start].encode('utf-16-le')) // 2, index))
                        continue
                    mark = QTextEdit.ExtraSelection()
                    mark.cursor = QTextCursor(editor.document())
                    mark.cursor.setPosition(len(text[:start].encode('utf-16-le')) // 2)
                    mark.cursor.setPosition(len(text[:end].encode('utf-16-le')) // 2, QTextCursor.KeepAnchor)
                    mark.format.setBackground(QColor('#ffd7d5' if side == 'original' else '#ccffd8'))
                    mark.format.setForeground(QColor('#82071e' if side == 'original' else '#116329'))
                    if index == self.diff_view.current:
                        mark.format.setBackground(QColor('#ffaaa5' if side == 'original' else '#7ee2a8'))
                        mark.format.setFontUnderline(True)
                    marks.append(mark)
            if side == 'incoming' or not self.diff_view.has_changes:
                for start, end in self.diff_view.unmatched_speaker_ranges:
                    mark = QTextEdit.ExtraSelection()
                    mark.cursor = QTextCursor(editor.document())
                    mark.cursor.setPosition(len(text[:start].encode('utf-16-le')) // 2)
                    mark.cursor.setPosition(len(text[:end].encode('utf-16-le')) // 2, QTextCursor.KeepAnchor)
                    mark.format.setBackground(QColor(CHECK_BACKGROUND))
                    mark.format.setForeground(QColor(CHECK_FOREGROUND))
                    marks.append(mark)
            editor._selected_review = self.diff_view.current
            editor.set_review_marks(marks, insertions)

    def select_inline(self, index):
        if self._review_worker is not None:
            return
        self._inline_selection = True
        try:
            self.diff_view.select(index)
        finally:
            self._inline_selection = False

    def select_suggestion(self, index):
        if not 0 <= index < len(self.diff_view.changes):
            return
        change = self.diff_view.changes[index]
        if not getattr(self, "_inline_selection", False):
            self.inline_editor.focus_edit(index)
        self.highlight_suggestions()
        if change.ranges:
            self._focus_passage(change.ranges[0])

    def _focus_passage(self, span):
        side = 'incoming' if self.stack.currentIndex() else 'original'
        editor = self.incoming_editor if self.stack.currentIndex() else self.editor
        start = span[2 if side == 'incoming' else 0]
        cursor = editor.textCursor()
        cursor.setPosition(len(getattr(self.document, side)[:start].encode('utf-16-le')) // 2)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        lines = editor.page_lines()
        line = next((i for i in range(len(lines)-1, -1, -1)
                     if lines[i].position <= cursor.position()), 0)
        editor.scroll_to_center_line(line)

    def select_at_cursor(self, editor, side):
        if self._review_worker is not None:
            return
        position = utf16_index(getattr(self.document, side), editor.textCursor().position())
        for index, change in enumerate(self.diff_view.changes):
            for a, b, c, d in change.ranges:
                start, end = (a, b) if side == 'original' else (c, d)
                if start <= position <= end:
                    self.diff_view.select(index)
                    return

    def edited(self):
        self.document.dirty = True
        self.changed.emit()

    def _start_review(self, index, accept):
        self.review(index, accept, background=True)

    def review(self, index, accept, *, background=False):
        if self.document.busy:
            return
        state = self.document.native
        before = state.original, state.incoming, deepcopy(state.review)
        try:
            if index is None:
                if not self.review_model.edits:
                    return
                if (self.review_model.original, self.review_model.incoming) != before[:2]:
                    raise ValueError('These suggestions are stale. Refresh the review.')
                ranges = tuple(span for edit in self.review_model.edits for span in edit.ranges)
                questionable = questionable_speaker_defaults(before[2], ranges) if accept else []
                if questionable:
                    names = '\n'.join(f'{speaker} → {name}' for speaker, name in questionable)
                    if QMessageBox.question(
                            self, 'Check speaker names',
                            'These automatic names have zero matching passages or are shared by multiple speaker tags.\n\n'
                            f'{names}\n\nAccept all suggestions with these names?',
                            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
                        return
                decision = lambda: resolve_all(*before[:2], ranges, accept)
            else:
                change = self.diff_view.changes[index]
                ranges = change.ranges
                decision = lambda: resolve(*before[:2], change, accept)
            if not background:
                result = decision()
        except (ValueError, IndexError) as exc:
            self.document.status = str(exc)
            self.refresh()
            return
        if background:
            self._review_worker = worker = ReviewPreviewWorker(
                state.bundle, state.job, before, decision, index, ranges, self)
            worker.finished.connect(self._finish_review)
            if self.playback and self.isActiveWindow():
                self.setFocus(Qt.OtherFocusReason)
            self.set_busy(True)
            if index is None:
                self.diff_view.count.setText('Updating preview…')
            else:
                self.diff_view.show_next_pending(index)
                pending = self.diff_view.current
                if self.playback and pending >= 0 and self.diff_view.changes[pending].ranges:
                    self.playback.seek_from_cursor()
            self.changed.emit()
            worker.start()
            return
        self._apply_review(index, before, result, ranges)

    @Slot()
    def _finish_review(self):
        worker = self._review_worker
        self._review_worker = None
        worker.deleteLater()
        self.set_busy(False)
        if worker.error is not None:
            self.document.status = str(worker.error)
            self.diff_view.filter_speaker(self.diff_view.speaker_filter, select=False)
            if worker.index is not None:
                self.diff_view.select(worker.index)
            self.changed.emit()
            return
        self._apply_review(worker.index, worker.before, worker.revisions, worker.ranges,
                           previews=worker.previews, model=worker.model)

    def _apply_review(self, index, before, result, ranges, *, previews=None, model=None):
        state = self.document.native
        anchor = self._review_position() if index is None else None
        # Use offsets from the revision the decision leaves intact. The new
        # diff can shift indices or regroup edits around the resolved change.
        side = slice(0, 2) if result[0] is before[0] else slice(2, 4)
        pending = self.diff_view.current
        next_ranges = ()
        if index is not None and model is not None and pending >= 0 and pending != index:
            next_ranges = tuple(span[side] for span in self.diff_view.changes[pending].ranges)
        self._review_undo.append(before)
        self._review_redo.clear()
        state.original, state.incoming = result
        track_decisions(state.review, ranges, incoming_changed=before[1].text != state.incoming.text)
        self.refresh(previews=previews, model=model)
        visible = self.diff_view.visible_indices
        if anchor is not None:
            self._restore_review_position(anchor, before)
        elif visible:
            target = next((i for i in visible if i >= index), visible[-1])
            if next_ranges:
                target = next((i for i in visible if tuple(
                    span[side] for span in self.diff_view.changes[i].ranges) == next_ranges), target)
            ranges = self.diff_view.changes[target].ranges
            self.diff_view.select(target)
            # The preview already moved playback to this edit while the worker ran.
            if self.playback and ranges and tuple(span[side] for span in ranges) != next_ranges:
                self.playback.seek_from_cursor()
        elif not self.diff_view.changes and ranges:
            self._focus_passage(ranges[0])
            if self.playback:
                self.playback.seek_from_cursor()
        self.edited()

    def change_speaker_mapping(self, speaker, name):
        if self._review_worker is not None:
            return
        state = self.document.native
        before = state.original, state.incoming, deepcopy(state.review)
        try:
            override_speaker(state, speaker, name)
        except ValueError as exc:
            self.document.status = str(exc)
            self.changed.emit()
            return
        self._review_undo.append(before)
        self._review_redo.clear()
        self.refresh()
        self.edited()

    def _review_history(self, source, target):
        if source and not self.document.busy:
            state = self.document.native
            before = state.original, state.incoming, deepcopy(state.review)
            target.append(before)
            anchor = self._review_position()
            state.original, state.incoming, state.review = source.pop()
            self.refresh()
            self._restore_review_position(anchor, before)
            self.edited()

    def undo_review(self): self._review_history(self._review_undo, self._review_redo)
    def redo_review(self): self._review_history(self._review_redo, self._review_undo)

    def _original_changed(self):
        if not self._updating:
            self._review_undo.clear()
            self._review_redo.clear()
            self._refresh_native_presentation('original', self.editor)
            self.edited()

    def _incoming_changed(self):
        if not self._updating:
            self._refresh_native_presentation('incoming', self.incoming_editor)
            self.edited()

    def _refresh_native_presentation(self, side, editor):
        if editor.whole_text_update:
            return
        state = self.document.native
        revision = getattr(state, side)
        editor.set_native_source(state.bundle, state.job.with_revision(revision))
        if editor.history_action:
            return
        editor.sync_native_text(revision.text)
        editor.refresh_native_presentation()
        self._native_history[side][editor.document().availableUndoSteps()] = revision

    def toggle_view(self):
        self.capture_position()
        if self._review_worker is None:
            self.refresh()
        self.stack.setCurrentIndex(1-self.stack.currentIndex())
        self.document.view = self.stack.currentIndex()
        self.schedule_restore()
        self.changed.emit()

    def receive(self, text, warnings, alignment=None):
        self.capture_position()
        try:
            automatic_before = begin_review(self.document.native, text,
                                            exclude_off_record='off_record' not in self.disabled_auto_accept_rules)
        except ValueError as exc:
            self.document.status = str(exc)
            self.changed.emit()
            return
        self._review_undo.clear()
        self._review_redo.clear()
        self.document.status = 'Incoming updated. Review the suggested revisions.'
        self._automatic_review(automatic_before)
        self._finish_receive(warnings, alignment)

    def receive_reviewed(self, result, warnings, alignment=None):
        state = self.document.native
        if state.original != result.source:
            self.document.status = 'Original changed while processing. The AI review was not applied.'
            self.changed.emit()
            return
        self.capture_position()
        self._review_undo.clear()
        self._review_redo.clear()
        state.original, state.incoming, state.review = result.after_rules
        before_original, before_incoming, _ = result.before_rules
        self._record_automatic_review(result.off_record_undo, before_original, before_incoming,
                                      state.review['automatic_changes'])
        state.original, state.incoming, state.review = result.after_ai
        if result.after_ai[:2] != result.after_rules[:2]:
            self._review_undo.append(result.after_rules)
        self.document.status = f'AI-assisted review. {result.summary}'
        self._finish_receive(warnings, alignment)

    def _finish_receive(self, warnings, alignment):
        warnings = list(warnings)
        self.document.native.alignment = alignment
        self._validate_alignment(warnings)
        if self.playback:
            self.playback.timing = self._playback_timing()
        self.document.update_warnings(warnings)
        self.refresh()
        if self.playback:
            self.playback.show_position(self.playback.player.position())
        self.edited()
        self.schedule_restore()

    def _automatic_review(self, automatic_before=None):
        state = self.document.native
        original, incoming = state.original, state.incoming
        records = auto_accept(state, disabled_rules=self.disabled_auto_accept_rules)
        self._record_automatic_review(automatic_before, original, incoming, records)

    def _record_automatic_review(self, automatic_before, original, incoming, records):
        if records:
            # Keep the version marker on undo so reopening does not silently
            # reapply a batch that the user explicitly undid.
            if automatic_before:
                self._review_undo.append(automatic_before)
            else:
                undo_review = deepcopy(self.document.native.review)
                undo_review['automatic_changes'] = []
                self._review_undo.append((original, incoming, undo_review))
            self.document.status = f'{len(records)} changes automatically accepted or filtered. Review the remaining suggestions. Undo restores the batch.'
            self.document.dirty = True

    def set_busy(self, busy):
        self.document.busy = busy
        pending = self.document.native.original != self.document.native.incoming
        self.editor.setReadOnly(busy or pending)
        self.incoming_editor.setReadOnly(True)
        self.diff_view.setEnabled(not busy)

    def active_editor(self):
        return self.editor if not self.document.busy and not self.stack.currentIndex() and not self.editor.isReadOnly() else None
