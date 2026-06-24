import difflib
from PySide6.QtWidgets import (QScrollArea, QWidget, QFrame, QPlainTextEdit,
                               QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy)
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QFont, QPainter, QColor

# Width of the existing left margin shared by the +/- markers and the line
# numbers — reused here rather than adding a new gutter.
GUTTER_WIDTH = 24


class _LineNumberArea(QWidget):
    """Paints line numbers into the editor's existing left viewport margin."""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def paintEvent(self, event):
        self._editor._paint_line_numbers(event)


class _EqualBlock(QPlainTextEdit):
    """Frameless, auto-height editable widget for unchanged diff lines.

    Edits here update both original and incoming (they stay identical in equal
    regions), so the diff structure is preserved and no new variance is created.
    """

    # Emitted on every keystroke — caller saves to disk without re-rendering.
    saved = Signal(list)
    # Emitted on focusOut when the line count changed — caller must re-render
    # so hunk indices stay accurate.
    needs_rerender = Signal()

    def __init__(self, lines, font, start_line, parent=None):
        super().__init__(parent)
        self._initial_count = len(lines)
        # 1-based number of the first line in this block within the transcript.
        self._start_line = start_line

        self.setFont(font)
        self.setFrameShape(QFrame.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Left padding aligns text with the content column of the diff rows
        # (which each start with a 24 px marker label).
        self.setViewportMargins(GUTTER_WIDTH, 0, 0, 0)
        self.document().setDocumentMargin(0)

        # Line numbers live in the existing left margin (no new gutter).
        self._line_area = _LineNumberArea(self)
        self.updateRequest.connect(self._on_update_request)

        self._suppress = True
        self.setPlainText('\n'.join(lines))
        self._suppress = False

        self._sync_height()
        self.document().contentsChanged.connect(self._on_changed)

    def _on_changed(self):
        if self._suppress:
            return
        self._sync_height()
        self.saved.emit(self.toPlainText().split('\n'))

    def _sync_height(self):
        fm = self.fontMetrics()
        lines = max(1, self.document().blockCount())
        self.setFixedHeight(fm.lineSpacing() * lines + 6)

    def _on_update_request(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(), GUTTER_WIDTH, cr.height()))

    def _paint_line_numbers(self, event):
        painter = QPainter(self._line_area)
        painter.setPen(QColor('#8a8f98'))
        # Slightly smaller than the text so multi-digit numbers fit the margin.
        number_font = QFont(self.font())
        number_font.setPointSizeF(max(7.0, self.font().pointSizeF() - 2))
        painter.setFont(number_font)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        offset = self.contentOffset()
        top = self.blockBoundingGeometry(block).translated(offset).top()
        bottom = top + self.blockBoundingRect(block).height()
        line_height = int(self.fontMetrics().height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(self._start_line + block_number)
                painter.drawText(0, int(top), GUTTER_WIDTH, line_height,
                                 Qt.AlignHCenter | Qt.AlignVCenter, number)
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def wheelEvent(self, event):
        # Unchanged blocks are not scrollable: let the wheel fall through to
        # the outer diff scroll area so the whole page scrolls instead.
        event.ignore()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_height()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # If lines were added/removed the cached hunk indices are stale.
        if self.document().blockCount() != self._initial_count:
            self.needs_rerender.emit()


class DiffView(QScrollArea):
    """Inline diff between the original text and the incoming text.

    Insertions (in incoming, missing from original) are highlighted green.
    Deletions (in original, missing from incoming) are highlighted red.
    Every change hunk carries Accept / Deny buttons that reconcile the two
    sides line-for-line, mirroring how Cursor / GitHub / VS Code present diffs.
    """

    # Emitted with (new_original_text, new_incoming_text) after each resolution.
    resolved = Signal(str, str)
    # Emitted during equal-block live edits — caller saves to disk only, no
    # re-render (cursor must stay in place while the user is typing).
    autosaved = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)

        self._mono = QFont("Courier New", 12)
        self._mono.setStyleHint(QFont.Monospace)

        self.original_lines = []
        self.incoming_lines = []

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setWidget(self._container)

    def set_texts(self, original_text, incoming_text):
        """Load both sides and render the inline diff."""
        self.original_lines = original_text.split('\n')
        self.incoming_lines = incoming_text.split('\n')
        self._render()

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render(self):
        self._clear()

        matcher = difflib.SequenceMatcher(
            None, self.original_lines, self.incoming_lines, autojunk=False)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                self._layout.addWidget(
                    self._make_equal_block(self.original_lines[i1:i2], i1, i2, j1, j2))
            else:
                self._layout.addWidget(self._make_hunk(tag, i1, i2, j1, j2))

        self._layout.addStretch(1)

    def _make_equal_block(self, lines, orig_i1, orig_i2, inc_j1, inc_j2):
        """Editable block for unchanged lines — no truncation, full scroll."""
        # Line numbers reflect the 1-based position within the original text.
        block = _EqualBlock(lines, self._mono, orig_i1 + 1)

        def on_saved(new_lines, oi1=orig_i1, oi2=orig_i2, ij1=inc_j1, ij2=inc_j2):
            # Equal lines stay equal: mirror the edit to both sides.
            self.original_lines = (self.original_lines[:oi1]
                                   + new_lines
                                   + self.original_lines[oi2:])
            self.incoming_lines = (self.incoming_lines[:ij1]
                                   + new_lines
                                   + self.incoming_lines[ij2:])
            self.autosaved.emit('\n'.join(self.original_lines),
                                '\n'.join(self.incoming_lines))

        block.saved.connect(on_saved)
        # Re-render when focusOut detects a line-count change so hunk indices
        # stay accurate before the user can click Accept / Deny.
        block.needs_rerender.connect(self._render)
        return block

    def _make_line_row(self, text, kind):
        if kind == 'delete':
            bg = '#ffd7d5'
            fg = '#82071e'
            mark = '\u2212'
        elif kind == 'insert':
            bg = '#ccffd8'
            fg = '#116329'
            mark = '+'
        else:
            # Equal lines: no background tint, no forced text color — inherit
            # whatever the palette provides so they look identical to the editor.
            bg = None
            fg = None
            mark = ' '

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        marker = QLabel(mark)
        marker.setFont(self._mono)
        marker.setFixedWidth(24)
        marker.setAlignment(Qt.AlignCenter)
        if bg:
            marker.setStyleSheet(f"background-color:{bg}; color:{fg};")

        # An empty string would collapse the row height, so keep a space.
        content = QLabel(text if text != '' else ' ')
        content.setFont(self._mono)
        content.setTextFormat(Qt.PlainText)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if bg:
            content.setStyleSheet(f"background-color:{bg}; color:{fg};")

        h.addWidget(marker)
        h.addWidget(content)
        return row

    def _make_hunk(self, tag, i1, i2, j1, j2):
        # No border or margin — the block sits flush in the document flow so
        # surrounding equal lines are not pushed away visually.
        block = QWidget()
        v = QVBoxLayout(block)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Red side: lines removed relative to incoming.
        for line in self.original_lines[i1:i2]:
            v.addWidget(self._make_line_row(line, 'delete'))
        # Green side: lines added by incoming.
        for line in self.incoming_lines[j1:j2]:
            v.addWidget(self._make_line_row(line, 'insert'))

        # Inline action bar — sits directly below the highlighted lines,
        # no surrounding box so it flows with the rest of the content.
        bar = QWidget()
        bar.setStyleSheet("background:#f6f8fa;")
        h = QHBoxLayout(bar)
        h.setContentsMargins(28, 3, 8, 3)
        h.setSpacing(6)

        caption = QLabel("Incoming change")
        caption.setStyleSheet("color:#57606a; font-size:11px;")

        accept = QPushButton("\u2713 Accept")
        accept.setCursor(Qt.PointingHandCursor)
        accept.setFixedHeight(22)
        accept.setStyleSheet(
            "border:none; background:#1f883d; color:white;"
            " padding:0 10px; border-radius:3px; font-size:11px;")
        accept.clicked.connect(
            lambda _=False, a=i1, b=i2, c=j1, d=j2: self._accept(a, b, c, d))

        deny = QPushButton("\u2717 Deny")
        deny.setCursor(Qt.PointingHandCursor)
        deny.setFixedHeight(22)
        deny.setStyleSheet(
            "border:none; background:#cf222e; color:white;"
            " padding:0 10px; border-radius:3px; font-size:11px;")
        deny.clicked.connect(
            lambda _=False, a=i1, b=i2, c=j1, d=j2: self._deny(a, b, c, d))

        h.addWidget(caption)
        h.addStretch(1)
        h.addWidget(accept)
        h.addWidget(deny)
        v.addWidget(bar)

        return block

    def _accept(self, i1, i2, j1, j2):
        # Take the incoming version for this region into the original.
        self.original_lines = (self.original_lines[:i1]
                               + self.incoming_lines[j1:j2]
                               + self.original_lines[i2:])
        self._commit()

    def _deny(self, i1, i2, j1, j2):
        # Keep the original version; roll the incoming side back to match it.
        self.incoming_lines = (self.incoming_lines[:j1]
                               + self.original_lines[i1:i2]
                               + self.incoming_lines[j2:])
        self._commit()

    def _commit(self):
        self.resolved.emit('\n'.join(self.original_lines),
                           '\n'.join(self.incoming_lines))
        self._render()
