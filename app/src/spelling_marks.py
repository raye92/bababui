"""Orange spelling-review underlines for the transcript views.

The underline is a view-only mark (a QTextEdit extra selection). It is drawn
after every other mark, so it stays visible over green, red and yellow edit
colors, and it is never written into the text, its formatting, the clipboard or
an export.
"""
from itertools import accumulate

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit

from app.src.review_colors import SPELLING_UNDERLINE
from shared.spelling_review import spelling_note, spelling_ranges


def utf16_offsets(text):
    """Qt position of each Python index in `text`, plus one past the end."""
    return list(accumulate((2 if ord(char) > 0xffff else 1 for char in text), initial=0))


def mark_format(fmt=None):
    fmt = QTextCharFormat() if fmt is None else fmt
    fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
    fmt.setUnderlineColor(QColor(SPELLING_UNDERLINE))
    return fmt


def selection(document, start, end):
    """One orange underline from Qt position `start` to `end`."""
    mark = QTextEdit.ExtraSelection()
    mark.cursor = QTextCursor(document)
    mark.cursor.setPosition(start)
    mark.cursor.setPosition(end, QTextCursor.KeepAnchor)
    mark_format(mark.format)
    return mark


def selections(document, text, record):
    """Orange underlines for every word to check in `text`, shown in `document`."""
    if not record:
        return []
    found = spelling_ranges(record, text)
    if not found:
        return []
    offsets = utf16_offsets(text)
    return [selection(document, offsets[start], offsets[end]) for start, end, _ in found]


def note_at(record, text, index):
    """The review note for the word at Python index `index` of `text`, or ''."""
    if not record:
        return ''
    for start, end, term in spelling_ranges(record, text):
        if start <= index < end or (index == end and start < end):
            return spelling_note(record, term)
    return ''
