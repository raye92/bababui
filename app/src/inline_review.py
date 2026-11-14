"""A read-only comparison over native transcript pages."""
from dataclasses import dataclass, replace
import math

from PySide6.QtCore import Qt, Signal, QSizeF, QRectF, QSignalBlocker
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPalette,
                          QTextBlockFormat, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit

from app.src.casecat.anchors import utf16_index
from app.src.native_editor import NativeTranscriptEditor, PageLine


def _qt(text):
    return len(text.encode('utf-16-le')) // 2


@dataclass
class ReviewRow:
    kind: str
    source_start: int
    source_end: int
    text: str
    page: int
    number: int
    source_page: int
    source_number: int
    y: float
    x: float
    pitch: float
    leading: float
    font: QFont
    section: int = -1
    edit_indices: tuple = ()
    incoming_start: int | None = None
    display_start: int = 0
    display_end: int = 0
    glyph_height: float = 0


@dataclass(frozen=True)
class ReviewPage:
    number: int
    top: float
    height: float


@dataclass(frozen=True)
class BoundaryMark:
    side: str
    position: int
    edit_index: int
    display_position: int
    empty: bool


def _common_ranges(model):
    """Map common source text using the existing decisions, never a new diff."""
    left, right = model.original.text, model.incoming.text
    result, a, c = [], 0, 0
    ranges = sorted({span for edit in model.edits for span in edit.ranges})
    for x, y, z, w in ranges + [(len(left), len(left), len(right), len(right))]:
        if a <= x and c <= z and left[a:x] == right[c:z]:
            result.append((a, x, c, z))
        a, c = y, w
    return result


def _row_groups(model, old_rows, new_rows, common):
    """Use matched native rows as display anchors around local changed groups.

    Correspondence comes from source offsets, so repeated wording cannot align
    with the wrong occurrence. A changed wrap can span several rows until the
    source layouts meet again. This grouping never creates review decisions.
    """
    def extent(row, text):
        end = row.source_end
        return end+1 if end < len(text) and text[end] == '\n' else end

    anchors = []
    for index, row in enumerate(old_rows):
        end = extent(row, model.original.text)
        for a, b, c, d in common:
            if a <= row.source_start <= end <= b:
                anchors.append((index, c+row.source_start-a, c+end-a))
                break

    def incoming_rows(start, end, reference):
        result = []
        for row in new_rows:
            a, b = max(start, row.source_start), min(end, row.source_end)
            if a >= b and not (row.source_start == row.source_end and start <= a < end):
                continue
            result.append(replace(row, source_start=a, source_end=b,
                                  text=row.text[a-row.source_start:b-row.source_start],
                                  x=reference.x if not result and reference else row.x))
        return result

    old_index = incoming_position = 0
    for x, y, end in anchors + [(len(old_rows), len(model.incoming.text), len(model.incoming.text))]:
        if x > old_index or y > incoming_position:
            a = old_rows[old_index].source_start if old_index < len(old_rows) else len(model.original.text)
            b = old_rows[x].source_start if x < len(old_rows) else len(model.original.text)
            c, d = incoming_position, y
            indices = tuple(index for index, edit in enumerate(model.edits) if any(
                (a < q and b > p) or (c < s and d > r)
                or (p == q and a <= p <= b) or (r == s and c <= r <= d)
                for p, q, r, s in edit.ranges))
            old_group = old_rows[old_index:x]
            yield old_group, incoming_rows(c, d, old_group[0] if old_group else None), indices, False
        if x < len(old_rows):
            # The Original page supplies shared row breaks. A shorter proposal
            # must not duplicate every following line merely because its own
            # preview can fit another word on the preceding line.
            row = old_rows[x]
            matched = replace(row, kind='incoming', source_start=y,
                              source_end=y+row.source_end-row.source_start)
            yield [row], [matched], (), True
        old_index, incoming_position = x+1, end


