"""Render the accepted transcript while its suggestions are pending."""
from itertools import accumulate
import re

from PySide6.QtCore import QObject, QPointF, QRunnable, Qt, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import QTextEdit

from app.src.casecat.anchors import utf16_index
from app.src.casecat.presentation import prepare_editor_presentation
from app.src.native_editor import NativeTranscriptEditor
from app.src.review_colors import ADDITION_BACKGROUND, CHECK_BACKGROUND, CHECK_FOREGROUND
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
        self._edits, self._highlights, self._labels = (), [], []

    def load_preview(self, bundle, job, prepared, model, selected, labels=()):
        self.set_native_source(bundle, job)
        self.setPlainText(job.text, prepared=prepared)
        self._text, self._edits = job.text, model.edits
        self._highlights = []
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
        self.set_label_ranges(labels, offsets)
        self.highlight_edit(selected)

    def set_label_ranges(self, labels, offsets=None):
        """Corrected or unmatched speaker labels, in the accepted text's positions."""
        if offsets is None:
            offsets = list(accumulate((2 if ord(char) > 0xffff else 1 for char in self._text), initial=0))
        self._labels = []
        for start, end in labels:
            if 0 <= start < end <= len(self._text):
                cursor = QTextCursor(self.document())
                cursor.setPosition(offsets[start])
                cursor.setPosition(offsets[end], QTextCursor.KeepAnchor)
                self._labels.append(cursor)

    def highlight_edit(self, selected):
        marks = []
        for _, _, index, cursor in self._highlights:
            mark = QTextEdit.ExtraSelection()
            mark.cursor = cursor
            mark.format.setBackground(QColor(ADDITION_BACKGROUND))
            mark.format.setForeground(QColor('#1e5531'))
            mark.format.setFontUnderline(index == selected)
            marks.append(mark)
        # Speaker labels come last, so they stay yellow inside a green edit.
        for cursor in self._labels:
            mark = QTextEdit.ExtraSelection()
            mark.cursor = cursor
            mark.format.setBackground(QColor(CHECK_BACKGROUND))
            mark.format.setForeground(QColor(CHECK_FOREGROUND))
            marks.append(mark)
        self.set_review_marks(marks, [])

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
