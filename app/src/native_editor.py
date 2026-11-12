"""Qt edit transactions and exact revision restoration for native tabs."""
from dataclasses import dataclass
import math
from difflib import SequenceMatcher

from PySide6.QtGui import (QKeySequence, QTextCursor,
                          QColor, QPalette, QContextMenuEvent, QFont, QFontMetricsF,
                          QTextBlockFormat, QTextOption, QPainter)
from PySide6.QtCore import Signal, Qt, QSignalBlocker, QMimeData, QTimer, QSizeF, QRectF
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit, QDialog, QMessageBox

from app.src.casecat.layout import read_layouts, ParagraphStyle
from transcript_formatting import TranscriptFormatter


def _paper_font(family, pixels):
    font = QFont(family)
    font.setPixelSize(round(pixels))
    if family.casefold() == 'courier new':
        # Measured against CaseCAT's Courier output. Fractional advances avoid
        # Windows hinting rounding every 18px glyph up to an 11px cell. The
        # small tracking preserves CAT's 56-column wrapping at native margins.
        font.setHintingPreference(QFont.PreferNoHinting)
        font.setLetterSpacing(QFont.AbsoluteSpacing, pixels / 256)
    return font


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


@dataclass(frozen=True)
class PageLine:
    page: int
    number: int
    position: int
    text: str
    y: float


