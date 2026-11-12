"""Qt edit transactions and exact revision restoration for native tabs."""
from difflib import SequenceMatcher

from PySide6.QtGui import (QKeySequence, QTextCursor,
                          QColor, QPalette, QContextMenuEvent)
from PySide6.QtCore import Signal, Qt, QSignalBlocker, QMimeData, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit, QDialog, QMessageBox

from app.src.diff_view import LineNumberedEditor


class _NativeTransactions:
    whole_text_set = Signal(str)
    transcript_clicked = Signal()
    history_action = None
    whole_text_update = False

    def setPlainText(self, text):
        self.whole_text_update = True
        try:
            super().setPlainText(self._presentation_text(text))
            self._after_set_plaintext()
        finally:
            self.whole_text_update = False
        self.whole_text_set.emit(self.toPlainText())

    def _after_set_plaintext(self):
        pass

    def _presentation_text(self, text):
        return text

    def undo(self):
        self.history_action = 'undo'
        try:
            super().undo()
            while (self.document().isUndoAvailable()
                   and not self._native_history_matches()):
                super().undo()
        finally:
            self.history_action = None

    def redo(self):
        self.history_action = 'redo'
        try:
            super().redo()
            while (self.document().isRedoAvailable()
                   and not self._native_history_matches()):
                super().redo()
        finally:
            self.history_action = None

    def _native_history_matches(self):
        lookup = getattr(self, 'native_revision_at_step', None)
        revision = lookup(self.document().availableUndoSteps()) if lookup else None
        return revision is None or revision.text == self.toPlainText()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Undo):
            self.undo()
        elif event.matches(QKeySequence.Redo):
            self.redo()
        else:
            super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and not self.textCursor().hasSelection():
            self.transcript_clicked.emit()

    def contextMenuEvent(self, event):
        if not True:
            return super().contextMenuEvent(event)
        if event.reason() == QContextMenuEvent.Mouse:
            clicked = self.cursorForPosition(event.pos())
            selection = self.textCursor()
            if not selection.selectionStart() <= clicked.position() <= selection.selectionEnd():
                self.setTextCursor(clicked)
        menu = QMenu(self)
        editable = not self.isReadOnly()
        if editable and hasattr(self, 'native_element_at_cursor'):
            element = self.native_element_at_cursor()
            if element and element.kind == 'field':
                menu.addAction('Fill In Field...', self.edit_native_field)
                menu.addSeparator()
            elif element and element.kind == 'symbol':
                menu.addAction('Change Format Symbol...', self.change_native_symbol)
                menu.addSeparator()
            insert = menu.addMenu('Insert')
            insert.addAction('Field...', self.insert_native_field)
            insert.addAction('Insert Format Symbols...', self.choose_native_symbol)
            menu.addSeparator()
        for label, callback, enabled in (
            ('Undo', self.undo, editable and self.document().isUndoAvailable()),
            ('Redo', self.redo, editable and self.document().isRedoAvailable()),
            ('Cut', self.cut, editable and self.textCursor().hasSelection()),
            ('Copy', self.copy, self.textCursor().hasSelection()),
            ('Paste', self.paste, editable and self.canPaste()),
            ('Select All', self.selectAll, bool(self.toPlainText()))):
            menu.addAction(label, callback).setEnabled(enabled)
        menu.exec(event.globalPos())


