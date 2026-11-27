"""A read-only comparison over native transcript pages."""
from bisect import bisect_right
from dataclasses import dataclass, replace
import math

from PySide6.QtCore import Qt, Signal, QPointF, QSizeF, QRectF, QSignalBlocker
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPainterPath,
                          QPainterPathStroker, QPalette, QPen, QTextBlockFormat, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit

from app.src.casecat.anchors import utf16_index
from app.src.native_editor import NativeTranscriptEditor, PageLine, _tab_positions
from app.src.review_colors import ADDITION_BACKGROUND, CHECK_BACKGROUND, CHECK_FOREGROUND
from app.src.suggestions import distance_to_ranges, preview_ranges, preview_start


_ROW_COLORS = {'original': QColor('#fbe9e7'), 'incoming': QColor('#e7f5ea')}
_FOCUS_WIDTH = 4
_FOCUS_INSET = 1
_FOCUS_PEN = QPen(Qt.black, 2 * _FOCUS_INSET, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin)


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
    # The right cell shares a display row with the plaintiff but has its own
    # native text range, after all text in the caption's left cell.
    caption_cell: tuple[int, int, int, int] | None = None
    background_rect: QRectF | None = None
    tab_ends: tuple[float, ...] = ()


@dataclass(frozen=True)
class ReviewPage:
    number: int
    top: float
    height: float


@dataclass(frozen=True)
class BoundaryMark:
    side: str
    edit_index: int
    display_position: int
    empty: bool


