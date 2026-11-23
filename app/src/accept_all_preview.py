"""Render the accepted transcript while its suggestions are pending."""
import re

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QTextCursor
from PySide6.QtWidgets import QTextEdit

from app.src.casecat.anchors import utf16_index
from app.src.casecat.presentation import prepare_editor_presentation
from app.src.native_editor import NativeTranscriptEditor
from app.src.review_colors import ADDITION_BACKGROUND, draw_focus_outlines
from app.src.suggestions import distance_to_ranges, preview_ranges, resolve_all


class PreviewSignals(QObject):
    finished = Signal(object, object, str)


class AcceptAllPreviewTask(QRunnable):
    def __init__(self, model, bundle, job, signals):
        super().__init__()
        self.model, self.bundle, self.job = model, bundle, job
        self.signals = signals

    def run(self):
        model = self.model
        try:
            revision, _ = resolve_all(model.original, model.incoming, model.ranges, True)
            job = self.job.with_revision(revision)
            prepared = prepare_editor_presentation(job, self.bundle)
        except Exception as exc:
            self.signals.finished.emit(model, None, str(exc))
        else:
            self.signals.finished.emit(model, (job, prepared), '')


class AcceptAllPreviewEditor(NativeTranscriptEditor):
    passage_clicked = Signal(int, int)
    history_requested = Signal(bool)
    native_edit_requested = Signal(object, int, int, str, int)

    def __init__(self, font):
        super().__init__(font)
        self.setReadOnly(True)
        self._text = ''
        self._edits, self._highlights = (), []
        self._focused = []
        self.caret_affinity = None
        self.affinity_position = -1
        self._block_styles = []

    def load_preview(self, bundle, job, prepared, model, selected):
        self.set_native_source(bundle, job)
        self.setPlainText(job.text, prepared=prepared)
        self._block_styles = [(self._paragraph_styles.get(m.start()), m.start() in self._page_breaks)
                              for m in re.finditer('^', job.text, re.MULTILINE)]
        self.update_review(model, selected)

    def invalidate_paragraphs(self, before, start, end, replacement, after):
        first = before.count('\n', 0, start)
        removed = before.count('\n', start, end)
        inserted = replacement.count('\n')
        if before[:start] + replacement + before[end:] == after:
            self._block_styles[first:first + removed + 1] = [None] * (inserted + 1)
        else:
            # A linked field operation can change several distant paragraphs.
            self._block_styles = []

    def needs_native_format(self, revision, start, end, replacement, qt_position):
        """Qt already reflows ordinary wording within an existing body paragraph."""
        from shared.transcript_formatting import TranscriptFormatter
        text = revision.text
        if any(not c.isalnum() for c in replacement + text[start:end]):
            return True
        block = self.document().findBlock(qt_position)
        first = text.rfind('\n', 0, start) + 1
        last = text.find('\n', end)
        if last < 0:
            last = len(text)
        old, new = text[first:last], block.text()
        if (not old or not new or old[0].isspace() or new[0].isspace()
                or '\u00a0' in new or '\u2011' in new or block.blockFormat().pageBreakPolicy()
                or TranscriptFormatter.examination_heading.fullmatch(old)
                or TranscriptFormatter.examination_heading.fullmatch(new)):
            return True
        if getattr(self._paragraph_styles, 'caption_tables', ()) and QTextCursor(block).currentTable():
            return True
        return any(first <= e.start <= last or e.start < first < e.end for e in revision.elements)

    def sync_review_revision(self, before, after, start, end, replacement):
        if before.text == after.text:
            return
        if before.text[:start] + replacement + before.text[end:] == after.text:
            patches = [(start, end, replacement)]
        else:
            # A filled field can occur on multiple distant pages. The native
            # elements already describe those ranges, even inside a Qt table.
            from app.src.review_editing import field_edits
            patches = [(a, b, after.text[c:d]) for a, b, c, d in field_edits(before, after)]
            if not patches:
                self.sync_native_text(after.text)
                return
        cursor = QTextCursor(self.document())
        with QSignalBlocker(self), QSignalBlocker(self.document()):
            cursor.beginEditBlock()
            for a, b, content in reversed(patches):
                cursor.setPosition(before.utf16_offset(a))
                cursor.setPosition(before.utf16_offset(b), QTextCursor.KeepAnchor)
                cursor.insertText(content.replace('-', '\u2011'))
            cursor.endEditBlock()

    def revert_text_edit(self, position, added, removed_text):
        """Reverse the reported Qt change at its original UTF-16 position."""
        cursor = QTextCursor(self.document())
        with QSignalBlocker(self), QSignalBlocker(self.document()):
            cursor.joinPreviousEditBlock()
            cursor.setPosition(position)
            cursor.setPosition(position + added, QTextCursor.KeepAnchor)
            cursor.insertText(removed_text.replace('-', '\u2011'))
            cursor.endEditBlock()

    def apply_prepared(self, job, prepared, model, selected):
        """Update changed Qt blocks in place, keeping the live caret and selection."""
        plain = job.text
        display = self._presentation_text(plain, prepared)
        tables = getattr(self._paragraph_styles, 'caption_tables', ())
        document = self.document()
        cursor = QTextCursor(document)
        actual_tables = document.rootFrame().childFrames()
        if len(tables) != len(actual_tables) or any(
                frame.firstPosition() != len(plain[:table.start + 1].encode('utf-16-le')) // 2
                for table, frame in zip(tables, actual_tables)):
            anchor, position = self.textCursor().anchor(), self.textCursor().position()
            scroll = self.verticalScrollBar().value()
            self.load_preview(self._native_source[0], job, prepared, model, selected)
            cursor.setPosition(min(anchor, document.characterCount() - 1))
            cursor.setPosition(min(position, document.characterCount() - 1), QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
            self.verticalScrollBar().setValue(scroll)
            return
        roles, changed = [], []
        logical = qt_offset = 0
        with QSignalBlocker(self), QSignalBlocker(document):
            cursor.beginEditBlock()
            for index, line in enumerate(display.split('\n')):
                role = self._paragraph_styles.get(logical), logical in self._page_breaks
                if index >= len(self._block_styles) or role != self._block_styles[index]:
                    changed.append((logical, qt_offset))
                    block = document.findBlock(qt_offset)
                    raw = block.text()
                    if raw != line and len(raw) == len(line):
                        offset = qt_offset
                        for old, wanted in zip(raw, line):
                            width = 2 if ord(old) > 0xffff else 1
                            if old != wanted and {old, wanted} in ({' ', '\u00a0'}, {'-', '\u2011'}):
                                cursor.setPosition(offset)
                                cursor.setPosition(offset + width, QTextCursor.KeepAnchor)
                                cursor.insertText(wanted)
                            offset += width
                roles.append(role)
                logical += len(line) + 1
                qt_offset += (len(line) if line.isascii() else len(line.encode('utf-16-le')) // 2) + 1
            self._apply_paragraph_styles(changed)
            if changed and changed[0][0] == 0:
                self._align_page_top()
            cursor.endEditBlock()
        self._block_styles = roles
        self.viewport().update()

    def update_review(self, model, selected):
        self._text, self._edits = model.incoming.text, model.edits
        bundle, job = self._native_source
        self._native_source = bundle, job.with_revision(model.incoming)
        self._highlights = []
        marks = []
        for index, edit in enumerate(self._edits):
            for _, _, start, end in preview_ranges(edit) or ((0, 0, 0, 0),):
                # Qt paints a selection of a paragraph separator as an empty
                # colored cell. Keep a caret for ranges with no visible text.
                fragments = [(start + match.start(), start + match.end())
                             for match in re.finditer(r'[^\n]+', self._text[start:end])]
                for first, last in fragments or [(start, start)]:
                    cursor = QTextCursor(self.document())
                    cursor.setPosition(model.incoming.utf16_offset(first))
                    cursor.setPosition(model.incoming.utf16_offset(last), QTextCursor.KeepAnchor)
                    self._highlights.append((first, last, index, cursor))
                    if first == last:
                        continue
                    mark = QTextEdit.ExtraSelection()
                    mark.cursor = cursor
                    mark.format.setBackground(QColor(ADDITION_BACKGROUND))
                    mark.format.setForeground(QColor('#1e5531'))
                    marks.append(mark)
        self.set_review_marks(marks, [])
        self.highlight_edit(selected)

    def highlight_edit(self, selected):
        self._focused = [cursor for _, _, index, cursor in self._highlights if index == selected]
        self.viewport().update()

    def apply_native_revision(self, revision, position=None, *, edit_range=None):
        if self.isReadOnly():
            return
        before = self._native_source[1].revision
        cursor = self.textCursor()
        start, end = edit_range or tuple(utf16_index(before.text, p) for p in
                                         (cursor.selectionStart(), cursor.selectionEnd()))
        length = len(revision.text) - len(before.text) + end - start
        replacement = revision.text[start:start + max(length, 0)]
        self.native_edit_requested.emit(revision, start, end, replacement,
                                        start + len(replacement) if position is None else position)

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            self.affinity_position = self.textCursor().position()
            self.caret_affinity = 'right' if event.key() in (Qt.Key_Left, Qt.Key_Home) else 'left'

    def _highlight_rect(self, cursor):
        outline = QRectF()
        if cursor.hasSelection():
            block = cursor.block()
            bounds = self.document().documentLayout().blockBoundingRect(block)
            layout = block.layout()
            start = cursor.selectionStart() - block.position()
            end = cursor.selectionEnd() - block.position()
            tabbed = '\t' in cursor.selectedText()
            for i in range(layout.lineCount()):
                line = layout.lineAt(i)
                a = max(start, line.textStart())
                b = min(end, line.textStart() + line.textLength())
                if a >= b:
                    continue
                rect = line.naturalTextRect()
                # Glyph positions follow the painted text through wraps and
                # direction changes. Tabs have no glyph, so box their line.
                if not tabbed:
                    runs = [run.boundingRect() for run in line.glyphRuns(a, b - a)]
                    if not runs:
                        continue
                    rect.setLeft(max(rect.left(), min(run.left() for run in runs)))
                    rect.setRight(min(rect.right(), max(run.right() for run in runs)))
                if not rect.isEmpty():
                    outline = outline.united(rect.translated(bounds.topLeft()))
        if not outline.isEmpty():
            return outline.adjusted(-1, -1, 1, 1)
        # An empty range marks its accepted position. Document-wide metadata
        # uses the start of the transcript.
        anchor = QTextCursor(cursor)
        anchor.setPosition(cursor.selectionStart())
        caret = QRectF(self.cursorRect(anchor))
        caret.translate(self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        return caret.adjusted(-3, 0, 3, 0)

    def _focus_rect(self):
        outline = QRectF()
        for cursor in self._focused:
            outline = outline.united(self._highlight_rect(cursor))
        return outline

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._focused:
            draw_focus_outlines(QPainter(self.viewport()), self, (self._focus_rect(),))

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or self.textCursor().hasSelection():
            return
        scroll = QPointF(self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        hit = self.document().documentLayout().hitTest(event.position() + scroll, Qt.ExactHit)
        caret = self.textCursor().position()
        self.affinity_position = caret
        self.caret_affinity = 'left' if hit >= 0 and hit < caret else 'right'
        position = utf16_index(self._text, hit if hit >= 0 else caret)
        candidates = [index for start, end, index, _ in self._highlights
                      if hit >= 0 and start <= position < end]

        index = min(candidates, key=lambda i: distance_to_ranges(
            self._edits[i].ranges, 'incoming', position, position), default=-1)
        self.passage_clicked.emit(index, position)

    def undo(self):
        self.history_requested.emit(True)

    def redo(self):
        self.history_requested.emit(False)
