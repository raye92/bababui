from html import escape
from app.src.transcript_diff import parse_transcript, align_blocks, word_spans, render_blocks, is_formatted, equivalent_content
from PySide6.QtWidgets import (QScrollArea, QWidget, QFrame, QPlainTextEdit,
                               QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy)
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QColor

# Width of the existing left margin shared by the +/- markers and the line
# numbers â€” reused here rather than adding a new gutter.
GUTTER_WIDTH = 24


class _LineNumberArea(QWidget):
    """Paints line numbers into the editor's existing left viewport margin."""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def paintEvent(self, event):
        self._editor._paint_line_numbers(event)


class _NumberedEdit(QPlainTextEdit):
    """QPlainTextEdit that paints 1-based line numbers in its left margin.

    The numbers live inside the viewport's left margin (no separate gutter
    widget in the layout) so a numbered editor and the diff's equal blocks
    line their text up in the same column.
    """

    def __init__(self, font, start_line=1, parent=None):
        super().__init__(parent)
        # 1-based number of the first line shown in this widget.
        self._start_line = start_line

        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.document().setDocumentMargin(0)

        self._line_area = _LineNumberArea(self)
        self.updateRequest.connect(self._on_update_request)
        self.blockCountChanged.connect(self._refresh_gutter)
        self._refresh_gutter()

    def _gutter_width(self):
        # Wide enough for the largest line number this widget can show, so
        # multi-digit numbers never clip. Shared style: number font is two
        # points smaller than the body text.
        highest = self._start_line + max(0, self.document().blockCount() - 1)
        digits = max(2, len(str(max(1, highest))))
        nf = QFont(self.font())
        nf.setPointSizeF(max(7.0, self.font().pointSizeF() - 2))
        return QFontMetrics(nf).horizontalAdvance('0' * digits) + 10

    def _refresh_gutter(self):
        w = self._gutter_width()
        self.setViewportMargins(w, 0, 0, 0)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(), w, cr.height()))
        self._line_area.update()

    def _on_update_request(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(
            QRect(cr.left(), cr.top(), self._gutter_width(), cr.height()))

    def _paint_line_numbers(self, event):
        painter = QPainter(self._line_area)
        painter.setPen(QColor('#8a8f98'))
        number_font = QFont(self.font())
        number_font.setPointSizeF(max(7.0, self.font().pointSizeF() - 2))
        painter.setFont(number_font)

        width = self._line_area.width()
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        offset = self.contentOffset()
        top = self.blockBoundingGeometry(block).translated(offset).top()
        bottom = top + self.blockBoundingRect(block).height()
        line_height = int(self.fontMetrics().height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(self._start_line + block_number)
                painter.drawText(0, int(top), width - 5, line_height,
                                 Qt.AlignRight | Qt.AlignVCenter, number)
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1


class LineNumberedEditor(_NumberedEdit):
    """Full, scrollable transcript editor with a line-number gutter.

    Drop-in replacement for a plain QPlainTextEdit so the original and incoming
    editors look identical to the diff view's numbered rows.
    """

    def __init__(self, font, parent=None):
        super().__init__(font, start_line=1, parent=parent)

    def center_line(self):
        """0-based document line currently nearest the vertical center."""
        sb = self.verticalScrollBar()
        line_h = max(1, self.fontMetrics().lineSpacing())
        visible = max(1, self.viewport().height() // line_h)
        return sb.value() + visible // 2

    def scroll_to_center_line(self, line):
        """Scroll so `line` (0-based) sits at the vertical center."""
        sb = self.verticalScrollBar()
        line_h = max(1, self.fontMetrics().lineSpacing())
        visible = max(1, self.viewport().height() // line_h)
        sb.setValue(max(0, int(line) - visible // 2))


class _EqualBlock(_NumberedEdit):
    """Frameless, auto-height editable widget for unchanged diff lines.

    Edits here update both original and incoming (they stay identical in equal
    regions), so the diff structure is preserved and no new variance is created.
    """

    # Emitted on every keystroke â€” caller saves to disk without re-rendering.
    saved = Signal(list)
    # Emitted on focusOut when the line count changed â€” caller must re-render
    # so hunk indices stay accurate.
    needs_rerender = Signal()

    def __init__(self, lines, font, start_line, gutter_width, parent=None):
        # Fixed gutter width shared with the diff rows so unchanged and changed
        # lines align in the same column regardless of their own digit counts.
        self._fixed_gutter = gutter_width
        super().__init__(font, start_line=start_line, parent=parent)
        self._initial_count = len(lines)

        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._suppress = True
        self.setPlainText('\n'.join(lines))
        self._suppress = False

        self._sync_height()
        self.document().contentsChanged.connect(self._on_changed)

    def _gutter_width(self):
        return self._fixed_gutter

    def _on_changed(self):
        if self._suppress:
            return
        self._sync_height()
        self.saved.emit(self.toPlainText().split('\n'))

    def _sync_height(self):
        # Size to the *actual* laid-out content height. fontMetrics().lineSpacing()
        # under-estimates what QPlainTextEdit really renders, so with both
        # scrollbars forced off the trailing lines were getting clipped (only
        # reachable by drag-selecting). Summing the real block heights guarantees
        # every line is visible and pushes the following diff rows down properly.
        doc = self.document()
        height = 0.0
        block = doc.firstBlock()
        while block.isValid():
            height += self.blockBoundingRect(block).height()
            block = block.next()
        if height <= 0:
            # Document not laid out yet (pre-show): fall back to a metrics estimate.
            height = self.fontMetrics().lineSpacing() * max(1, doc.blockCount())
        self.setFixedHeight(int(round(height + 2 * doc.documentMargin())) + 2)

    def wheelEvent(self, event):
        # Unchanged blocks are not scrollable: let the wheel fall through to
        # the outer diff scroll area so the whole page scrolls instead.
        event.ignore()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_height()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # If lines were added/removed the cached hunk indices are stale.
        if self.document().blockCount() != self._initial_count:
            self.needs_rerender.emit()



class DiffView(QScrollArea):
    """Review logical content while retaining paragraph structure."""
    resolved = Signal(str, str)
    autosaved = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._mono = QFont('Courier New', 12)
        self._mono.setStyleHint(QFont.Monospace)
        self.original_blocks, self.incoming_blocks = [], []
        self._formatted = False
        self._regions, self._rows = [], []
        self._gutter = GUTTER_WIDTH
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setWidget(self._container)

    def set_texts(self, original_text, incoming_text):
        self._formatted = is_formatted(original_text) or is_formatted(incoming_text)
        self.original_blocks = parse_transcript(original_text)
        self.incoming_blocks = parse_transcript(incoming_text)
        self._render()

    def _clear(self):
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _compute_gutter(self):
        digits = max(2, len(str(max(1, len(self.original_blocks)))))
        return QFontMetrics(self._mono).horizontalAdvance('0' * digits + ' \u2212') + 10

    def _render(self):
        self._clear()
        self._rows = []
        self._gutter = self._compute_gutter()
        self._regions = []
        for op in align_blocks(self.original_blocks, self.incoming_blocks):
            # Group only contiguous runs of the same one-sided change.
            # Replacement pairs remain independent review decisions.
            if (op[0] in ('equal', 'insert', 'delete') and self._regions
                    and self._regions[-1][0] == op[0]
                    and self._regions[-1][2] == op[1] and self._regions[-1][4] == op[3]):
                self._regions[-1][2], self._regions[-1][4] = op[2], op[4]
            else:
                self._regions.append(list(op))
        for region in self._regions:
            tag, i1, i2, j1, j2 = region
            widget = self._make_equal_block(region) if tag == 'equal' else self._make_hunk(region)
            self._layout.addWidget(widget)
            start = self.original_blocks[i1].source_start if i1 < len(self.original_blocks) else (
                self.original_blocks[-1].source_end if self.original_blocks else 0)
            end = self.original_blocks[i2-1].source_end if i2 > i1 else start
            self._rows.append((widget, start, end-start))
        self._layout.addStretch(1)

    @property
    def has_changes(self):
        return any(r[0] != 'equal' for r in self._regions)

    def _texts(self):
        original = render_blocks(self.original_blocks, self._formatted)
        incoming = render_blocks(self.incoming_blocks, self._formatted)
        if equivalent_content(self.original_blocks, self.incoming_blocks):
            incoming = original
        return original, incoming

    def _refresh_blocks(self):
        self.set_texts(*self._texts())

    def _make_equal_block(self, region):
        _, i1, i2, j1, j2 = region
        lines = [b.indent + b.text for b in self.original_blocks[i1:i2]]
        block = _EqualBlock(lines, self._mono, i1+1, self._gutter)
        block.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        def on_saved(new_lines):
            _, oi1, oi2, ij1, ij2 = region
            replacement = parse_transcript('\n'.join(new_lines))
            self.original_blocks[oi1:oi2] = replacement
            self.incoming_blocks[ij1:ij2] = replacement.copy()
            da, db = len(replacement)-(oi2-oi1), len(replacement)-(ij2-ij1)
            following = False
            for other in self._regions:
                if other is region:
                    other[2], other[4] = oi1+len(replacement), ij1+len(replacement)
                    following = True
                elif following:
                    other[1] += da
                    other[2] += da
                    other[3] += db
                    other[4] += db
            self.autosaved.emit(*self._texts())
        block.saved.connect(on_saved)
        block.needs_rerender.connect(self._refresh_blocks)
        return block

    def _make_line_row(self, text, kind, spans=None, number=None):
        bg, fg, mark = ('#ffd7d5', '#82071e', '\u2212') if kind == 'delete' else ('#ccffd8', '#116329', '+')
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        marker = QLabel(f'{number} {mark}' if number is not None else mark)
        marker.setFont(self._mono)
        marker.setFixedWidth(self._gutter)
        marker.setAlignment(Qt.AlignCenter)
        marker.setStyleSheet(f'background-color:{bg}; color:{fg};')
        content = QLabel(text or ' ')
        content.setFont(self._mono)
        content.setTextFormat(Qt.PlainText)
        content.setWordWrap(True)
        if spans is not None:
            parts, position = [], 0
            highlight = '#ffaaa5' if kind == 'delete' else '#7ee2a8'
            for start, end in spans:
                parts.append(escape(text[position:start]))
                parts.append(f'<span style="background-color:{highlight}; font-weight:bold">' + escape(text[start:end]) + '</span>')
                position = end
            parts.append(escape(text[position:]))
            content.setTextFormat(Qt.RichText)
            content.setText('<span style="white-space:pre-wrap">' + ''.join(parts) + '</span>')
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        content.setStyleSheet(f'background-color:{bg}; color:{fg};')
        layout.addWidget(marker)
        layout.addWidget(content)
        return row

    def _make_hunk(self, region):
        tag, i1, i2, j1, j2 = region
        block = QWidget()
        v = QVBoxLayout(block)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        old = '\n'.join(b.indent+b.text for b in self.original_blocks[i1:i2])
        new = '\n'.join(b.indent+b.text for b in self.incoming_blocks[j1:j2])
        old_spans, new_spans = word_spans(old, new) if tag == 'replace' else (None, None)
        for blocks, kind, spans in ((self.original_blocks[i1:i2], 'delete', old_spans),
                                   (self.incoming_blocks[j1:j2], 'insert', new_spans)):
            offset = 0
            for index, paragraph in enumerate(blocks):
                text = paragraph.indent + paragraph.text
                local = None if spans is None else [(max(0, start-offset), min(len(text), end-offset))
                    for start, end in spans if start < offset+len(text) and end > offset]
                number = i1+index+1 if kind == 'delete' or index < i2-i1 else None
                v.addWidget(self._make_line_row(text, kind, local, number))
                offset += len(text)+1
        bar = QWidget()
        bar.setStyleSheet('background:#f6f8fa;')
        h = QHBoxLayout(bar)
        h.setContentsMargins(self._gutter+4, 3, 8, 3)
        h.setSpacing(6)
        caption = QLabel('Incoming change')
        caption.setStyleSheet('color:#57606a; font-size:11px;')
        h.addWidget(caption)
        h.addStretch(1)
        for title, color, callback in (('\u2713 Accept', '#1f883d', self._accept), ('\u2717 Deny', '#cf222e', self._deny)):
            button = QPushButton(title)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(22)
            button.setStyleSheet(f'border:none; background:{color}; color:white; padding:0 10px; border-radius:3px; font-size:11px;')
            button.clicked.connect(lambda _=False, callback=callback: callback(*region[1:]))
            h.addWidget(button)
        v.addWidget(bar)
        return block

    def _accept(self, i1, i2, j1, j2):
        self.original_blocks[i1:i2] = self.incoming_blocks[j1:j2]
        self._commit()

    def _deny(self, i1, i2, j1, j2):
        self.incoming_blocks[j1:j2] = self.original_blocks[i1:i2]
        self._commit()

    def _commit(self):
        original, incoming = self._texts()
        self.set_texts(original, incoming)
        self.resolved.emit(original, incoming)

    def center_line(self):
        """0-based original line nearest the vertical center of the viewport.

        Diffs make the page taller than the plain text, so this maps the pixel
        scroll position back to an original line number for cross-view sync.
        """
        if not self._rows:
            return 0
        center_y = self.verticalScrollBar().value() + self.viewport().height() / 2
        for widget, start, count in self._rows:
            top = widget.y()
            height = widget.height()
            if center_y < top + height:
                if count <= 0 or height <= 0:
                    return start
                frac = min(1.0, max(0.0, (center_y - top) / height))
                return start + int(frac * count)
        # Past the last row: clamp to its final line.
        widget, start, count = self._rows[-1]
        return start + max(0, count - 1)

    def scroll_to_center_line(self, line):
        """Scroll so original `line` (0-based) sits at the vertical center."""
        if not self._rows:
            return
        target_top = None
        for widget, start, count in self._rows:
            if count > 0 and start <= line < start + count:
                target_top = widget.y() + ((line - start) / count) * widget.height()
                break
            if start >= line:
                target_top = widget.y()
                break
        if target_top is None:
            target_top = self._rows[-1][0].y()
        self.verticalScrollBar().setValue(
            int(target_top - self.viewport().height() / 2))