def _row_groups(model, old_rows, new_rows):
    pairs = model.compare_rows([(r.source_start, r.source_end) for r in old_rows],
                               [(r.source_start, r.source_end) for r in new_rows])
    for old_slice, new_slice, section in pairs:
        original = old_rows[old_slice]
        start, end = section.incoming_range
        if not section.edit_indices:
            yield original, [], section
            continue
        incoming = []
        for row in new_rows[new_slice]:
            a, b = max(start, row.source_start), min(end, row.source_end)
            if a >= b and not (row.source_start == row.source_end and start <= row.source_start <= end):
                continue
            first, last = a - row.source_start, b - row.source_start
            incoming.append(replace(row, source_start=a, source_end=b, text=row.text[first:last],
                                    tab_ends=row.tab_ends[row.text.count('\t', 0, first):row.text.count('\t', 0, last)],
                                    x=original[0].x if original and not incoming else row.x))
        yield original, incoming, section


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
                bounds = editor.document().documentLayout().blockBoundingRect(block)
                y = bounds.top() + line.y()
                page = int(y // editor._page_height) + 1
                number = editor.number_at_y(page - 1, y, counts.get(page, 0) + 1)
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
                x = bounds.left() + line.cursorToX(line.textStart())[0]
                tab_ends = []
                if '\t' in text:
                    tab_end = line.textStart()
                    for piece in text.split('\t')[:-1]:
                        tab_end += _qt(piece) + 1
                        tab_ends.append(bounds.left() + line.cursorToX(tab_end)[0])
                rows.append(ReviewRow(side, positions[start], positions[end], text,
                                      page, number, page, number, y,
                                      x, pitch,
                                      line.y() - index*pitch, font, glyph_height=line.height(),
                                      tab_ends=tuple(tab_ends)))
        block = block.next()
    return rows


def _combine_caption_cells(rows, source):
    """Place unchanged cell text on the same physical line in read-only review."""
    for table in reversed(getattr(source._paragraph_styles, 'caption_tables', ())):
        selected = [i for i, row in enumerate(rows) if row.kind != 'incoming'
                    and table.start < row.source_start <= table.end]
        if not selected:
            continue
        first, stop = selected[0], selected[-1] + 1
        group = rows[first:stop]
        if any(row.kind != 'equal' for row in group):
            continue
        left = [row for row in group if row.source_start <= table.separator]
        for right in (row for row in group if row.source_start > table.separator):
            line = next((r for r in left if abs(r.y - right.y) < 1), None)
            if line is None:
                left.append(right)
                continue
            cell_width = QFontMetricsF(line.font).horizontalAdvance('0')
            column = max(len(line.text), round((right.x - line.x) / cell_width))
            line.caption_cell = (column, right.source_start, right.incoming_start, len(right.text))
            line.text = line.text.ljust(column) + right.text
        rows[first:stop] = sorted(left, key=lambda row: row.y)


class InlineReviewEditor(QTextEdit):
    selected = Signal(int)
    source_activated = Signal(str, int)
    history_requested = Signal(bool)

    def __init__(self, font=None, parent=None):
        super().__init__(parent)
        self.model = None
        self.rows, self.pages = [], []
        self._notice_gutters = {}
        self.boundary_marks = []
        self.source_editors = None
        self._external_sources = False
        self._current_edit = -1
        self._edit_cursors = []
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

    def set_model(self, model, *, unmatched_speakers=()):
        anchor = self.source_position() if self.rows else ('original', 0)
        self.model = model
        self._highlight_ranges = [preview_ranges(edit) for edit in model.edits]
        self._edit_cursors = [[] for _ in model.edits]
        original, incoming = self._sources(model)
        self._page_width, self._page_height = original._page_width, original._page_height
        self._left, self._right = original._left, original._right
        self._top, self._bottom = original._top, original._bottom
        self._line_height = original._line_height
        self.setFont(original.font())
        self.document().setDefaultFont(original.font())
        self.rows = []
        old_rows, new_rows = _native_rows(original, 'original'), _native_rows(incoming, 'incoming')
        native_geometry = {(row.source_start, row.source_end): (row.y, row.pitch) for row in old_rows}

        extra = [0.] * max(1, original.document().pageCount())
        old_index, added_height = 0, 0.

        def append_original(row, section_index=-1, edits=(), incoming_start=None):
            row.kind = 'original' if section_index >= 0 else 'equal'
            row.section, row.edit_indices = section_index, edits
            row.y += added_height
            if row.kind == 'equal':
                row.incoming_start = incoming_start
            self.rows.append(row)

        for section_index, (old_group, new_group, section) in enumerate(_row_groups(model, old_rows, new_rows)):
            edits = section.edit_indices
            if not edits:
                append_original(old_group[0], incoming_start=section.incoming_range[0])
                old_index += 1
                continue
            first_row = len(self.rows)
            reference = (old_group[-1] if old_group else
                         old_rows[min(old_index, len(old_rows)-1)]) if old_rows else None
            page = reference.page if reference else 1
            if old_group:
                # Use the source's blank line spacing for the paired incoming
                # row before adding any height to the comparison page.
                baseline_end = reference.y+reference.pitch+added_height
                # Pack both sides of a changed passage at the same compact
                # pitch. Native source positions and line numbers stay intact.
                y = old_group[0].y
                for source_row in old_group:
                    row = replace(_compact(source_row), y=y)
                    y += row.pitch
                    append_original(row, section_index, edits)
                    old_index += 1
                y += added_height
            else:
                a = section.original_range[0]
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
                                      glyph_height=row.glyph_height, tab_ends=row.tab_ends)
                self.rows.append(projected)
                y += row.pitch
            if not new_group:
                c = section.incoming_range[0]
                row = _compact(ReviewRow('incoming', c, c, '', page, 0, page, 0,
                                        y, self._left, self._line_height,
                                        reference.leading if reference else 0, incoming.font(),
                                        section_index, edits,
                                        glyph_height=reference.glyph_height if reference else 0))
                self.rows.append(row)
                y += row.pitch
            if len(edits) > 1:
                for row in self.rows[first_row:]:
                    text = getattr(model, row.kind).text
                    # Both lines touch an edited paragraph separator. Context
                    # elsewhere in the pair belongs to its nearest decision.
                    start, end = row.source_start, row.source_end
                    start -= int(start > 0 and text[start - 1] == '\n')
                    end += int(end < len(text) and text[end] == '\n')
                    distances = {i: distance_to_ranges(self._highlight_ranges[i], row.kind, start, end)
                                 for i in edits}
                    nearest = min(distances.values())
                    row.edit_indices = tuple(i for i in edits if distances[i] == nearest)
            amount = max(0, y-baseline_end)
            added_height += amount
            extra[page-1] += amount
        # Lay out each native page independently. Compact sections may span
        # pages, but cannot pull the next page's numbered rows across a footer.
        # Include negative spacing adjustments so following text does not keep
        # the empty space removed by compacting the original rows.
        self.pages = []
        top = 0.
        for page in range(1, len(extra)+1):
            shift = 0.
            cursor_y = top+self._top
            previous = None
            for row in (row for row in self.rows if row.page == page):
                if row.kind != 'incoming' and row.number:
                    source_y, source_pitch = native_geometry[row.source_start, row.source_end]
                    row.y = top + source_y-(page-1)*self._page_height + shift
                    shift += row.pitch-source_pitch
                else:
                    row.y = cursor_y
                    shift += row.pitch
                if previous is not None and previous.kind == 'incoming' and row.kind == 'original':
                    # Use a visual blank line between comparisons. Any native
                    # space already at this boundary counts toward the gap.
                    gap = max(0., cursor_y + previous.pitch - row.y)
                    row.y += gap
                    shift += gap
                cursor_y = row.y+row.pitch
                previous = row
            height = max(self._page_height, self._page_height+shift,
                         cursor_y-top+self._bottom)
            self.pages.append(ReviewPage(page, top, height))
            top += height
        _combine_caption_cells(self.rows, original)
        self._render_document(unmatched_speakers)
        self._notice_gutters = {}
        if getattr(original._paragraph_styles, 'cover_length', 0):
            rows_by_page = {page.number: [] for page in self.pages}
            for row in self.rows:
                rows_by_page[row.page].append(row)
            for page in self.pages:
                self._notice_gutters[page.number] = self._notice_line_positions(
                    page, rows_by_page[page.number], native_geometry)
        self.boundary_marks = []
        for index, edit in enumerate(model.edits):
            preview = self._highlight_ranges[index]
            for span in edit.ranges:
                a, b, c, d = span
                for side, start, end in (('original', a, b), ('incoming', c, d)):
                    if start == end and span not in preview:
                        continue
                    content = getattr(model, side).text[start:end]
                    if start != end and (content.strip() or '\n' not in content):
                        continue
                    position = self.display_position(side, start, edit_index=index)
                    if position is not None:
                        self.boundary_marks.append(BoundaryMark(side, index, position, start == end))
        side, position = anchor
        self.set_source_position(side, min(position, len(getattr(model, side).text)))
        self._refresh_selections()

    def _notice_line_positions(self, page, rows, native_geometry):
        """Keep a single gutter grid as comparison rows expand or compact the page."""
        original = sorted((native_geometry[r.source_start, r.source_end][0], r.y)
                          for r in rows if r.number)
        source_top = (page.number - 1) * self._page_height
        offset = page.top - source_top
        anchors = iter(original)
        anchor = next(anchors, None)
        last = max((r.y + r.pitch for r in rows), default=page.top + self._top)
        positions = []
        for n in range(self.source_editors[0].lines_per_page):
            native_y = source_top + self._top + n * self._line_height
            while anchor and anchor[0] <= native_y + 1:
                offset = anchor[1] - anchor[0]
                anchor = next(anchors, None)
            y = native_y + offset
            if not anchor and original and native_y > original[-1][0] + 1:
                y = max(y, last, positions[-1] + self._line_height if positions else y)
            positions.append(y)
        return positions

    def _render_document(self, unmatched_speakers):
        document = self.document()
        speaker_ends = [end for _, end in unmatched_speakers]
        speaker_mark = QTextCharFormat()
        speaker_mark.setBackground(QColor(CHECK_BACKGROUND))
        speaker_mark.setForeground(QColor(CHECK_FOREGROUND))
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
                block.setTabPositions(_tab_positions(end - row.x for end in row.tab_ends))
                # Every display block contains one physical row. Put spacing
                # in margins so switching between native and compact pitch
                # cannot move the glyph relative to its painted line number.
                block.setLineHeight(_compact(row).pitch, QTextBlockFormat.FixedHeight.value)
                cursor.setBlockFormat(block)
                char = QTextCharFormat()
                char.setFont(row.font)
                if row.kind != 'equal':
                    char.setForeground(QColor('#6e2530' if row.kind == 'original' else '#1e5531'))
                cursor.select(QTextCursor.BlockUnderCursor)
                cursor.setCharFormat(char)
                if row.kind != 'equal':
                    for index in row.edit_indices:
                        for a, b, c, d in self._highlight_ranges[index]:
                            start, end = (a, b) if row.kind == 'original' else (c, d)
                            start, end = max(start, row.source_start), min(end, row.source_end)
                            if start >= end:
                                continue
                            cursor.setPosition(row.display_start+_qt(row.text[:start-row.source_start]))
                            cursor.setPosition(row.display_start+_qt(row.text[:end-row.source_start]), QTextCursor.KeepAnchor)
                            mark = QTextCharFormat()
                            mark.setBackground(QColor('#f2aba7' if row.kind == 'original' else ADDITION_BACKGROUND))
                            cursor.mergeCharFormat(mark)
                            self._edit_cursors[index].append(QTextCursor(cursor))
                if speaker_ends and row.kind != 'original':
                    source_start = row.incoming_start if row.kind == 'equal' else row.source_start
                    source_end = source_start + len(row.text)
                    first = bisect_right(speaker_ends, source_start)
                    for index in range(first, len(unmatched_speakers)):
                        start, end = unmatched_speakers[index]
                        if start >= source_end:
                            break
                        left = max(0, start - source_start)
                        right = min(len(row.text), end - source_start)
                        if left < right:
                            cursor.setPosition(position + _qt(row.text[:left]))
                            cursor.setPosition(position + _qt(row.text[:right]), QTextCursor.KeepAnchor)
                            cursor.mergeCharFormat(speaker_mark)
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
            previous_bottom = 0
            for index, (row, leading, height) in enumerate(measured):
                # A changed table can put both caption columns in reading order.
                # Qt stacks those blocks, even when their native rows share a y.
                origin = max(previous_bottom, row.y - leading)
                row.y = origin + leading
                if row.kind != 'equal':
                    row.background_rect = QRectF(row.x, row.y, self._page_width - row.x, row.pitch)
                    if index:
                        previous = self.rows[index - 1]
                        if previous.section == row.section and previous.page == row.page:
                            # Share the paint edge when either the block boxes or
                            # their glyphs touch. Keep intentional paragraph space.
                            gap = min(origin - previous_bottom, row.y - previous.background_rect.bottom())
                            if gap < 1:
                                previous.background_rect.setBottom(row.y)
                cursor.setPosition(row.display_start)
                block = cursor.blockFormat()
                if index == 0:
                    fmt = frame.frameFormat()
                    fmt.setTopMargin(origin)
                    frame.setFrameFormat(fmt)
                else:
                    block.setTopMargin(origin - previous_bottom)
                cursor.setBlockFormat(block)
                previous_bottom = origin + height
            fmt = frame.frameFormat()
            bottom = (self.pages[-1].top+self.pages[-1].height-previous_bottom
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
        if row.caption_cell:
            column, original, _, length = row.caption_cell
            index = utf16_index(row.text, local)
            if index >= column:
                return 'original', original + min(length, index - column)
            return 'original', min(row.source_end, row.source_start + index)
        return ('incoming' if row.kind == 'incoming' else 'original',
                row.source_start+utf16_index(row.text, local))

    def source_position(self):
        return self._source_at(self.textCursor().position())

    def display_position(self, side, position, *, edit_index=None):
        candidates = []
        for row in self.rows:
            if edit_index is not None and edit_index not in row.edit_indices:
                continue
            if row.caption_cell:
                column, original, incoming, length = row.caption_cell
                cell_start = original if side == 'original' else incoming
                if cell_start <= position <= cell_start + length:
                    return row.display_start + _qt(row.text[:column + position - cell_start])
            if side == 'incoming' and row.kind == 'equal' and row.incoming_start is not None:
                start = row.incoming_start
            elif (side == 'incoming') == (row.kind == 'incoming'):
                start = row.source_start
            else:
                continue
            end = start + (row.source_end - row.source_start if row.caption_cell else len(row.text))
            local = max(start, min(position, end))
            if local == position or edit_index is not None:
                # A changed separator can sit just before its owned empty row.
                candidates.append((abs(local - position), local == end and start != end,
                                   row.display_start + _qt(row.text[:local - start])))
        if candidates:
            return min(candidates)[2]
        return None

    def set_source_position(self, side, position, keep_anchor=False, *, edit_index=None):
        display = self.display_position(side, position, edit_index=edit_index)
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
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or self.textCursor().hasSelection():
            return
        caret = self.textCursor().position()
        point = event.position()
        scroll = QPointF(self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        # The nearest caret can be after the character under the pointer.
        clicked = self.document().documentLayout().hitTest(point + scroll, Qt.ExactHit)
        playback = self._source_at(clicked if clicked >= 0 else caret)

        index = None
        for mark in self.boundary_marks:
            hit = (mark.display_position == caret if mark.empty
                   else self.boundary_rect(mark).contains(point))
            if hit:
                index = mark.edit_index
                break
        row = self._row_at(caret)
        if index is None and row and row.edit_indices:
            side, position = playback
            index = min(row.edit_indices, key=lambda i: distance_to_ranges(
                self.model.edits[i].ranges, side, position, position))
        if index is not None:
            self.selected.emit(index)
        self.source_activated.emit(*playback)

    def highlight_edit(self, index):
        if self._current_edit != index:
            self._current_edit = index
            self.viewport().update()

    def focus_edit(self, index, *, prefer_incoming=False):
        if self.model is None or not 0 <= index < len(self.model.edits):
            return
        self.highlight_edit(index)
        change = self.model.edits[index]
        if change.ranges:
            a, b, c, d = change.ranges[0]
            side = 'incoming' if a == b or (prefer_incoming and c != d) else 'original'
            if self.set_source_position(side, preview_start(change, side), edit_index=index):
                self.ensureCursorVisible()
                rect = self.cursorRect()
                self.verticalScrollBar().setValue(max(0, self.verticalScrollBar().value()+rect.y()-self.viewport().height()//2))

    def set_source_highlight(self, side, start, end):
        self._source_highlight = side, start, end
        self._refresh_selections()

    def clear_source_highlight(self):
        self._source_highlight = None
        self._refresh_selections()

    def _refresh_selections(self):
        marks = []
        if self._source_highlight:
            side, start, end = self._source_highlight
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
                mark.format.setBackground(QColor(120, 165, 220, 85))
                marks.append(mark)
        super().setExtraSelections(marks)
        self.viewport().update()

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

    def center_source_position(self):
        if not self.rows:
            return 'original', 0
        center = self.verticalScrollBar().value() + self.viewport().height() / 2
        row = min(self.rows, key=lambda row: abs(row.y - center))
        return ('incoming' if row.kind == 'incoming' else 'original'), row.source_start

    def scroll_to_source_position(self, side, position):
        display = self.display_position(side, position)
        row = self._row_at(display) if display is not None else None
        if row:
            self.verticalScrollBar().setValue(round(row.y - self.viewport().height() / 2))

    def scroll_to_center_line(self, line):
        lines = self.page_lines()
        if lines:
            row = lines[min(max(0, int(line)), len(lines)-1)]
            self.verticalScrollBar().setValue(max(0, int(row.y-self.viewport().height()/2)))

    def _paint_row_backgrounds(self, event):
        x, y = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        visible = event.rect().translated(x, y)
        with QPainter(self.viewport()) as painter:
            painter.translate(-x, -y)
            for row in self.rows:
                if row.y > visible.bottom() + 1:
                    break
                band = row.background_rect
                if band is not None and band.bottom() > visible.top():
                    painter.fillRect(band, _ROW_COLORS[row.kind])

    def _paint_edit_outline(self, painter, scroll, marker_rects):
        """Trace the visible text on each side, including the steps at soft wraps."""
        if not 0 <= self._current_edit < len(self._edit_cursors):
            return
        paths = {side: QPainterPath() for side in _ROW_COLORS}
        visible_top = scroll - _FOCUS_WIDTH
        visible_bottom = scroll + self.viewport().height() + _FOCUS_WIDTH
        for cursor in self._edit_cursors[self._current_edit]:
            block = cursor.block()
            row = self.rows[block.blockNumber()]
            band = row.background_rect
            if band.bottom() < visible_top or band.top() > visible_bottom:
                continue
            layout = block.layout()
            line = layout.lineAt(0)
            start = cursor.selectionStart() - block.position()
            length = cursor.selectionEnd() - cursor.selectionStart()
            path = paths[row.kind]
            origin = layout.position().x()
            for run in line.glyphRuns(start, length):
                rect = run.boundingRect()
                path.addRect(origin + rect.left(), band.top(), rect.width(), band.height())
            # Tabs occupy highlighted space, but have no glyph run.
            pos = start
            for piece in cursor.selectedText().split('\t')[:-1]:
                pos += _qt(piece)
                a, b = line.cursorToX(pos)[0], line.cursorToX(pos + 1)[0]
                path.addRect(origin + min(a, b), band.top(), abs(b - a), band.height())
                pos += 1
        contours = list(paths.values())
        for rect in marker_rects:
            marker_path = QPainterPath()
            marker_path.addRect(rect)
            contours.append(marker_path)
        painter.setPen(_FOCUS_PEN)
        selected = QPainterPath()
        for path in contours:
            path.setFillRule(Qt.WindingFill)
            contour = path.simplified()
            painter.drawPath(contour)
            selected = selected.united(contour)
        # Keep one pixel inside each contour, including where red meets green.
        # Only the outer half of this wider stroke contributes additional ink.
        stroker = QPainterPathStroker(_FOCUS_PEN)
        stroker.setWidth(2 * (_FOCUS_WIDTH - _FOCUS_INSET))
        painter.fillPath(stroker.createStroke(selected).subtracted(selected), Qt.black)

    def paintEvent(self, event):
        self._paint_row_backgrounds(event)
        super().paintEvent(event)
        if not self.source_editors:
            return
        source = self.source_editors[0]
        painter = QPainter(self.viewport())
        scroll = self.verticalScrollBar().value()
        scroll_x = self.horizontalScrollBar().value()
        painter.translate(-scroll_x, -scroll)
        painter.setFont(source.font())
        painter.setPen(QColor('#8a8f98'))
        for row in self.rows:
            if row.number and row.page in self._notice_gutters:
                continue
            if scroll-self._line_height <= row.y <= scroll+self.viewport().height():
                label = str(row.number) if row.number else '+' if row.kind == 'incoming' else '−'
                painter.drawText(source.line_number_rect(row.y), Qt.AlignRight | Qt.AlignVCenter, label)
        for page in self.pages:
            if page.top > scroll+self.viewport().height() or page.top+page.height < scroll:
                continue
            painter.setPen(self.palette().color(QPalette.Mid))
            painter.drawRect(QRectF(1, page.top+1, self._page_width-2, page.height-2))
            painter.setPen(QColor('#8a8f98'))
            if page.number in self._notice_gutters:
                gutter = enumerate(self._notice_gutters[page.number], 1)
            else:
                page_rows = [row for row in self.rows if row.page == page.number]
                count = next((row.number for row in reversed(page_rows) if row.number), 0)
                last_y = max((row.y + row.pitch for row in page_rows), default=page.top + self._top)
                gutter = ((n, last_y + (n - count - 1) * self._line_height)
                          for n in range(count + 1, source.lines_per_page + 1))
            for number, y in gutter:
                painter.drawText(source.line_number_rect(y), Qt.AlignRight | Qt.AlignVCenter, str(number))
            footer = source.page_number_rect(page.number-1)
            footer.translate(0, page.top-(page.number-1)*self._page_height+page.height-self._page_height)
            painter.setFont(source.page_number_font())
            painter.drawText(footer, Qt.AlignRight | Qt.AlignVCenter, str(page.number))
            painter.setFont(source.font())
            painter.fillRect(QRectF(0, page.top+page.height-12, self.viewport().width(), 12),
                             self.palette().color(QPalette.Window))
        marker_rects = []
        for marker in self.boundary_marks:
            rect = self.boundary_rect(marker).translated(scroll_x, scroll)
            if marker.empty:
                color = QColor('#116329' if marker.side == 'original' else '#82071e')
                # A cosmetic pen keeps the stroke visible when the page scales down.
                painter.setPen(QPen(color, 0))
                painter.drawLine(rect.topLeft(), rect.bottomLeft())
            else:
                painter.fillRect(rect, QColor('#f2aba7' if marker.side == 'original' else ADDITION_BACKGROUND))
                painter.setPen(QColor('#6e2530' if marker.side == 'original' else '#1e5531'))
                painter.drawText(rect, Qt.AlignCenter, '↵')
            if marker.edit_index == self._current_edit:
                marker_rects.append(rect.adjusted(-2, 0, 2, 0) if marker.empty else rect)
        # Paint on top so the next row's text background cannot cut off a border.
        self._paint_edit_outline(painter, scroll, marker_rects)

    def boundary_rect(self, marker):
        cursor = QTextCursor(self.document())
        cursor.setPosition(marker.display_position)
        rect = self.cursorRect(cursor)
        if marker.empty:
            return QRectF(rect.x(), rect.y()+2, 1, max(1, rect.height()-4))
        return QRectF(rect.x()-14, rect.y(), 12, max(14, rect.height()))
