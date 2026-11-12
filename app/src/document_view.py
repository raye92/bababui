"""One structured document and its review transactions."""
from PySide6.QtCore import Signal, QTimer, Qt
from PySide6.QtGui import QFont, QShortcut, QKeySequence, QTextCursor, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QPushButton, QLabel, QSplitter, QTextEdit
from app.src.native_editor import NativeTranscriptEditor
from app.src.review_view import ReviewView
from app.src.casecat.anchors import utf16_index
from app.src.suggestions import propose, resolve


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


class DocumentView(QWidget):
    changed = Signal()

    def __init__(self, document):
        super().__init__()
        if document.native is None:
            raise ValueError('An editor requires an imported CaseCAT job.')
        self.document = document
        self._updating = False
        self._position_pending = True
        self._native_history = {'original': {}, 'incoming': {}}
        self._review_undo, self._review_redo = [], []
        self.stack = QStackedWidget()
        self.original_stack = QStackedWidget()
        font = QFont('Courier New', 12)
        self.editor = NativeTranscriptEditor(font)
        self.incoming_editor = NativeTranscriptEditor(font)
        self.diff_view = ReviewView()
        self.diff_view.requested.connect(self.review)
        self.diff_view.selected.connect(self.select_suggestion)
        for side, editor in (('original', self.editor), ('incoming', self.incoming_editor)):
            editor.native_revision_at_step = lambda steps, s=side: self._native_history[s].get(steps)
            editor.whole_text_set.connect(lambda text, s=side, e=editor: self._native_whole_text(s, e, text))
            editor.document().contentsChange.connect(lambda p, r, a, s=side, e=editor: self._native_edit(s, e, p, r, a))
        self.original_stack.addWidget(self.editor)
        self.stack.addWidget(self.original_stack)
        self.stack.addWidget(self.incoming_editor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.review_splitter = QSplitter(Qt.Horizontal)
        self.review_splitter.addWidget(self.stack)
        self.review_splitter.addWidget(self.diff_view)
        self.diff_view.setMinimumWidth(260)
        self.review_splitter.setStretchFactor(0, 1)
        self.review_splitter.setSizes([900, 300])
        layout.addWidget(self.review_splitter, 1)
        self.editor.transcript_clicked.connect(lambda: self.select_at_cursor(self.editor, 'original'))
        self.incoming_editor.transcript_clicked.connect(lambda: self.select_at_cursor(self.incoming_editor, 'incoming'))
        self.playback = None
        if document.wav_path:
            self.setup_playback(layout)
        self.editor.textChanged.connect(self._original_changed)
        self.incoming_editor.textChanged.connect(self._incoming_changed)
        self.refresh()
        self.stack.setCurrentIndex(document.view)
        self.schedule_restore()

    def setup_playback(self, layout):
        from app.src.casecat.timing import AudioMap
        from app.src.playback import PlaybackBar
        from PySide6.QtCore import Qt
        import wave
        doc = self.document
        try:
            timing = AudioMap.from_job(doc.native.bundle, doc.native.job, doc.wav_path)
        except (ValueError, OSError, wave.Error, EOFError):
            timing = None
        self.playback = PlaybackBar(doc.wav_path, timing, self._playback_context, self)
        layout.addWidget(self.playback)
        if not getattr(self, '_playback_connected', False):
            self._playback_connected = True
            self.stack.currentChanged.connect(lambda _: self.playback.stop())
            for editor in (self.editor, self.incoming_editor):
                editor.transcript_clicked.connect(lambda: self.playback.seek_from_cursor())
            for key, method in (('Shift+F9', 'seek_from_cursor'), ('Ctrl+F9', 'stop')):
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(lambda m=method: getattr(self.playback, m)())

    def active_view(self):
        return self.incoming_editor if self.stack.currentIndex() else self.original_stack.currentWidget()

    def _playback_context(self):
        editor = self.incoming_editor if self.stack.currentIndex() else self.editor
        return editor, getattr(self.document.native, 'incoming' if self.stack.currentIndex() else 'original')

    def _seek_review_passage(self, side, position):
        if self.playback:
            revision = getattr(self.document.native, side)
            self.playback.seek_passage(revision, utf16_index(revision.text, position))

    def capture_position(self):
        self.document.view = self.stack.currentIndex()
        if not self._position_pending:
            self.document.center_line = self.active_view().center_line()

    def schedule_restore(self):
        self._position_pending = True
        QTimer.singleShot(0, self.restore_position)

    def restore_position(self):
        self.active_view().scroll_to_center_line(self.document.center_line)
        self._position_pending = False

    def _set_text(self, editor, text):
        changed = editor.toPlainText() != text
        side = 'original' if editor is self.editor else 'incoming'
        state = self.document.native
        revision = getattr(state, side)
        editor.set_native_source(state.bundle, state.job.with_revision(revision))
        if changed:
            editor.setPlainText(text)
        steps = editor.document().availableUndoSteps()
        if changed or not self._native_history[side]:
            self._native_history[side] = {steps: revision}
        elif self._native_history[side].get(steps) != revision:
            editor.document().clearUndoRedoStacks()
            self._native_history[side] = {0: revision}

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
            doc.set_text('incoming', revision.text, revision=revision)
        self.edited()

    def refresh(self):
        self._updating = True
        doc = self.document
        self._set_text(self.editor, doc.original)
        self._set_text(self.incoming_editor, doc.incoming)
        self.diff_view.set_revisions(doc.native.original, doc.native.incoming)
        self.original_stack.setCurrentWidget(self.editor)
        self.diff_view.setVisible(self.diff_view.has_changes)
        self.highlight_suggestions()
        self._updating = False
        self.set_busy(doc.busy)

    def highlight_suggestions(self):
        for side, editor in (('original', self.editor), ('incoming', self.incoming_editor)):
            text = getattr(self.document, side)
            marks, insertions = [], []
            for index, change in enumerate(self.diff_view.changes):
                for a, b, c, d in change.ranges:
                    start, end = (a, b) if side == 'original' else (c, d)
                    if start == end:
                        insertions.append((len(text[:start].encode('utf-16-le')) // 2, index))
                        continue
                    mark = QTextEdit.ExtraSelection()
                    mark.cursor = QTextCursor(editor.document())
                    mark.cursor.setPosition(len(text[:start].encode('utf-16-le')) // 2)
                    mark.cursor.setPosition(len(text[:end].encode('utf-16-le')) // 2, QTextCursor.KeepAnchor)
                    mark.format.setBackground(QColor('#ffd7d5' if side == 'original' else '#ccffd8'))
                    mark.format.setForeground(QColor('#82071e' if side == 'original' else '#116329'))
                    marks.append(mark)
            editor.set_review_marks(marks, insertions)

    def select_suggestion(self, index):
        if not 0 <= index < len(self.diff_view.changes):
            return
        change = self.diff_view.changes[index]
        if change.ranges:
            side = 'incoming' if self.stack.currentIndex() else 'original'
            editor = self.incoming_editor if self.stack.currentIndex() else self.editor
            start = change.ranges[0][2 if side == 'incoming' else 0]
            cursor = editor.textCursor()
            cursor.setPosition(len(getattr(self.document, side)[:start].encode('utf-16-le')) // 2)
            editor.setTextCursor(cursor)
            editor.ensureCursorVisible()

    def select_at_cursor(self, editor, side):
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

    def review(self, index, accept):
        if self.document.busy:
            return
        state = self.document.native
        before = state.original, state.incoming
        try:
            result = resolve(*before, self.diff_view.changes[index], accept)
        except (ValueError, IndexError) as exc:
            self.document.status = str(exc)
            self.refresh()
            return
        self._review_undo.append(before)
        self._review_redo.clear()
        state.original, state.incoming = result
        self.refresh()
        self.edited()

    def _review_history(self, source, target):
        if source and not self.document.busy:
            state = self.document.native
            target.append((state.original, state.incoming))
            state.original, state.incoming = source.pop()
            self.refresh()
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
        self.refresh()
        self.stack.setCurrentIndex(1-self.stack.currentIndex())
        self.document.view = self.stack.currentIndex()
        self.schedule_restore()
        self.changed.emit()

    def receive(self, text, warnings):
        self.capture_position()
        try:
            proposal = propose(self.document.native.original, text)
        except ValueError as exc:
            self.document.status = str(exc)
            self.changed.emit()
            return
        self.document.native.incoming = proposal
        self._review_undo.clear()
        self._review_redo.clear()
        self.document.warnings = list(dict.fromkeys([*self.document.native.job.warnings, *warnings]))
        self.document.status = 'Incoming updated. Review the suggested revisions.'
        self.refresh()
        self.edited()
        self.schedule_restore()

    def set_busy(self, busy):
        self.document.busy = busy
        pending = self.document.native.original != self.document.native.incoming
        self.editor.setReadOnly(busy or pending)
        self.incoming_editor.setReadOnly(True)
        self.diff_view.setEnabled(not busy)

    def active_editor(self):
        return self.editor if not self.document.busy and not self.stack.currentIndex() and not self.editor.isReadOnly() else None
