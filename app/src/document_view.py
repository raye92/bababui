"""One structured document and its review transactions."""
from bisect import bisect_right
from copy import deepcopy
from PySide6.QtCore import Signal, Slot, QThread, QThreadPool, QTimer, Qt
from PySide6.QtGui import QFont, QTextCursor, QColor, QTextFormat
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QPushButton, QLabel, QSplitter, QTextEdit, QMessageBox
from app.src.accept_all_preview import AcceptAllPreviewEditor, AcceptAllPreviewTask, PreviewSignals
from app.src.native_editor import NativeTranscriptEditor
from app.src.review_view import ReviewView
from app.src.review_model import build_review, map_position
from app.src.review_editing import edit_review, resolve_review
from app.src.transcript_keyboard import TranscriptKeyboard
from app.src.review_colors import CHECK_BACKGROUND, CHECK_FOREGROUND
from app.src.inline_review import InlineReviewEditor
from app.src.page_view import PageView
from app.src.playback import DEFAULT_FORWARD_SECONDS, PlaybackBar
from app.src.casecat.anchors import utf16_index
from app.src.casecat.presentation import prepare_editor_presentation
from app.src.suggestions import distance_to_ranges, preview_ranges, preview_start, text_edits
from app.src.suggestion_filter import override_speaker, questionable_speaker_defaults
from app.src.notice_review import auto_accept_document, begin_document_review
from app.src.speech_alignment import NO_TIMESTAMPS, UNAVAILABLE, WAV_CHANGED


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
            self.model, self.review = self.decision()
            self.revisions = self.model.original, self.model.incoming
            for side, old, revision in zip(('original', 'incoming'), self.before, self.revisions):
                if old != revision:
                    job = self.job.with_revision(revision)
                    self.previews[side] = prepare_editor_presentation(job, self.bundle)
        except Exception as exc:
            self.error = exc


