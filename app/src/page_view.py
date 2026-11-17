"""Scale the editor surface without changing native page geometry or text."""
import math
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
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
        self._scroll_timer = QTimer(self, interval=16)
        self._scroll_timer.timeout.connect(self._scroll_step)
        self._scroll_anchor_y = 0
        self._ignored_mouse_release = Qt.NoButton

    def fit_page(self):
        viewport = self.viewport().size()
        if viewport.isEmpty():
            return
        width = math.ceil(self.editor._page_width) + 2*self.editor.frameWidth() + self.editor.verticalScrollBar().sizeHint().width()
        scale = min(1., viewport.width() / width)
        height = math.floor(viewport.height() / scale)
        self.editor.resize(width, height)
        self.setSceneRect(0, 0, width, height)
        self.resetTransform()
        self.scale(scale, scale)

    def _scroll_step(self):
        offset = QCursor.pos().y() - self._scroll_anchor_y
        if abs(offset) <= 8:
            return
        speed = min(40, 1 + (abs(offset) - 9) // 8)
        step = round(math.copysign(speed, offset) / self.transform().m22())
        bar = self.editor.verticalScrollBar()
        bar.setValue(bar.value() + step)

    def _stop_autoscroll(self):
        if self._scroll_timer.isActive():
            self._scroll_timer.stop()
            self.viewport().unsetCursor()

    def mousePressEvent(self, event):
        button = event.button()
        if self._scroll_timer.isActive():
            self._stop_autoscroll()
        elif button == Qt.MiddleButton:
            bar = self.editor.verticalScrollBar()
            if bar.maximum() > bar.minimum():
                self.setFocus(Qt.MouseFocusReason)
                self._scroll_anchor_y = event.globalPosition().toPoint().y()
                self.viewport().setCursor(Qt.SizeVerCursor)
                self._scroll_timer.start()
        else:
            return super().mousePressEvent(event)
        self._ignored_mouse_release = button
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self._scroll_timer.isActive() or event.button() == Qt.MiddleButton:
            self.mousePressEvent(event)
        else:
            super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == self._ignored_mouse_release or event.button() == Qt.MiddleButton:
            self._ignored_mouse_release = Qt.NoButton
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._scroll_timer.isActive():
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._scroll_timer.isActive():
            self._stop_autoscroll()
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self._stop_autoscroll()
        super().focusOutEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_page()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.fit_page)

    def hideEvent(self, event):
        self._stop_autoscroll()
        self._ignored_mouse_release = Qt.NoButton
        super().hideEvent(event)
