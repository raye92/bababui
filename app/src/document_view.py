"""One document's editor, Incoming view, and revision controls."""
from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QPlainTextEdit, QPushButton
from app.src.diff_view import DiffView, LineNumberedEditor


class DocumentView(QWidget):
    changed = Signal()

    def __init__(self, document):
        super().__init__()
        self.document = document
        self._updating = False
        self._position_pending = True
        self.stack = QStackedWidget()
        self.original_stack = QStackedWidget()
        font = QFont('Courier New', 12)
        font.setStyleHint(QFont.Monospace)
        self.editor = LineNumberedEditor(font)
        self.incoming_editor = LineNumberedEditor(font)
        self.diff_view = DiffView()
        self.original_stack.addWidget(self.editor)
        self.original_stack.addWidget(self.diff_view)
        self.stack.addWidget(self.original_stack)
        self.stack.addWidget(self.incoming_editor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.editor.textChanged.connect(self._original_changed)
        self.incoming_editor.textChanged.connect(self._incoming_changed)
        self.diff_view.resolved.connect(self._resolved)
        self.diff_view.autosaved.connect(self._diff_edited)
        self.refresh()
        self.stack.setCurrentIndex(document.view)
        self.schedule_restore()

    def active_view(self):
        return self.incoming_editor if self.stack.currentIndex() == 1 else self.original_stack.currentWidget()

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
        if editor.toPlainText() != text:
            editor.setPlainText(text)

    def refresh(self):
        self._updating = True
        doc = self.document
        self._set_text(self.editor, doc.original)
        self._set_text(self.incoming_editor, doc.incoming)
        if doc.original == doc.incoming:
            self.original_stack.setCurrentWidget(self.editor)
        else:
            self.diff_view.set_texts(doc.original, doc.incoming)
            if self.diff_view.has_changes:
                self.original_stack.setCurrentWidget(self.diff_view)
            else:
                # Layout is generated, not a pending editorial decision.
                doc.incoming = doc.original
                self._set_text(self.incoming_editor, doc.incoming)
                self.original_stack.setCurrentWidget(self.editor)
        self._updating = False
        self.set_busy(doc.busy)

    def edited(self):
        self.document.dirty = True
        self.changed.emit()

    def _original_changed(self):
        if self._updating:
            return
        self.document.original = self.editor.toPlainText()
        self.document.incoming = self.document.original
        self.edited()

    def _incoming_changed(self):
        if self._updating:
            return
        self.document.incoming = self.incoming_editor.toPlainText()
        self.edited()

    def _diff_edited(self, original, incoming):
        self.document.original, self.document.incoming = original, incoming
        self._updating = True
        self._set_text(self.incoming_editor, incoming)
        self._updating = False
        self.edited()

    def _resolved(self, original, incoming):
        self._diff_edited(original, incoming)
        if original == incoming:
            self.refresh()

    def toggle_view(self):
        self.capture_position()
        line = self.document.center_line
        if self.stack.currentIndex() == 0:
            self._updating = True
            self._set_text(self.incoming_editor, self.document.incoming)
            self._updating = False
            self.stack.setCurrentIndex(1)
        else:
            self.refresh()
            self.stack.setCurrentIndex(0)
        self.document.view = self.stack.currentIndex()
        self.document.center_line = line
        self.schedule_restore()
        self.changed.emit()

    def receive(self, text, warnings):
        self.capture_position()
        self.document.incoming = text
        self.document.warnings = list(warnings)
        self.document.status = 'Incoming updated. Review the suggested revisions.'
        self.refresh()
        self.edited()
        self.schedule_restore()

    def set_busy(self, busy):
        self.document.busy = busy
        self.editor.setReadOnly(busy)
        self.incoming_editor.setReadOnly(busy)
        for editor in self.diff_view.findChildren(QPlainTextEdit):
            editor.setReadOnly(busy)
        for button in self.diff_view.findChildren(QPushButton):
            button.setEnabled(not busy)

    def active_editor(self):
        if self.document.busy:
            return None
        if self.stack.currentIndex() == 1:
            return self.incoming_editor
        if self.original_stack.currentWidget() is self.editor:
            return self.editor
        return None