def _compact(row):
    pitch = min(row.pitch, math.ceil(max(row.glyph_height, QFontMetricsF(row.font).height())))
    return replace(row, pitch=pitch, leading=max(0, row.leading-row.pitch+pitch))


def _native_rows(editor, side):
    """Read actual Qt wrapping without stripping spaces or adding source text."""
    editor.document().documentLayout().documentSize()
    plain = editor.toPlainText()
    positions, offset = {0: 0}, 0
    for index, char in enumerate(plain):
        offset += _qt(char)
        positions[offset] = index + 1
    rows, counts = [], {}
    block = editor.document().begin()
    while block.isValid():
        layout = block.layout()
        raw = block.text().encode('utf-16-le')
        if block.isVisible():
            for index in range(layout.lineCount()):
                line = layout.lineAt(index)
                start = block.position() + line.textStart()
                end = min(offset, start + line.textLength())
                y = layout.position().y() + line.y()
                page = int(y // editor._page_height) + 1
                number = counts.get(page, 0) + 1
                counts[page] = number
                pitch = block.blockFormat().lineHeight()
                if block.blockFormat().lineHeightType() != QTextBlockFormat.FixedHeight.value:
                    pitch = editor._line_height
                cursor = QTextCursor(block)
                cursor.setPosition(start)
                font = cursor.charFormat().font().resolve(editor.document().defaultFont())
                if not font.family():
                    font = editor.font()
                text = raw[line.textStart()*2:(line.textStart()+line.textLength())*2].decode('utf-16-le')
                rows.append(ReviewRow(side, positions[start], positions[end], text,
                                      page, number, page, number, y,
                                      layout.position().x() + line.x(), pitch,
                                      line.y() - index*pitch, font, glyph_height=line.height()))
        block = block.next()
    return rows


class InlineReviewEditor(QTextEdit):
    selected = Signal(int)
    source_activated = Signal(str, int)
    history_requested = Signal(bool)

    def __init__(self, font=None, parent=None):
        super().__init__(parent)
        self.model = None
        self.rows, self.pages, self.shared_ranges = [], [], []
        self.boundary_marks = []
        self.source_editors = None
        self._external_sources = False
        self._current_edit = -1
        self._source_highlight = None
        self._page_width, self._page_height = 800., 1200.
        self._font = QFont(font or QFont('Courier New', 12))
        self.setFont(self._font)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet('QTextEdit { border: 0; }')
        self.setReadOnly(True)

    def set_source_editors(self, original, incoming):
        self.source_editors = original, incoming
        self._external_sources = True

    def _sources(self, model):
        if self.source_editors is None:
            self.source_editors = tuple(NativeTranscriptEditor(self._font, self) for _ in range(2))
            for editor in self.source_editors:
                editor.hide()
        if not self._external_sources:
            for editor, revision in zip(self.source_editors, (model.original, model.incoming)):
                editor.setPlainText(revision.text)
        return self.source_editors

    def set_model(self, model):
        anchor = self.source_position() if self.rows else ('original', 0)
        self.model = model
        original, incoming = self._sources(model)
        self._page_width, self._page_height = original._page_width, original._page_height
        self._left, self._right = original._left, original._right
        self._top, self._bottom = original._top, original._bottom
        self._line_height = original._line_height
        self.setFont(original.font())
        self.document().setDefaultFont(original.font())
        self.rows, self.shared_ranges = [], []
        old_rows, new_rows = _native_rows(original, 'original'), _native_rows(incoming, 'incoming')
        self.shared_ranges = _common_ranges(model)

        extra = [0.] * max(1, original.document().pageCount())
        old_index, added_height = 0, 0.

        def append_original(row, section_index=-1, edits=(), matched=None):
            row.kind = 'original' if section_index >= 0 else 'equal'
            row.section, row.edit_indices = section_index, edits
            row.y += added_height
            if row.kind == 'equal':
                row.incoming_start = matched.source_start
            self.rows.append(row)

        for section_index, (old_group, new_group, edits, shared) in enumerate(
                _row_groups(model, old_rows, new_rows, self.shared_ranges)):
            if shared:
                append_original(old_group[0], matched=new_group[0])
                old_index += 1
                continue
            reference = (old_group[-1] if old_group else
                         old_rows[min(old_index, len(old_rows)-1)]) if old_rows else None
            page = reference.page if reference else 1
            if old_group:
                # Use the source's blank line spacing for the paired incoming
                # row before adding any height to the comparison page.
                baseline_end = reference.y+reference.pitch+added_height
                for index, row in enumerate(old_group):
                    if index == len(old_group)-1:
                        row = _compact(row)
                    append_original(row, section_index, edits)
                    old_index += 1
                y = self.rows[-1].y+self.rows[-1].pitch
            else:
                a = reference.source_start if reference else len(model.original.text)
                y = reference.y+added_height if reference else self._top+added_height
                baseline_end = y
                row = _compact(ReviewRow('original', a, a, '', page, 0, page, 0,
                                        y, self._left, self._line_height,
                                        reference.leading if reference else 0, original.font(),
                                        section_index, edits,
                                        glyph_height=reference.glyph_height if reference else 0))
                self.rows.append(row)
                y += row.pitch
            for source_row in new_group:
                row = _compact(source_row)
                # Source page breaks do not divide a semantic comparison section.
                projected = ReviewRow('incoming', row.source_start, row.source_end, row.text,
                                      page, 0, row.page, row.number, y, row.x, row.pitch,
                                      row.leading, row.font, section_index, edits,
                                      glyph_height=row.glyph_height)
                self.rows.append(projected)
                y += row.pitch
            if not new_group:
                c = next((span[2]+reference.source_end-span[0] for span in self.shared_ranges
                          if span[0] <= reference.source_end <= span[1]), len(model.incoming.text))
                row = _compact(ReviewRow('incoming', c, c, '', page, 0, page, 0,
                                        y, self._left, self._line_height,
                                        reference.leading if reference else 0, incoming.font(),
                                        section_index, edits,
                                        glyph_height=reference.glyph_height if reference else 0))
                self.rows.append(row)
                y += row.pitch
            amount = max(0, y-baseline_end)
            added_height += amount
            extra[page-1] += amount
        self.pages = []
        top = 0.
        for page, amount in enumerate(extra, 1):
            height = self._page_height + amount
            self.pages.append(ReviewPage(page, top, height))
            top += height
        self._render_document()
        self.boundary_marks = []
        for index, edit in enumerate(model.edits):
            for a, b, c, d in edit.ranges:
                for side, start, end in (('original', a, b), ('incoming', c, d)):
                    content = getattr(model, side).text[start:end]
                    if start != end and (content.strip() or '\n' not in content):
                        continue
                    position = self.display_position(side, start)
                    if position is not None:
                        self.boundary_marks.append(BoundaryMark(side, start, index, position, start == end))
        side, position = anchor
        self.set_source_position(side, min(position, len(getattr(model, side).text)))
        self._refresh_selections()
        self.viewport().update()

    def _render_document(self):
        document = self.document()
        with QSignalBlocker(self), QSignalBlocker(document):
            super().setPlainText('\n'.join(row.text for row in self.rows))
            document.setUndoRedoEnabled(False)
            cursor = QTextCursor(document)
            cursor.beginEditBlock()
            frame = document.rootFrame()
            fmt = frame.frameFormat()
            fmt.setLeftMargin(0)
            fmt.setRightMargin(0)
            fmt.setTopMargin(0)
            fmt.setBottomMargin(0)
            frame.setFrameFormat(fmt)
            position = 0
            for row in self.rows:
                row.display_start, row.display_end = position, position + _qt(row.text)
                cursor.setPosition(position)
                block = QTextBlockFormat()
                block.setLeftMargin(row.x)
                # Every display block contains one physical row. Put spacing
                # in margins so switching between native and compact pitch
                # cannot move the glyph relative to its painted line number.
                block.setLineHeight(_compact(row).pitch, QTextBlockFormat.FixedHeight.value)
                if row.kind != 'equal':
                    block.setBackground(QColor('#fbe9e7' if row.kind == 'original' else '#e7f5ea'))
                cursor.setBlockFormat(block)
                char = QTextCharFormat()
                char.setFont(row.font)
                if row.kind != 'equal':
                    char.setForeground(QColor('#6e2530' if row.kind == 'original' else '#1e5531'))
                cursor.select(QTextCursor.BlockUnderCursor)
                cursor.setCharFormat(char)
                if row.kind != 'equal':
                    for index in row.edit_indices:
                        for a, b, c, d in self.model.edits[index].ranges:
                            start, end = (a, b) if row.kind == 'original' else (c, d)
                            start, end = max(start, row.source_start), min(end, row.source_end)
                            if start >= end:
                                continue
                            cursor.setPosition(row.display_start+_qt(row.text[:start-row.source_start]))
                            cursor.setPosition(row.display_start+_qt(row.text[:end-row.source_start]), QTextCursor.KeepAnchor)
                            mark = QTextCharFormat()
                            mark.setBackground(QColor('#f2aba7' if row.kind == 'original' else '#9edcb0'))
                            cursor.mergeCharFormat(mark)
                position = row.display_end + 1
            cursor.endEditBlock()
            document.setPageSize(QSizeF(self._page_width, -1))
            document.documentLayout().documentSize()
            measured = []
            for row in self.rows:
                block = document.findBlock(row.display_start)
                layout = block.layout()
                measured.append((row, layout.lineAt(0).y(), block.blockFormat().lineHeight()))
            # Batch margin updates so Qt lays out the full review only once.
            cursor.beginEditBlock()
            previous_origin = previous_height = 0
            for index, (row, leading, height) in enumerate(measured):
                origin = row.y-leading
                cursor.setPosition(row.display_start)
                block = cursor.blockFormat()
                if index == 0:
                    fmt = frame.frameFormat()
                    fmt.setTopMargin(max(0, origin))
                    frame.setFrameFormat(fmt)
                else:
                    block.setTopMargin(max(0, origin-previous_origin-previous_height))
                cursor.setBlockFormat(block)
                previous_origin, previous_height = origin, height
            fmt = frame.frameFormat()
            bottom = (self.pages[-1].top+self.pages[-1].height-previous_origin-previous_height
                      if self.pages else self._bottom)
            fmt.setBottomMargin(max(0, bottom))
            frame.setFrameFormat(fmt)
            cursor.endEditBlock()
        self._update_scroll_range()

    def _row_at(self, position):
        block = self.document().findBlock(position)
        index = block.blockNumber()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def _source_at(self, position):
        row = self._row_at(position)
        if row is None:
            return 'original', 0
        local = min(max(0, position-row.display_start), _qt(row.text))
        return ('incoming' if row.kind == 'incoming' else 'original',
                row.source_start+utf16_index(row.text, local))

    def source_position(self):
        return self._source_at(self.textCursor().position())

    def display_position(self, side, position):
        candidates = []
        for row in self.rows:
            if side == 'incoming' and row.kind == 'equal' and row.incoming_start is not None:
                start = row.incoming_start
            elif (side == 'incoming') == (row.kind == 'incoming'):
                start = row.source_start
            else:
                continue
            end = start+len(row.text)
            if start <= position <= end:
                candidates.append((position == end and start != end,
                                   row.display_start+_qt(row.text[:position-start])))
        if candidates:
            return min(candidates)[1]
        return None

    def set_source_position(self, side, position, keep_anchor=False):
        display = self.display_position(side, position)
        if display is None:
            return False
        cursor = self.textCursor()
        cursor.setPosition(display, QTextCursor.KeepAnchor if keep_anchor else QTextCursor.MoveAnchor)
        self.setTextCursor(cursor)
        return True

    def keyPressEvent(self, event):
        for sequence, action in ((QKeySequence.Copy, self.copy),
                                 (QKeySequence.Undo, self.undo),
                                 (QKeySequence.Redo, self.redo)):
            if event.matches(sequence):
                action()
                event.accept()
                return
        super().keyPressEvent(event)

    def copy(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        first, last = self._row_at(start), self._row_at(end)
        side, a = self._source_at(start)
        other, b = self._source_at(end)
        rows = [row for row in self.rows if row.display_start <= end and row.display_end >= start]
        if first and last and side == other and all((row.kind == 'incoming') == (side == 'incoming') for row in rows):
            value = getattr(self.model, side).text[a:b]
        else:
            value = cursor.selectedText().replace('\u2029', '\n').replace('\u2011', '-').replace('\u00a0', ' ')
        QApplication.clipboard().setText(value)

    def undo(self):
        self.history_requested.emit(True)

    def redo(self):
        self.history_requested.emit(False)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('Undo review', self.undo)
        menu.addAction('Redo review', self.redo)
        menu.addAction('Copy', self.copy).setEnabled(self.textCursor().hasSelection())
        menu.addAction('Select All', self.selectAll).setEnabled(bool(self.rows))
        menu.exec(event.globalPos())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            for marker in self.boundary_marks:
                if self.boundary_rect(marker).contains(event.position()):
                    self._current_edit = marker.edit_index
                    self._refresh_selections()
                    self.selected.emit(marker.edit_index)
                    self.source_activated.emit(marker.side, marker.position)
                    event.accept()
                    return
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or self.textCursor().hasSelection():
            return
        side, position = self.source_position()
        row = self._row_at(self.textCursor().position())
        if row and row.edit_indices:
            candidates = []
            for index in row.edit_indices:
                for a, b, c, d in self.model.edits[index].ranges:
                    start, end = (a, b) if side == 'original' else (c, d)
                    distance = max(start-position, position-end, 0)
                    candidates.append((distance, index))
            if candidates:
                self._current_edit = min(candidates)[1]
                self._refresh_selections()
                self.selected.emit(self._current_edit)
        self.source_activated.emit(side, position)

    def focus_edit(self, index):
        if self.model is None or not 0 <= index < len(self.model.edits):
            return
        self._current_edit = index
        change = self.model.edits[index]
        if change.ranges:
            a, b, c, d = change.ranges[0]
            side, position = ('original', a) if a != b else ('incoming', c)
            if self.set_source_position(side, position):
                self.ensureCursorVisible()
                rect = self.cursorRect()
                self.verticalScrollBar().setValue(max(0, self.verticalScrollBar().value()+rect.y()-self.viewport().height()//2))
        self._refresh_selections()

    def set_source_highlight(self, side, start, end):
        self._source_highlight = side, start, end
        self._refresh_selections()

    def clear_source_highlight(self):
        self._source_highlight = None
        self._refresh_selections()

    def _refresh_selections(self):
        marks = []
        intervals = []
        if self.model is not None and 0 <= self._current_edit < len(self.model.edits):
            for a, b, c, d in self.model.edits[self._current_edit].ranges:
                intervals.extend([('original', a, b, False), ('incoming', c, d, False)])
        if self._source_highlight:
            intervals.append((*self._source_highlight, True))
        for side, start, end, audio in intervals:
            for row in self.rows:
                if side == 'incoming' and row.kind == 'equal' and row.incoming_start is not None:
                    source_start = row.incoming_start
                elif (side == 'incoming') == (row.kind == 'incoming'):
                    source_start = row.source_start
                else:
                    continue
                left, right = max(start, source_start), min(end, source_start+len(row.text))
                if left >= right:
                    continue
                mark = QTextEdit.ExtraSelection()
                mark.cursor = QTextCursor(self.document())
                mark.cursor.setPosition(row.display_start+_qt(row.text[:left-source_start]))
                mark.cursor.setPosition(row.display_start+_qt(row.text[:right-source_start]), QTextCursor.KeepAnchor)
                if audio:
                    mark.format.setBackground(QColor(120, 165, 220, 85))
                else:
                    mark.format.setFontUnderline(True)
                marks.append(mark)
        super().setExtraSelections(marks)

    def _update_scroll_range(self):
        if self.pages:
            height = self.pages[-1].top+self.pages[-1].height
            self.verticalScrollBar().setMaximum(max(0, math.ceil(height-self.viewport().height())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scroll_range()

    def page_lines(self):
        return [PageLine(row.page, row.number, row.display_start, row.text.rstrip(), row.y)
                for row in self.rows if row.number]

    def center_line(self):
        lines = self.page_lines()
        middle = self.verticalScrollBar().value()+self.viewport().height()/2
        return min(range(len(lines)), key=lambda i: abs(lines[i].y-middle)) if lines else 0

    def scroll_to_center_line(self, line):
        lines = self.page_lines()
        if lines:
            row = lines[min(max(0, int(line)), len(lines)-1)]
            self.verticalScrollBar().setValue(max(0, int(row.y-self.viewport().height()/2)))

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.source_editors:
            return
        source = self.source_editors[0]
        painter = QPainter(self.viewport())
        scroll = self.verticalScrollBar().value()
        painter.translate(0, -scroll)
        painter.setFont(source.font())
        painter.setPen(QColor('#8a8f98'))
        for row in self.rows:
            if scroll-self._line_height <= row.y <= scroll+self.viewport().height():
                label = str(row.number) if row.number else '+' if row.kind == 'incoming' else '−'
                painter.drawText(source.line_number_rect(row.y), Qt.AlignRight | Qt.AlignVCenter, label)
        for page in self.pages:
            if page.top > scroll+self.viewport().height() or page.top+page.height < scroll:
                continue
            painter.setPen(self.palette().color(QPalette.Mid))
            painter.drawRect(QRectF(1, page.top+1, self._page_width-2, page.height-2))
            painter.setPen(QColor('#8a8f98'))
            page_rows = [row for row in self.rows if row.page == page.number]
            numbered = [row for row in page_rows if row.number]
            count = numbered[-1].number if numbered else 0
            last_y = max((row.y+row.pitch for row in page_rows), default=page.top+self._top)
            for number in range(count+1, source.lines_per_page+1):
                y = last_y+(number-count-1)*self._line_height
                painter.drawText(source.line_number_rect(y), Qt.AlignRight | Qt.AlignVCenter, str(number))
            footer = source.page_number_rect(page.number-1)
            footer.translate(0, page.top-(page.number-1)*self._page_height+page.height-self._page_height)
            painter.setFont(source.page_number_font())
            painter.drawText(footer, Qt.AlignRight | Qt.AlignVCenter, str(page.number))
            painter.setFont(source.font())
            painter.fillRect(QRectF(0, page.top+page.height-12, self.viewport().width(), 12),
                             self.palette().color(QPalette.Window))
        painter.resetTransform()
        for marker in self.boundary_marks:
            rect = self.boundary_rect(marker)
            color = QColor('#f2aba7' if marker.side == 'original' else '#9edcb0')
            painter.fillRect(rect, color)
            painter.setPen(QColor('#6e2530' if marker.side == 'original' else '#1e5531'))
            painter.drawText(rect, Qt.AlignCenter, '|' if marker.empty else '↵')

    def boundary_rect(self, marker):
        cursor = QTextCursor(self.document())
        cursor.setPosition(marker.display_position)
        rect = self.cursorRect(cursor)
        return QRectF(rect.x()-14, rect.y(), 12, max(14, rect.height()))
