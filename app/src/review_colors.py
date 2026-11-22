"""Highlight colors and outlines shared by transcript review views."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen

ADDITION_BACKGROUND = '#9edcb0'
FOCUS_OUTLINE = '#d4a000'
CHECK_BACKGROUND = '#ffe08a'
CHECK_FOREGROUND = '#513a08'


def draw_focus_outlines(painter, editor, rects):
    """Draw all four edges inside the visible width of the transcript."""
    pen = QPen(QColor(FOCUS_OUTLINE), 3, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin)
    painter.setPen(pen)
    inset = pen.widthF() / 2
    viewport = QRectF(editor.viewport().rect())
    x, y = editor.horizontalScrollBar().value(), editor.verticalScrollBar().value()
    for rect in rects:
        band = rect.translated(-x, -y)
        if band.intersects(viewport):
            band.setLeft(max(band.left(), viewport.left()))
            band.setRight(min(band.right(), viewport.right()))
            if band.width() <= pen.widthF():
                painter.fillRect(band, pen.color())
            else:
                painter.drawRect(band.adjusted(inset, inset, -inset, -inset))
