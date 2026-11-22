"""Render the accepted transcript while its suggestions are pending."""
from itertools import accumulate
import re

from PySide6.QtCore import QObject, QPointF, QRunnable, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QTextCursor
from PySide6.QtWidgets import QTextEdit

from app.src.casecat.anchors import utf16_index
from app.src.casecat.presentation import prepare_editor_presentation
from app.src.native_editor import NativeTranscriptEditor
from app.src.review_colors import ADDITION_BACKGROUND, draw_focus_outlines
from app.src.suggestions import preview_ranges, resolve_all


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

    def __init__(self, font):
        super().__init__(font)
        self.setReadOnly(True)
        self._text = ''
        self._edits, self._highlights = (), []
        self._focused = []

    def load_preview(self, bundle, job, prepared, model, selected):
        self.set_native_source(bundle, job)
        self.setPlainText(job.text, prepared=prepared)
        self._text, self._edits = job.text, model.edits
        self._highlights = []
        marks = []
        offsets = list(accumulate((2 if ord(char) > 0xffff else 1 for char in self._text), initial=0))
        for index, edit in enumerate(self._edits):
            for _, _, start, end in preview_ranges(edit):
                # Qt paints a selection of a paragraph separator as an empty
                # colored cell. Highlight the visible parts of the edit.
                for match in re.finditer(r'[^\n]+', self._text[start:end]):
                    first, last = start + match.start(), start + match.end()
                    cursor = QTextCursor(self.document())
                    cursor.setPosition(offsets[first])
                    cursor.setPosition(offsets[last], QTextCursor.KeepAnchor)
                    self._highlights.append((first, last, index, cursor))
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

    def _focus_rects(self):
        for cursor in self._focused:
            block = cursor.block()
            bounds = self.document().documentLayout().blockBoundingRect(block)
            layout = block.layout()
            if not layout.lineCount():
                continue
            start = cursor.selectionStart() - block.position()
            end = cursor.selectionEnd() - block.position()
            first = layout.lineForTextPosition(start).lineNumber()
            last = layout.lineForTextPosition(end - 1).lineNumber()
            tabbed = '\t' in cursor.selectedText()
            for i in range(first, last + 1):
                line = layout.lineAt(i)
                rect = line.naturalTextRect()
                # Glyph positions follow the painted text through wraps and
                # direction changes. Tabs have no glyph, so box their line.
                if not tabbed:
                    a = max(start, line.textStart())
                    b = min(end, line.textStart() + line.textLength())
                    runs = [run.boundingRect() for run in line.glyphRuns(a, b - a)]
                    if not runs:
                        continue
                    rect.setLeft(max(rect.left(), min(run.left() for run in runs)))
                    rect.setRight(min(rect.right(), max(run.right() for run in runs)))
                if not rect.isEmpty():
                    yield rect.translated(bounds.topLeft()).adjusted(-1, -1, 1, 1)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._focused:
            draw_focus_outlines(QPainter(self.viewport()), self, self._focus_rects())

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or self.textCursor().hasSelection():
            return
        scroll = QPointF(self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        hit = self.document().documentLayout().hitTest(event.position() + scroll, Qt.ExactHit)
        caret = self.textCursor().position()
        position = utf16_index(self._text, hit if hit >= 0 else caret)
        candidates = [index for start, end, index, _ in self._highlights
                      if hit >= 0 and start <= position < end]

        def distance(index):
            return min(max(start - position, position - end + 1, 0)
                       for _, _, start, end in self._edits[index].ranges)

        index = min(candidates, key=distance, default=-1)
        self.passage_clicked.emit(index, position)

    def undo(self):
        self.history_requested.emit(True)

    def redo(self):
        self.history_requested.emit(False)
