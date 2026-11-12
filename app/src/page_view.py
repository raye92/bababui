"""Scale the editor surface without changing native page geometry or text."""
import math
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QFrame


class PageView(QGraphicsView):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setScene(QGraphicsScene(self))
        self.proxy = self.scene().addWidget(editor)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setBackgroundBrush(editor.palette().base())

    def fit_page(self):
        width = math.ceil(self.editor._page_width) + 2*self.editor.frameWidth() + self.editor.verticalScrollBar().sizeHint().width()
        scale = min(1., max(1, self.viewport().width()) / width)
        height = max(1, math.floor(self.viewport().height()/scale))
        self.editor.resize(width, height)
        self.setSceneRect(0, 0, width, height)
        self.resetTransform()
        self.scale(scale, scale)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_page()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.fit_page)