class NativeTranscriptEditor(_NativeTransactions, LineNumberedEditor):
    """Original editor appearance with native association-aware transactions."""

    def copy(self):
        if self.textCursor().hasSelection():
            QApplication.clipboard().setMimeData(self.createMimeDataFromSelection())


    def cut(self):
        if not self.isReadOnly() and self.textCursor().hasSelection():
            self._snap_native_cursor()
            self.copy()
            self.textCursor().removeSelectedText()


    def paste(self):
        if not self.isReadOnly():
            self.insertFromMimeData(QApplication.clipboard().mimeData())


    def keyPressEvent(self, event):
        for sequence, action in ((QKeySequence.Copy, self.copy), (QKeySequence.Cut, self.cut),
                                 (QKeySequence.Paste, self.paste)):
            if event.matches(sequence):
                action()
                return
        if self._native_source:
            revision = self._native_source[1].revision
            cursor = self.textCursor()
            from app.src.casecat.anchors import utf16_index
            position = utf16_index(revision.text, cursor.position())
            if (event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and not self.isReadOnly()
                    and not event.modifiers() & (Qt.AltModifier | Qt.MetaModifier)):
                if not cursor.hasSelection():
                    back = event.key() == Qt.Key_Backspace
                    word = bool(event.modifiers() & Qt.ControlModifier)
                    movement = (QTextCursor.PreviousWord if back else QTextCursor.NextWord) if word else (QTextCursor.PreviousCharacter if back else QTextCursor.NextCharacter)
                    cursor.movePosition(movement, QTextCursor.KeepAnchor)
                start, end = (utf16_index(revision.text, value) for value in (cursor.selectionStart(), cursor.selectionEnd()))
                if any(start < e.end and end > e.start for e in revision.elements):
                    start, end = revision.atomic_range(start, end)
                    self.apply_native_revision(revision._replace(start, end, ''), start)
                    return
            if not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
                if event.key() in (Qt.Key_Left, Qt.Key_Right) and (not cursor.hasSelection() or event.modifiers() & Qt.ShiftModifier):
                    left = event.key() == Qt.Key_Left
                    element = next((e for e in revision.elements
                                    if (e.start < position <= e.end if left else e.start <= position < e.end)), None)
                    if element:
                        target = element.start if left else element.end
                        cursor.setPosition(self._qt_position(target), QTextCursor.KeepAnchor if event.modifiers() & Qt.ShiftModifier else QTextCursor.MoveAnchor)
                        self.setTextCursor(cursor)
                        return
            if event.text() and not self.isReadOnly() and cursor.hasSelection() and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
                start, end = utf16_index(revision.text, cursor.selectionStart()), utf16_index(revision.text, cursor.selectionEnd())
                if any(start < e.end and end > e.start for e in revision.elements):
                    start, end = revision.atomic_range(start, end)
                    text = '\n' if event.key() in (Qt.Key_Return, Qt.Key_Enter) else event.text()
                    if event.key() not in (Qt.Key_Delete, Qt.Key_Backspace):
                        self.apply_native_revision(revision._replace(start, end, text), start+len(text))
                        return
            self._snap_native_cursor()
        super().keyPressEvent(event)
        if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End):
            self._snap_native_cursor()


    def _qt_position(self, position):
        return len(self.toPlainText()[:position].encode('utf-16-le')) // 2


    def _snap_native_cursor(self):
        if not self._native_source:
            return
        from app.src.casecat.anchors import utf16_index
        revision = self._native_source[1].revision
        cursor = self.textCursor()
        if cursor.hasSelection():
            start, end = revision.atomic_range(utf16_index(revision.text, cursor.selectionStart()),
                                               utf16_index(revision.text, cursor.selectionEnd()))
            backwards = cursor.position() < cursor.anchor()
            cursor.setPosition(self._qt_position(end if backwards else start))
            cursor.setPosition(self._qt_position(start if backwards else end), QTextCursor.KeepAnchor)
        else:
            position = utf16_index(revision.text, cursor.position())
            element = next((e for e in revision.elements if e.start < position < e.end), None)
            if element:
                cursor.setPosition(self._qt_position(element.start))
        self.setTextCursor(cursor)


    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._snap_native_cursor()


    def mouseReleaseEvent(self, event):
        self._snap_native_cursor()
        super().mouseReleaseEvent(event)


    def createMimeDataFromSelection(self):
        data = QMimeData()
        data.setText(self.textCursor().selectedText().replace('\u2029', '\n').replace('\u00a0', ' '))
        if self._native_source:
            from app.src.casecat.anchors import utf16_index
            from app.src.casecat.clipboard import MIME_TYPE, selection_data
            revision = self._native_source[1].revision
            start = utf16_index(revision.text, self.textCursor().selectionStart())
            end = utf16_index(revision.text, self.textCursor().selectionEnd())
            if any(start <= e.start and e.end <= end for e in revision.elements):
                data.setData(MIME_TYPE, selection_data(revision, start, end))
        return data


    def insertFromMimeData(self, data):
        from app.src.casecat.clipboard import MIME_TYPE, paste_revision
        if not self._native_source or not data.hasFormat(MIME_TYPE):
            if self._native_source and self.textCursor().hasSelection() and data.hasText() and not self.isReadOnly():
                from app.src.casecat.anchors import utf16_index
                revision = self._native_source[1].revision
                start, end = (utf16_index(revision.text, value) for value in
                              (self.textCursor().selectionStart(), self.textCursor().selectionEnd()))
                if any(start < e.end and end > e.start for e in revision.elements):
                    start, end = revision.atomic_range(start, end)
                    self.apply_native_revision(revision._replace(start, end, data.text()), start+len(data.text()))
                    return
            return super().insertFromMimeData(data)
        from app.src.casecat.anchors import utf16_index
        job = self._native_source[1]
        start = utf16_index(job.text, self.textCursor().selectionStart())
        end = utf16_index(job.text, self.textCursor().selectionEnd())
        try:
            revision = paste_revision(job.revision, job.baseline, start, end, bytes(data.data(MIME_TYPE)))
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            QMessageBox.warning(self, 'Cannot paste native elements', str(exc))
            return
        self.apply_native_revision(revision)


    def apply_native_revision(self, revision, position=None):
        if self.isReadOnly():
            return
        if position is None:
            from app.src.casecat.anchors import utf16_index
            position = min(utf16_index(self.toPlainText(), self.textCursor().position()), len(revision.text))
        self.pending_native_revision = revision
        try:
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.Document)
            cursor.insertText(revision.text)
            cursor.endEditBlock()
            if position is not None:
                cursor.setPosition(len(revision.text[:position].encode('utf-16-le')) // 2)
                self.setTextCursor(cursor)
        finally:
            self.pending_native_revision = None


    def insert_native_field(self):
        if self.isReadOnly() or self._native_source is None:
            return
        from app.src.native_dialogs import FieldListDialog
        if not getattr(self, '_field_dialog', None):
            self._field_dialog = FieldListDialog(self)
        self._field_dialog.refresh()
        self._field_dialog.show()
        self._field_dialog.raise_()
        self._field_dialog.activateWindow()


    def insert_named_field(self, name):
        if self.isReadOnly() or self._native_source is None:
            return False
        from app.src.casecat.fields import field_values
        from app.src.casecat.anchors import utf16_index
        job = self._native_source[1]
        value = field_values(job.revision).get(name)
        if value is None:
            return False
        start = utf16_index(job.text, self.textCursor().selectionStart())
        end = utf16_index(job.text, self.textCursor().selectionEnd())
        try:
            start, end = job.revision.atomic_range(start, end)
            revision = job.revision._replace(start, end, '').insert_field(start, name, value)
        except (ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, 'Cannot insert field', str(exc))
            return False
        self.apply_native_revision(revision, start + len(value or f'[!{name}]'))
        return True


    def choose_native_symbol(self, *, change=False):
        if self.isReadOnly() or self._native_source is None:
            return
        from app.src.native_dialogs import FormatSymbolDialog
        element = self.native_element_at_cursor()
        if change and (element is None or element.kind != 'symbol'):
            return
        current = ('By-line' if element.name == 'By-line' else 'Q' if element.raw == '160200' else 'A') if change else None
        dialog = FormatSymbolDialog(self, current=current)
        if dialog.exec() == QDialog.Accepted:
            if change:
                cursor = self.textCursor()
                cursor.setPosition(self._qt_position(element.start))
                cursor.setPosition(self._qt_position(element.end), QTextCursor.KeepAnchor)
                self.setTextCursor(cursor)
            self.insert_native_symbol(dialog.symbol)
        dialog.deleteLater()
        self.setFocus(Qt.OtherFocusReason)


    def change_native_symbol(self):
        self.choose_native_symbol(change=True)


    def insert_native_symbol(self, label):
        if self.isReadOnly() or self._native_source is None or label not in ('Q', 'A', 'By-line'):
            return
        from dataclasses import replace
        from app.src.casecat.anchors import utf16_index
        from app.src.casecat.elements import NativeElement
        revision = self._native_source[1].revision
        start = utf16_index(revision.text, self.textCursor().selectionStart())
        end = utf16_index(revision.text, self.textCursor().selectionEnd())
        element = self.native_element_at_cursor()
        if element and element.kind == 'symbol' and (start == end or end <= element.end):
            start, end = element.start, element.end
        try:
            start, end = revision.atomic_range(start, end)
        except ValueError as exc:
            QMessageBox.warning(self, 'Cannot insert symbol', str(exc))
            return
        prefix = '\n' if start and revision.text[start-1] != '\n' else ''
        content = 'BY ' if label == 'By-line' else f'     {label}    '
        revision = revision._replace(start, end, prefix + content)
        if label == 'By-line':
            element = NativeElement(start+len(prefix), start+len(prefix)+3, 'symbol',
                                    '160500110602000000425920', 'By-line')
            kept = [e for e in revision.elements if e.end <= element.start or e.start >= element.end]
            revision = replace(revision, elements=tuple(sorted((*kept, element), key=lambda e: (e.start, e.end))))
        self.apply_native_revision(revision, start+len(prefix)+len(content))


    def native_element_at_cursor(self):
        if self._native_source is None:
            return None
        from app.src.casecat.anchors import utf16_index
        revision = self._native_source[1].revision
        cursor = self.textCursor()
        position = utf16_index(self.toPlainText(), cursor.selectionStart() if cursor.hasSelection() else cursor.position())
        return next((e for e in revision.elements if e.start <= position < e.end), None)


    def edit_native_field(self):
        element = self.native_element_at_cursor()
        if self.isReadOnly() or element is None or element.kind != 'field':
            return
        self.fill_native_field(element.name)


    def fill_native_field(self, name):
        if self.isReadOnly() or self._native_source is None:
            return
        from app.src.native_dialogs import FillFieldDialog
        from app.src.casecat.fields import field_values
        revision = self._native_source[1].revision
        current = field_values(revision).get(name)
        if current is None:
            return
        value, accepted = FillFieldDialog.get_value(self, name, current)
        if not accepted or value == current:
            return
        try:
            revision = revision.set_field(name, value)
        except ValueError as exc:
            QMessageBox.warning(self, 'Cannot edit field', str(exc))
            return
        self.apply_native_revision(revision)


    def mouseDoubleClickEvent(self, event):
        cursor = self.cursorForPosition(event.position().toPoint())
        self.setTextCursor(cursor)
        element = self.native_element_at_cursor()
        if element and element.kind == 'field' and not self.isReadOnly():
            self.edit_native_field()
            event.accept()
        elif element and element.kind == 'symbol':
            text = self.toPlainText()
            cursor.setPosition(len(text[:element.start].encode('utf-16-le')) // 2)
            cursor.setPosition(len(text[:element.end].encode('utf-16-le')) // 2, QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


    def __init__(self, font, parent=None):
        self._native_source = None
        super().__init__(font, parent=parent)

    def setReadOnly(self, readonly):
        super().setReadOnly(readonly)
        if readonly and getattr(self, '_field_dialog', None):
            self._field_dialog.close()


    def hideEvent(self, event):
        if getattr(self, '_field_dialog', None):
            self._field_dialog.close()
        super().hideEvent(event)


    def set_native_source(self, bundle, job):
        self._native_source = (bundle, job)
        self._refresh_element_marks()
        if getattr(self, "_field_dialog", None):
            QTimer.singleShot(0, self._field_dialog.refresh_if_idle)

    def setExtraSelections(self, selections):
        self._external_selections = selections
        self._refresh_element_marks()


    def _refresh_element_marks(self):
        selections = []
        if self._native_source and self.toPlainText() == self._native_source[1].text:
            text = self.toPlainText()
            dark = self.palette().color(QPalette.Base).lightness() < 128
            for element in self._native_source[1].revision.elements:
                mark = QTextEdit.ExtraSelection()
                mark.cursor = QTextCursor(self.document())
                mark.cursor.setPosition(len(text[:element.start].encode('utf-16-le')) // 2)
                mark.cursor.setPosition(len(text[:element.end].encode('utf-16-le')) // 2, QTextCursor.KeepAnchor)
                color = ('#eab46a' if dark else '#a15a10') if element.kind == 'field' else ('#91bce9' if dark else '#276394')
                mark.format.setForeground(QColor(color))
                selections.append(mark)
        super().setExtraSelections([*selections, *getattr(self, '_external_selections', [])])


    def _after_set_plaintext(self):
        self.document().clearUndoRedoStacks()
        self._refresh_element_marks()

    def refresh_native_presentation(self):
        self._refresh_element_marks()

    def sync_native_text(self, text):
        """Join linked field updates and atomic symbol edits to one Qt undo."""
        old = self.toPlainText()
        if old == text:
            return
        cursor = QTextCursor(self.document())
        with QSignalBlocker(self), QSignalBlocker(self.document()):
            cursor.joinPreviousEditBlock()
            for tag, a, b, c, d in reversed(SequenceMatcher(None, old, text, autojunk=False).get_opcodes()):
                if tag != 'equal':
                    cursor.setPosition(len(old[:a].encode('utf-16-le')) // 2)
                    cursor.setPosition(len(old[:b].encode('utf-16-le')) // 2, QTextCursor.KeepAnchor)
                    cursor.insertText(text[c:d])
            cursor.endEditBlock()