class NativeTranscriptEditor(_NativeTransactions, QTextEdit):
    columns = TranscriptFormatter.LINE_WIDTH
    lines_per_page = TranscriptFormatter.LINES_PER_PAGE
    """CaseCAT page presentation over structured edit transactions."""

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
                    text = data.text().replace('\r\n', '\n').replace('\r', '\n')
                    self.apply_native_revision(revision._replace(start, end, text), start+len(text))
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
        super().__init__(parent)
        self._native_source = None
        self._native_layout = None
        self._paragraph_styles = {}
        self.setAcceptRichText(False)
        paper_font = QFont(font)
        paper_font.setPixelSize(18)
        self.setFont(paper_font)
        self.document().setDefaultFont(paper_font)
        metrics = QFontMetricsF(paper_font)
        self._line_height = math.ceil(metrics.height()) * 2
        self._left = 78
        self._right = 48
        self._top = 48
        self._bottom = 48
        self._page_width = metrics.horizontalAdvance('0') * self.columns + self._left + self._right
        self._page_height = self._top + self.lines_per_page * self._line_height + self._bottom
        self.setLineWrapMode(QTextEdit.FixedPixelWidth)
        self.setLineWrapColumnOrWidth(math.ceil(self._page_width))
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        # Qt's text-only range must not hide/show the bar while the page range
        # includes blank footer space, which otherwise causes resize oscillation.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        # Use the same application palette as the original text editor.
        self.setStyleSheet('QTextEdit { border: 0; }')
        self.document().documentLayout().documentSizeChanged.connect(self._update_page_scroll_range)
        self._after_set_plaintext()

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
        if getattr(self, '_field_dialog', None):
            QTimer.singleShot(0, self._field_dialog.refresh_if_idle)
        layouts = read_layouts(job.native_bytes)
        if not layouts or not layouts[0].paragraphs:
            return
        self._native_layout = layout = layouts[0]
        style = layout.paragraphs[0]
        # Keep a comfortable screen size while using the source's proportions.
        self._twip_scale = 18 / style.font_twips
        font = _paper_font(style.font_family, 18)
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.lines_per_page = layout.lines_per_page
        self._left = style.left * self._twip_scale
        self._right = (layout.width - style.right) * self._twip_scale
        self._top = layout.top * self._twip_scale
        self._bottom = (layout.height - layout.bottom) * self._twip_scale
        self._page_width = layout.width * self._twip_scale
        self._page_height = layout.height * self._twip_scale
        self._line_height = (layout.bottom - layout.top) * self._twip_scale / layout.lines_per_page
        self.columns = round((style.right - style.left) * self._twip_scale / QFontMetricsF(font).horizontalAdvance('0'))
        self.setLineWrapColumnOrWidth(math.ceil(self._page_width))
        # QTextEdit's wrap-width setter changes the document height to -1.
        # Restore pagination on every native refresh, including equal text.
        self.document().setPageSize(QSizeF(self._page_width, self._page_height))

    def set_review_marks(self, selections, insertions):
        self._review_selections = selections
        self._review_insertions = insertions
        self._refresh_element_marks()
        self.viewport().update()

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
        super().setExtraSelections([*selections, *getattr(self, '_external_selections', []), *getattr(self, '_review_selections', [])])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, '_page_width'):
            return
        margins = self.viewportMargins()
        available = self.viewport().width() + margins.left() + margins.right()
        inset = max(0, (available - math.ceil(self._page_width)) // 2)
        if margins.left() != inset or margins.right() != inset:
            self.setViewportMargins(inset, 0, inset, 0)
        # QTextEdit resets page height to -1 when its viewport changes. Restore
        # the same geometry used by the decorations and cursor hit testing.
        # This is layout only: it must not create text edits or undo entries.
        size = QSizeF(self._page_width, self._page_height)
        if self.document().pageSize() != size:
            self.document().setPageSize(size)
        self._update_page_scroll_range()

    def _update_page_scroll_range(self, *_):
        # QTextEdit stops at the last text block. A short final page still needs
        # its remaining numbered rows and footer to be reachable.
        height = self.document().pageCount() * self._page_height
        self.verticalScrollBar().setMaximum(max(0, math.ceil(height - self.viewport().height())))

    def _presentation_text(self, text):
        self._paragraph_styles = {}
        if self._native_source:
            bundle, job = self._native_source
            if job.text == text:
                from app.src.casecat.presentation import presentation
                try:
                    display, styles = presentation(job, bundle)
                except ValueError:
                    return text
                if display.replace('\u00a0', ' ') == text:
                    self._paragraph_styles = styles
                    return display
        return text

    def _after_set_plaintext(self):
        frame = self.document().rootFrame()
        fmt = frame.frameFormat()
        fmt.setLeftMargin(self._left)
        fmt.setRightMargin(self._right)
        fmt.setTopMargin(self._top)
        fmt.setBottomMargin(self._bottom)
        frame.setFrameFormat(fmt)
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.Document)
        block = QTextBlockFormat()
        block.setLineHeight(self._line_height, QTextBlockFormat.FixedHeight.value)
        cursor.setBlockFormat(block)
        self._apply_paragraph_styles()
        self.document().setPageSize(QSizeF(self._page_width, self._page_height))
        self._align_page_top()
        self.document().clearUndoRedoStacks()
        self._update_page_scroll_range()
        self._refresh_element_marks()

    def refresh_native_presentation(self):
        """Join derived styling to the text edit without replacing the document."""
        plain = self.toPlainText()
        display = self._presentation_text(plain)
        cursor = QTextCursor(self.document())
        with QSignalBlocker(self), QSignalBlocker(self.document()):
            cursor.joinPreviousEditBlock()
            # Normal and hard spaces share the same logical Qt text offset.
            raw = self.document().toRawText().replace('\u2029', '\n')
            offset = 0
            for original, wanted in zip(raw, display):
                width = len(original.encode('utf-16-le')) // 2
                if original != wanted and {original, wanted} == {' ', '\u00a0'}:
                    cursor.setPosition(offset)
                    cursor.setPosition(offset + width, QTextCursor.KeepAnchor)
                    cursor.insertText(wanted)
                offset += width
            self._apply_paragraph_styles()
            self._align_page_top()
            cursor.endEditBlock()

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

    def _apply_paragraph_styles(self):
        cursor = QTextCursor(self.document())
        plain = self.toPlainText()
        positions, offset, qt_offset = [], 0, 0
        for text in plain.split('\n'):
            positions.append((offset, qt_offset))
            offset += len(text) + 1
            qt_offset += len(text.encode('utf-16-le')) // 2 + 1
        for position, qt_position in positions:
            style = self._paragraph_styles.get(position)
            cursor.setPosition(qt_position)
            paragraph = cursor.blockFormat()
            if isinstance(style, ParagraphStyle) and self._native_layout:
                scale = self._twip_scale
                paragraph.setLeftMargin(style.left * scale - self._left)
                paragraph.setRightMargin((self._native_layout.width - style.right) * scale - self._right)
                text = cursor.block().text()
                prefix = 10 if text.startswith(('     Q    ', '     A    ')) else 5 if text.startswith('     ') else 0
                paragraph.setTextIndent((style.first - style.left) * scale -
                                        QFontMetricsF(self.font()).horizontalAdvance(' ' * prefix))
                paragraph.setAlignment(Qt.AlignHCenter if style.alignment == 2 else Qt.AlignLeft)
                char_format = cursor.blockCharFormat()
                font = _paper_font(style.font_family, style.font_twips * scale)
                font.setBold(style.font_weight >= 700)
                font.setItalic(style.italic)
                font.setUnderline(style.underline)
                paragraph.setLineHeight(self._line_height * (0.5 if style.spacing == 1 else 1),
                                        QTextBlockFormat.FixedHeight.value)
                if paragraph != cursor.blockFormat():
                    cursor.setBlockFormat(paragraph)
                char_format.setFont(font)
                if cursor.charFormat().font() != font:
                    cursor.select(QTextCursor.BlockUnderCursor)
                    cursor.mergeCharFormat(char_format)
            else:
                # Imported paragraph styles take precedence. With no native
                # style, use the documented transcript heading convention.
                centered = style == 7 or bool(TranscriptFormatter.examination_heading.fullmatch(cursor.block().text().strip()))
                paragraph.setAlignment(Qt.AlignHCenter if centered else Qt.AlignLeft)
                if paragraph != cursor.blockFormat():
                    cursor.setBlockFormat(paragraph)

    def _align_page_top(self):
        # Qt places extra fixed-height leading above the glyphs. CaseCAT puts
        # the glyph row at the top margin. Transfer that leading to the bottom
        # margin, keeping the text area height and exact line pitch unchanged.
        # LineDistanceHeight cannot do this: Qt includes font leading between
        # wrapped lines but excludes it at paragraph boundaries.
        self.document().documentLayout().documentSize()
        layout = self.document().firstBlock().layout()
        leading = layout.lineAt(0).y() if layout.lineCount() else 0
        frame = self.document().rootFrame()
        fmt = frame.frameFormat()
        fmt.setTopMargin(self._top - leading)
        fmt.setBottomMargin(self._bottom + leading)
        if fmt != frame.frameFormat():
            frame.setFrameFormat(fmt)

    def page_lines(self):
        # Force layout before reading QTextLine coordinates, including offscreen
        # pages. QTextCursor and native edit transactions keep logical offsets.
        self.document().documentLayout().documentSize()
        result = []
        page_numbers = {}
        block = self.document().begin()
        while block.isValid():
            layout = block.layout()
            if block.isVisible():
                raw = block.text().encode('utf-16-le')
                for index in range(layout.lineCount()):
                    line = layout.lineAt(index)
                    y = layout.position().y() + line.y()
                    page = int(y // self._page_height)
                    # Number physical lines, not rounded glyph coordinates:
                    # font ascent and paragraph spacing vary independently.
                    number = page_numbers.get(page, 0) + 1
                    page_numbers[page] = number
                    text = raw[line.textStart()*2:(line.textStart()+line.textLength())*2].decode('utf-16-le')
                    result.append(PageLine(page + 1, number, block.position() + line.textStart(), text.rstrip(), y))
            block = block.next()
        return result

    def page_number_rect(self, page):
        """Zero-based page's footer, outside the transcript's text area."""
        height = QFontMetricsF(self.page_number_font()).height()
        if self._native_layout and self._native_layout.page_number_top is not None:
            top = page * self._page_height + self._native_layout.page_number_top * self._twip_scale
            return QRectF(self._page_width - self._right - 80, top, 80, height)
        top = (page + 1) * self._page_height - self._bottom
        return QRectF(self._page_width - self._right - 80,
                      top + max(0, (self._bottom - height) / 2 - 6), 80, height)

    def page_number_font(self):
        if self._native_layout and self._native_layout.page_number_top is not None:
            return _paper_font(self.font().family(), self._native_layout.page_number_font_twips * self._twip_scale)
        return self.font()

    def line_number_rect(self, y):
        right = (self._native_layout.line_number_right * self._twip_scale
                 if self._native_layout and self._native_layout.line_number_right
                 else self._left - 14)
        return QRectF(16, y, max(0, right - 16), self.fontMetrics().height())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        scroll_y = self.verticalScrollBar().value()
        scroll_x = self.horizontalScrollBar().value()
        painter.translate(-scroll_x, -scroll_y)
        painter.setFont(self.font())
        painter.setPen(QColor('#8a8f98'))
        lines = self.page_lines()
        for line in lines:
            if scroll_y - self._line_height <= line.y <= scroll_y + self.viewport().height():
                painter.drawText(self.line_number_rect(line.y),
                                 Qt.AlignRight | Qt.AlignVCenter, str(line.number))
        for position, index in getattr(self, '_review_insertions', []):
            cursor = QTextCursor(self.document())
            cursor.setPosition(position)
            rect = self.cursorRect(cursor)
            x, y = rect.x() + scroll_x, rect.y() + scroll_y
            selected = index == getattr(self, '_selected_review', -1)
            color = QColor('#7ee2a8' if selected else '#2da44e')
            painter.fillRect(QRectF(x - 2, y, 4, rect.height()), color)
            badge = QRectF(x - 10, y - 18, 20, 18)
            painter.fillRect(badge, color)
            painter.setPen(QColor('#052e16'))
            painter.drawText(badge, Qt.AlignCenter, '+')
        first = max(0, int(scroll_y // self._page_height))
        last = min(self.document().pageCount(), int((scroll_y + self.viewport().height()) // self._page_height) + 1)
        for page in range(first, last):
            y = page * self._page_height
            painter.setPen(self.palette().color(QPalette.Mid))
            painter.drawRect(QRectF(1, y + 1, self._page_width - 2, self._page_height - 2))
            painter.setPen(QColor('#8a8f98'))
            page_lines = [line for line in lines if line.page == page + 1]
            # CaseCAT numbers the unused rows on the final page too.
            for number in range(len(page_lines) + 1, self.lines_per_page + 1):
                row_y = (page_lines[-1].y + (number - len(page_lines)) * self._line_height
                         if page_lines else y + self._top + (number - 1) * self._line_height)
                painter.drawText(self.line_number_rect(row_y), Qt.AlignRight | Qt.AlignVCenter, str(number))
            painter.setFont(self.page_number_font())
            painter.drawText(self.page_number_rect(page), Qt.AlignRight | Qt.AlignVCenter, str(page + 1))
            painter.setFont(self.font())
            painter.fillRect(QRectF(0, y + self._page_height - 12, self.viewport().width(), 12), self.palette().color(QPalette.Window))
        if self.viewport().width() > self._page_width:
            painter.fillRect(QRectF(self._page_width, scroll_y, self.viewport().width() - self._page_width,
                                    self.viewport().height()), self.palette().color(QPalette.Window))

    def center_line(self):
        lines = self.page_lines()
        middle = self.verticalScrollBar().value() + self.viewport().height() / 2
        return min(range(len(lines)), key=lambda i: abs(lines[i].y - middle)) if lines else 0

    def scroll_to_center_line(self, line):
        lines = self.page_lines()
        if lines:
            target = lines[min(max(0, int(line)), len(lines) - 1)]
            self.verticalScrollBar().setValue(max(0, int(target.y - self.viewport().height() / 2)))