class DocumentView(QWidget):
    changed = Signal()
    notice_requested = Signal()

    def __init__(self, document, *, disabled_auto_accept_rules=frozenset(), forward_seconds=DEFAULT_FORWARD_SECONDS):
        super().__init__()
        if document.native is None:
            raise ValueError('An editor requires an imported CaseCAT job.')
        self.document = document
        self.disabled_auto_accept_rules = disabled_auto_accept_rules
        self.forward_seconds = forward_seconds
        automatic_before = None
        from app.src.suggestion_filter import LABEL, GENERIC
        if (document.native.review is None and document.native.original != document.native.incoming
                and any((m := LABEL.match(p)) and GENERIC.fullmatch(m['name']) for p in document.incoming.split('\n'))):
            automatic_before = begin_document_review(document.native, document.native.incoming.text, full_document=True,
                                            exclude_off_record='off_record' not in self.disabled_auto_accept_rules)
        self._updating = False
        self._position_pending = True
        self._restore_source = None
        self._restore_timer = QTimer(self, singleShot=True)
        self._restore_timer.timeout.connect(self.restore_position)
        self._native_history = {'original': {}, 'incoming': {}}
        self._review_undo, self._review_redo = [], []
        self._review_worker = None
        self._typing_run = None
        self._history_selection = None
        self._source_views_stale = False
        self.accept_all_preview = False
        self._preview_anchor = None
        self._preview_model = None
        self._preview_preparing = False
        # The task may finish after the tab closes. It keeps the signal sender
        # alive, and Qt disconnects the tab's slot when the tab is deleted.
        self._preview_signals = PreviewSignals()
        self._preview_signals.finished.connect(self._finish_accept_all_preview, Qt.QueuedConnection)
        self._format_signals = PreviewSignals()
        self._format_signals.finished.connect(self._finish_preview_format, Qt.QueuedConnection)
        self._format_timer = QTimer(self, singleShot=True, interval=500)
        self._format_timer.timeout.connect(self._prepare_preview_format)
        self._format_running = False
        self._needs_native_format = False
        if document.native.original != document.native.incoming or automatic_before:
            self._automatic_review(automatic_before)
        self.stack = QStackedWidget()
        self.original_stack = QStackedWidget()
        font = QFont('Courier New', 12)
        self.editor = NativeTranscriptEditor(font)
        self.incoming_editor = NativeTranscriptEditor(font)
        self.inline_editor = InlineReviewEditor(font)
        self.inline_editor.set_source_editors(self.editor, self.incoming_editor)
        self.inline_editor.selected.connect(self._select_clicked_edit)
        self.inline_editor.history_requested.connect(lambda undo: self.undo_review() if undo else self.redo_review())
        self.inline_editor.source_activated.connect(self._seek_review_passage)
        self.preview_editor = AcceptAllPreviewEditor(font)
        self.preview_editor.document().contentsChange.connect(self._preview_text_changed)
        self.preview_editor.native_edit_requested.connect(self._preview_native_edit)
        self.preview_editor.passage_clicked.connect(self._preview_clicked)
        self.preview_editor.history_requested.connect(lambda undo: self.undo_review() if undo else self.redo_review())
        self.editor.transaction_history = self._editor_history
        for editor in (self.editor, self.preview_editor):
            editor.history_available = lambda undo: bool(self._review_undo if undo else self._review_redo)
        self.smart_keys = False
        self.keyboard = TranscriptKeyboard(self)
        for editor in (self.editor, self.incoming_editor, self.preview_editor, self.inline_editor):
            editor.installEventFilter(self.keyboard)
        self.diff_view = ReviewView()
        self.diff_view.live_location = self._amended_location
        self.diff_view.requested.connect(self._start_review)
        self.diff_view.selection_changed.connect(self.highlight_suggestions)
        self.diff_view.selected.connect(self.select_suggestion)
        self.diff_view.navigated.connect(self._seek_selected_suggestion)
        self.diff_view.passage_clicked.connect(self._card_word_clicked)
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
        self.preview_page = PageView(self.preview_editor)
        self.original_stack.addWidget(self.preview_page)
        self.preview_loading = QLabel('Preparing Accept All preview…', alignment=Qt.AlignCenter)
        self.preview_loading.setFocusPolicy(Qt.StrongFocus)
        self.original_stack.addWidget(self.preview_loading)
        self.stack.addWidget(self.original_stack)
        self.stack.addWidget(self.incoming_page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.review_splitter = QSplitter(Qt.Horizontal)
        self.review_splitter.addWidget(self.stack)
        self.review_splitter.addWidget(self.diff_view)
        self.stack.setMinimumWidth(400)
        self.review_splitter.setCollapsible(0, False)
        self.diff_view.setMinimumWidth(260)
        self.review_splitter.setStretchFactor(0, 1)
        self.review_splitter.setStretchFactor(1, 1)
        self.review_splitter.setSizes([900, 380])
        layout.addWidget(self.review_splitter, 1)
        self.editor.transcript_clicked.connect(lambda: self._transcript_clicked(self.editor, 'original'))
        self.incoming_editor.transcript_clicked.connect(lambda: self._transcript_clicked(self.incoming_editor, 'incoming'))
        self.playback = None
        if document.native.alignment and not document.wav_path:
            self._validate_alignment(document.warnings)
        if document.wav_path:
            self.setup_playback(layout)
        self.editor.textChanged.connect(self._original_changed)
        self.incoming_editor.textChanged.connect(self._incoming_changed)
        self.stack.setCurrentIndex(document.view)
        self.refresh()
        self.schedule_restore()

    def offer_notice(self):
        self.notice_offer = banner = QWidget(self)
        row = QHBoxLayout(banner)
        row.setContentsMargins(8, 3, 8, 3)
        row.addWidget(QLabel('Add a notice PDF to fill the cover?'))
        upload, skip = QPushButton('Upload notice PDF'), QPushButton('Skip')
        row.addWidget(upload)
        row.addWidget(skip)
        row.addStretch()
        upload.clicked.connect(self.notice_requested)
        skip.clicked.connect(banner.hide)
        self.layout().insertWidget(0, banner)
        banner.show()

    def setup_playback(self, layout):
        doc = self.document
        self._validate_alignment(doc.warnings)
        self.playback = PlaybackBar(doc.wav_path, self._playback_timing(), self._playback_context, self,
                                    forward_seconds=self.forward_seconds)
        layout.addWidget(self.playback)
        if not getattr(self, '_playback_connected', False):
            self._playback_connected = True
            self.stack.currentChanged.connect(lambda _: self.playback.stop())

    def set_forward_seconds(self, seconds):
        self.forward_seconds = seconds
        if self.playback:
            self.playback.set_forward_seconds(seconds)

    def set_smart_keys(self, enabled):
        if self.smart_keys != enabled:
            self.smart_keys = enabled
            self.preview_editor.set_block_cursor(enabled)
            self.changed.emit()

    def replay_current_edit(self):
        if self._seek_selected_suggestion():
            self.playback.player.play()

    def _seek_selected_suggestion(self):
        if not self.playback or not self.diff_view.has_current:
            return False
        ranges = self.diff_view.changes[self.diff_view.current].ranges
        if not ranges:
            return False
        a, b, c, d = ranges[0]
        state = self.document.native
        targets = ((state.original, a, b), (state.incoming, c, d))
        prefer_incoming = state.alignment is not None or self.stack.currentIndex() == 1 or self._showing_accept_all_preview()
        if a == b or (c != d and prefer_incoming):
            targets = targets[::-1]
        return any(self.playback.seek_passage(*target) for target in targets)

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
            timing = AudioMap.from_job(doc.native.bundle, doc.native.job, doc.wav_path,
                                       bundled=doc.audio_override is None)
            return timing if any(time is not None for time in timing.stroke_ms) else None
        except (ValueError, OSError, wave.Error, EOFError):
            return None

    def active_view(self):
        if self.stack.currentIndex():
            return self.incoming_editor
        page = self.original_stack.currentWidget()
        return page.editor if isinstance(page, PageView) else None

    def _playback_context(self):
        editor = self.active_view()
        if editor is None:
            return None, None
        if editor is self.inline_editor:
            side, _ = editor.source_position()
        else:
            side = 'original' if editor is self.editor else 'incoming'
        return editor, getattr(self.document.native, side)

    def _seek_review_passage(self, side, position):
        if self.playback:
            revision = getattr(self.document.native, side)
            self.playback.seek_passage(revision, position)

    def _card_word_clicked(self, side, position):
        self._focus_passage(self.review_model.position_on(side, position, 'original'),
                            self.review_model.position_on(side, position, 'incoming'))
        if self.active_view() is self.inline_editor:
            self.inline_editor.set_source_position(side, position, edit_index=self.diff_view.current)
            self.inline_editor.ensureCursorVisible()
        self._seek_review_passage(side, position)

    def capture_position(self):
        self.document.view = self.stack.currentIndex()
        editor = self.active_view()
        if self._position_pending or editor is None:
            return
        if editor is self.preview_editor:
            self._preview_anchor = self._review_position()
            anchor = self._inline_anchor(*self._preview_anchor)
            position = self.inline_editor.display_position(*anchor)
            if position is not None:
                self.document.center_line = max(0, sum(1 for row in self.inline_editor.rows
                                                       if row.number and row.display_start <= position) - 1)
        else:
            self.document.center_line = editor.center_line()

    def schedule_restore(self, source_position=None):
        if self.active_view() is None and source_position is not None:
            self._preview_anchor = source_position
        self._position_pending = True
        self._restore_source = source_position
        self._restore_timer.start(0)

    def restore_position(self):
        editor = self.active_view()
        source_position, self._restore_source = self._restore_source, None
        self._position_pending = False
        if editor is None:
            return
        if source_position is None and editor is self.preview_editor:
            source_position = self._preview_anchor
        if source_position is None:
            editor.scroll_to_center_line(self.document.center_line)
        elif editor is self.inline_editor:
            editor.scroll_to_source_position(*self._inline_anchor(*source_position))
        else:
            side, offset = source_position
            target = 'original' if editor is self.editor else 'incoming'
            offset = self.review_model.position_on(side, offset, target)
            position = len(getattr(self.document, target)[:offset].encode('utf-16-le')) // 2
            lines = editor.page_lines()
            editor.scroll_to_center_line(bisect_right([line.position for line in lines], position) - 1)
        if source_position is not None:
            self.capture_position()

    def _inline_anchor(self, side, offset):
        if self.inline_editor.display_position(side, offset) is None:
            target = 'incoming' if side == 'original' else 'original'
            return target, self.review_model.position_on(side, offset, target)
        return side, offset

    def _review_position(self):
        if self._position_pending and self._restore_source is not None:
            return self._restore_source
        editor = self.active_view()
        if editor is None:
            return self._preview_anchor or ('original', 0)
        if editor is self.inline_editor:
            return editor.center_source_position()
        side = 'original' if editor is self.editor else 'incoming'
        middle = editor.verticalScrollBar().value() + editor.viewport().height() / 2
        page = int(middle // editor._page_height)
        lines = editor.page_lines((max(0, page - 1), page + 1))
        position = min(lines, key=lambda line: abs(line.y - middle)).position if lines else 0
        return side, utf16_index(editor.toPlainText(), position)

    def _restore_review_position(self, anchor, before):
        side, position = anchor
        old = before[1 if side == 'incoming' else 0].text
        editor = self.active_view()
        if editor is not self.inline_editor:
            side = 'original' if editor is self.editor else 'incoming'
        new = getattr(self.document, side)
        self.schedule_restore((side, map_position(position, text_edits(old, new))))

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
        if side == 'original' and not editor.history_action:
            self._record_typing(position, removed, added, editor, atomic=pending is not None)
        if doc.native.review and side == 'incoming':
            doc.native.review.pop('pending_decisions', None)
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
            if self.playback and hasattr(self.playback.timing, 'track_edit'):
                self.playback.timing.track_edit(old, revision, utf16_index(old.text, start),
                                                utf16_index(old.text, end), new_text[new_start:new_end])
        doc.set_text(side, revision.text, revision=revision)
        if side == 'original':
            doc.native.review = None
            doc.set_text('incoming', revision.text, revision=revision)

    def _native_whole_text(self, side, editor, text):
        doc = self.document
        if self._updating:
            return
        self._typing_run = None
        self._review_undo.clear()
        self._review_redo.clear()
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

    def _showing_accept_all_preview(self):
        return self.accept_all_preview and not self.stack.currentIndex() and bool(self.review_model.edits)

    def _preview_matches(self, model):
        return (model is not None and self.review_model.original is model.original
                and self.review_model.incoming is model.incoming)

    def _amended_location(self, change):
        if self._updating or not self._source_views_stale or self.active_view() is not self.preview_editor:
            return None
        editor = self.preview_editor
        position = editor._qt_position(preview_start(change, 'incoming'))
        cursor = QTextCursor(editor.document())
        cursor.setPosition(position)
        y = editor.cursorRect(cursor).center().y() + editor.verticalScrollBar().value()
        page = max(0, int(y // editor._page_height))
        lines = editor.page_lines((page, page))
        index = bisect_right(lines, position, key=lambda line: line.position) - 1
        return lines[index] if index >= 0 else None

    def set_accept_all_preview(self, enabled):
        if enabled == self.accept_all_preview:
            return
        anchor = self._review_position()
        self.accept_all_preview = enabled
        if enabled:
            self.stack.setCurrentIndex(0)
        elif self._source_views_stale:
            self.refresh(model=self.review_model)
        self._update_original_page()
        self.schedule_restore(anchor)
        self.document.view = self.stack.currentIndex()
        self.changed.emit()

    def _update_original_page(self):
        if self.accept_all_preview and self._source_views_stale and self._preview_matches(self._preview_model):
            page = self.preview_page
        elif not self.review_model.edits:
            page = self.original_page
        elif not self.accept_all_preview:
            page = self.inline_page
        elif self._preview_matches(self._preview_model):
            page = self.preview_page
        else:
            page = self.preview_loading
            if not self.stack.currentIndex() and not self._preview_preparing:
                state = self.document.native
                self._preview_preparing = True
                QThreadPool.globalInstance().start(AcceptAllPreviewTask(
                    self.review_model, state.bundle, state.job, self._preview_signals))
        previous = self.original_stack.currentWidget()
        if previous is not page:
            self.original_stack.setCurrentWidget(page)
            if (self.playback and not self.stack.currentIndex()
                    and self.preview_page in (previous, page)):
                self.playback.show_position(self.playback.player.position())
        if self.diff_view.has_changes:
            editor = self.active_view()
            if editor is self.inline_editor:
                editor = self.editor
            side = 'original' if editor is self.editor else 'incoming'
            self.diff_view.set_page_lines(editor.page_lines() if editor is not None else (), side)

    @Slot(object, object, str)
    def _finish_accept_all_preview(self, model, result, error):
        self._preview_preparing = False
        if not self.accept_all_preview:
            return
        if not self._preview_matches(model):
            self._update_original_page()
            return
        if result is None:
            self.document.status = f'Could not prepare Accept All preview. {error}'
            self.set_accept_all_preview(False)
            return
        job, prepared = result
        selected = self.diff_view.current if self.diff_view.has_current else -1
        self.preview_editor.load_preview(self.document.native.bundle, job, prepared, model, selected)
        self._preview_model = model
        self.preview_editor.setReadOnly(self.document.busy)
        self._update_original_page()
        self._restore_history_selection()
        if not self.stack.currentIndex():
            self.schedule_restore(self._preview_anchor)

    def _record_typing(self, position, removed, added, editor, *, atomic=False):
        state = self.document.native
        single_insert = (added in (1, 2) and removed == 0 and not atomic)
        if not single_insert or self._typing_run != (editor, position):
            self._review_undo.append((state.original, state.incoming, state.review,
                                      (position, position + removed, getattr(editor, 'caret_affinity', None))))
        self._typing_run = (editor, position + added) if single_insert else None
        self._review_redo.clear()

    def _editor_history(self, undo):
        history = self._review_undo if undo else self._review_redo
        if not history:
            return False
        (self.undo_review if undo else self.redo_review)()
        return True

    def _restore_history_selection(self):
        if self._history_selection is None:
            return
        editor = self.active_editor()
        if editor is not None:
            anchor, position, affinity = self._history_selection
            self._history_selection = None
            cursor = editor.textCursor()
            last = editor.document().characterCount() - 1
            cursor.setPosition(min(anchor, last))
            cursor.setPosition(min(position, last), QTextCursor.KeepAnchor)
            editor.setTextCursor(cursor)
            if editor is self.preview_editor:
                editor.caret_affinity, editor.affinity_position = affinity, cursor.position()

    def _preview_text_changed(self, position, removed, added):
        editor = self.preview_editor
        if self._updating or editor.whole_text_update or not self._preview_matches(self._preview_model):
            return
        old = self.review_model.incoming.text
        new = editor.toPlainText()
        if old == new:
            return
        start, end = (utf16_index(old, p) for p in (position, position + removed))
        finish = utf16_index(new, position + added)
        self._edit_preview(start, end, new[start:finish], position, removed, added)

    @Slot(object, int, int, str, int)
    def _preview_native_edit(self, revision, start, end, replacement, caret):
        if self.document.busy or not self._preview_matches(self._preview_model):
            return
        position = self.preview_editor._qt_position(start)
        self._edit_preview(start, end, replacement, position, end-start, len(replacement),
                           native_revision=revision, caret=caret)

    def _edit_preview(self, start, end, replacement, position, removed, added, *, native_revision=None, caret=None):
        state = self.document.native
        editor = self.preview_editor
        affinity = editor.caret_affinity if position == editor.affinity_position else None
        before = self.review_model
        try:
            model, review = edit_review(before, state.review, 'incoming', start, end, replacement,
                                        affinity=affinity, native_revision=native_revision)
        except ValueError as exc:
            self.document.status = str(exc)
            if native_revision is None:
                editor.revert_text_edit(position, added, before.incoming.text[start:end])
            self.changed.emit()
            return
        if model is before:
            return
        self._record_typing(position, removed, added, editor, atomic=native_revision is not None)
        self._updating = True
        try:
            self.review_model = self._preview_model = model
            state.original, state.incoming, state.review = model.original, model.incoming, review
            if self.playback and hasattr(self.playback.timing, 'track_edit'):
                self.playback.timing.track_edit(before.incoming, model.incoming, start, end, replacement)
            if native_revision is not None:
                editor.sync_review_revision(before.incoming, model.incoming, start, end, replacement)
            else:
                editor.sync_native_text(model.incoming.text)
            if not self._needs_native_format:
                self._needs_native_format = native_revision is not None or editor.needs_native_format(
                    before.incoming, start, end, replacement, position)
            editor.invalidate_paragraphs(before.incoming.text, start, end, replacement, model.incoming.text)
            if caret is not None:
                cursor = editor.textCursor()
                cursor.setPosition(editor._qt_position(min(len(model.incoming.text), caret)))
                editor.setTextCursor(cursor)
            editor.affinity_position = position + added
            editor.caret_affinity = 'left' if replacement else affinity
            self._source_views_stale = True
            self.diff_view.amend_model(model, review)
            editor.update_review(model, self.diff_view.current if self.diff_view.has_current else -1)
            if not model.edits:
                self.diff_view.setVisible(bool(review.get('evidence', {}).get('speakers')))
            self._format_timer.start()
        finally:
            self._updating = False
        self.edited()

    def _prepare_preview_format(self):
        if (self._format_running or not self._source_views_stale
                or self.active_view() is not self.preview_editor):
            return
        if not self._needs_native_format:
            self._refresh_preview_sidebar()
            return
        self._format_running = True
        state = self.document.native
        QThreadPool.globalInstance().start(AcceptAllPreviewTask(
            self.review_model, state.bundle, state.job, self._format_signals))

    @Slot(object, object, str)
    def _finish_preview_format(self, model, result, error):
        self._format_running = False
        if self.active_view() is not self.preview_editor or not self._source_views_stale:
            return
        if model is not self.review_model:
            if not self._format_timer.isActive():
                self._format_timer.start()
            return
        if result is None:
            self.document.status = f'Could not update preview formatting. {error}'
            self.changed.emit()
            return
        self._updating = True
        try:
            self.preview_editor.apply_prepared(*result, model, self.diff_view.current)
            self._needs_native_format = False
        finally:
            self._updating = False
        self._refresh_preview_sidebar()

    def _refresh_preview_sidebar(self):
        if (self.diff_view.review or {}).get('evidence', {}).get('speakers'):
            self.diff_view._speakers(self.review_model.original)
            self.diff_view.filter_speaker(self.diff_view.speaker_filter, select=False)
        self.diff_view._update_heading()

    @Slot(int, int)
    def _preview_clicked(self, index, position):
        if self.active_view() is not self.preview_editor:
            return
        if index >= 0 and not self.document.busy:
            self._select_clicked_edit(index)
        self._seek_review_passage('incoming', position)

    def refresh(self, *, previews=None, model=None):
        previous_model = getattr(self, 'review_model', None)
        anchor = (self._review_position() if self.accept_all_preview and previous_model is not None
                  and not self.stack.currentIndex() else None)
        self._updating = True
        doc = self.document
        previews = previews or {}
        self._set_text(self.editor, doc.original, previews.get('original'))
        self._set_text(self.incoming_editor, doc.incoming, previews.get('incoming'))
        self.review_model = model if model is not None else build_review(doc.native.original, doc.native.incoming, doc.native.review)
        self.diff_view.set_model(self.review_model, review=doc.native.review)
        self.inline_editor.set_model(
            self.review_model, unmatched_speakers=self.diff_view.unmatched_speaker_ranges)
        self._source_views_stale = False
        self._needs_native_format = False
        self._update_original_page()
        self.inline_page.fit_page()
        self.original_page.fit_page()
        self.incoming_page.fit_page()
        self.diff_view.setVisible(self.diff_view.has_changes or bool((doc.native.review or {}).get('evidence', {}).get('speakers')))
        self._updating = False
        self.highlight_suggestions()
        self.set_busy(doc.busy)
        if anchor is not None and not self._preview_matches(previous_model):
            self._restore_review_position(anchor, (previous_model.original, previous_model.incoming))

    def highlight_suggestions(self):
        if self._updating:
            return
        selected = self.diff_view.current if self.diff_view.has_current else -1
        if self._source_views_stale and self.active_view() is self.preview_editor:
            self.preview_editor.highlight_edit(selected)
            return
        self.inline_editor.highlight_edit(selected)
        for side, editor in (('original', self.editor), ('incoming', self.incoming_editor)):
            text = getattr(self.document, side)
            marks, insertions = [], []
            for index, change in enumerate(self.diff_view.changes):
                for a, b, c, d in preview_ranges(change):
                    start, end = (a, b) if side == 'original' else (c, d)
                    if index == selected:
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
                    if index == selected:
                        mark.format.setBackground(QColor('#ffaaa5' if side == 'original' else '#7ee2a8'))
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
            editor._selected_review = selected
            editor.set_review_marks(marks, insertions)
        if self._preview_matches(self._preview_model):
            self.preview_editor.highlight_edit(selected)

    def _select_clicked_edit(self, index):
        if self._review_worker is None:
            self.diff_view.select(index, focus_passage=False)

    def select_suggestion(self, index):
        if not 0 <= index < len(self.diff_view.changes):
            return
        change = self.diff_view.changes[index]
        self.inline_editor.focus_edit(index, prefer_incoming=self.document.native.alignment is not None)
        if change.ranges:
            self._focus_passage(preview_start(change, 'original'), preview_start(change, 'incoming'))

    def _focus_passage(self, original_start, incoming_start):
        self._restore_timer.stop()
        self._restore_source = None
        self._position_pending = False
        if self._showing_accept_all_preview():
            self._preview_anchor = ('incoming', incoming_start)
            if self.active_view() is None:
                return
            side, editor = 'incoming', self.preview_editor
        elif self.stack.currentIndex():
            side, editor = 'incoming', self.incoming_editor
        else:
            side, editor = 'original', self.editor
        start = incoming_start if side == 'incoming' else original_start
        cursor = editor.textCursor()
        cursor.setPosition(len(getattr(self.document, side)[:start].encode('utf-16-le')) // 2)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        lines = editor.page_lines()
        line = next((i for i in range(len(lines)-1, -1, -1)
                     if lines[i].position <= cursor.position()), 0)
        editor.scroll_to_center_line(line)

    def _transcript_clicked(self, editor, side):
        position = utf16_index(getattr(self.document, side), editor.textCursor().position())
        self._seek_review_passage(side, position)
        if self._review_worker is not None:
            return
        at_end = None
        offset = 0 if side == 'original' else 2
        for index, change in enumerate(self.diff_view.changes):
            if distance_to_ranges(change.ranges, side, position, position) == 0:
                self.diff_view.select(index, focus_passage=False)
                return
            if at_end is None and any(span[offset + 1] == position for span in change.ranges):
                at_end = index
        if at_end is not None:
            self.diff_view.select(at_end, focus_passage=False)

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
                ranges = self.review_model.ranges
                questionable = questionable_speaker_defaults(before[2], ranges) if accept else []
                if questionable:
                    names = '\n'.join(f'{speaker} → {name}' for speaker, name in questionable)
                    if QMessageBox.question(
                            self, 'Check speaker names',
                            'These automatic names have zero matching passages or are shared by multiple speaker tags.\n\n'
                            f'{names}\n\nAccept all suggestions with these names?',
                            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
                        return
            else:
                change = self.diff_view.changes[index]
                ranges = change.ranges
            snapshot = self.review_model
            decision = lambda: resolve_review(snapshot, before[2], index, accept)
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
                self._seek_selected_suggestion()
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
        self._apply_review(worker.index, worker.before, (worker.model, worker.review), worker.ranges,
                           previews=worker.previews)

    def _apply_review(self, index, before, decision, ranges, *, previews=None):
        model, review = decision
        result = model.original, model.incoming
        self._typing_run = None
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
        state.review = review
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
                self._seek_selected_suggestion()
        elif not self.diff_view.changes and ranges:
            self._focus_passage(ranges[0][0], ranges[0][2])
            if self.playback:
                retained = state.original if result[0] is before[0] else state.incoming
                self.playback.seek_passage(retained, *ranges[0][side])
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
            self._typing_run = None
            state = self.document.native
            before = state.original, state.incoming, deepcopy(state.review)
            editor = self.active_editor()
            if editor is not None:
                cursor = editor.textCursor()
                target.append((*before, (cursor.anchor(), cursor.position(), getattr(editor, 'caret_affinity', None))))
            else:
                target.append(before)
            anchor = self._review_position()
            saved = source.pop()
            self._history_selection = saved[3] if len(saved) > 3 else None
            state.original, state.incoming, state.review = saved[:3]
            self.refresh()
            self._restore_history_selection()
            self._restore_review_position(anchor, before)
            self.edited()

    def undo_review(self): self._review_history(self._review_undo, self._review_redo)
    def redo_review(self): self._review_history(self._review_redo, self._review_undo)

    def _original_changed(self):
        if not self._updating:
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
        anchor = self._review_position() if self.accept_all_preview else None
        self.capture_position()
        if self._review_worker is None:
            self.refresh()
        self.stack.setCurrentIndex(1-self.stack.currentIndex())
        self._update_original_page()
        self.document.view = self.stack.currentIndex()
        self.schedule_restore(anchor)
        self.changed.emit()

    def receive_transcription(self, warnings, alignment):
        self.document.status = 'Raw transcription saved.'
        self._finish_receive(warnings, alignment)

    def receive(self, text, warnings, alignment=None):
        self.capture_position()
        try:
            automatic_before = begin_document_review(self.document.native, text,
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
        self.document.status = 'Automated review complete.'
        self._record_automatic_review(result.off_record_undo, before_original, before_incoming,
                                      state.review['automatic_changes'])
        state.original, state.incoming, state.review = result.after_ai
        if result.after_ai[:2] != result.after_rules[:2]:
            self._review_undo.append(result.after_rules)
        if result.summary:
            self.document.status = f'AI-assisted review. {result.summary}'
        self._finish_receive(warnings, alignment)

    def _finish_receive(self, warnings, alignment):
        warnings = list(warnings)
        if alignment is not None:
            self.document.native.alignment = alignment
        self._validate_alignment(warnings)
        if self.playback:
            self.playback.timing = self._playback_timing()
            if self.playback.timing and any(w in (NO_TIMESTAMPS, UNAVAILABLE) for w in warnings):
                source = 'saved speech timing for this WAV' if self.document.native.alignment else 'CaseCAT recording times'
                warnings.append(f'Playback uses {source}.')
        self.document.update_warnings(warnings)
        self.refresh()
        if self.playback:
            self.playback.show_position(self.playback.player.position())
        self.edited()
        if self._restore_source is None:
            self.schedule_restore()

    def _automatic_review(self, automatic_before=None):
        state = self.document.native
        original, incoming = state.original, state.incoming
        previous_version = (state.review or {}).get('grouping_version')
        undo = []
        records = auto_accept_document(state, disabled_rules=self.disabled_auto_accept_rules, remember_undo=undo.append)
        self._record_automatic_review(undo[0] if undo else automatic_before, original, incoming, records)
        if state.review and previous_version != state.review.get('grouping_version'):
            self.document.dirty = True

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
        if hasattr(self, 'notice_offer'):
            self.notice_offer.setEnabled(not busy)
        pending = self.document.native.original != self.document.native.incoming
        self.editor.setReadOnly(busy or pending)
        self.preview_editor.setReadOnly(busy or not self._preview_matches(self._preview_model))
        self.incoming_editor.setReadOnly(True)
        self.diff_view.setEnabled(not busy)

    def active_editor(self):
        editor = self.active_view()
        return editor if editor is not None and not self.document.busy and not editor.isReadOnly() else None
