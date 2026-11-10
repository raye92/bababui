"""Tab headers double as WAV inputs only until audio is attached."""
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QEvent
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QTabBar, QMenu, QApplication, QToolButton, QSizePolicy, QTabWidget, QSizeGrip


class EditorTabs(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize_grip = QSizeGrip(self)

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            button = self.cornerWidget(Qt.TopRightCorner)
            if button:
                bar = self.tabBar().geometry()
                button.setGeometry(self.width() - bar.height(), bar.top(), bar.height(), bar.height())
            grip = getattr(self, 'resize_grip', None)
            if grip:
                size = grip.sizeHint()
                grip.setGeometry(self.width() - size.width(), self.height() - size.height(), size.width(), size.height())
                grip.raise_()
        return result


class NewTabButton(QToolButton):
    """Square corner control sized to the tab strip instead of a toolbar button."""
    def __init__(self, tabs):
        super().__init__(tabs)
        self.tabs = tabs
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setStyleSheet('QToolButton { border-radius: 0; padding: 0; margin: 0; }')

    def sizeHint(self):
        height = max(1, self.tabs.tabBar().sizeHint().height())
        return QSize(height, height)

    def minimumSizeHint(self):
        return self.sizeHint()


class AudioTabBar(QTabBar):
    attach_requested = Signal(int)
    wav_dropped = Signal(int, str)
    duplicate_requested = Signal(int)
    replace_requested = Signal(int)
    close_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setExpanding(False)
        self.setElideMode(Qt.ElideMiddle)
        self.setUsesScrollButtons(True)
        self._press_position = None

    def is_empty(self, index):
        info = self.tabData(index) or {}
        return index >= 0 and not info.get('wav_path')

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().text().color(), 1, Qt.DotLine))
        painter.setBrush(Qt.NoBrush)
        for index in range(self.count()):
            if self.is_empty(index):
                painter.drawRoundedRect(self.tabRect(index).adjusted(2, 2, -3, -3), 4, 4)

    def mousePressEvent(self, event):
        self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        index = self.tabAt(event.position().toPoint())
        moved = self._press_position is not None and (
            event.position().toPoint() - self._press_position).manhattanLength() >= QApplication.startDragDistance()
        super().mouseReleaseEvent(event)
        self._press_position = None
        if not moved and event.button() == Qt.LeftButton and self.is_empty(index):
            self.attach_requested.emit(index)

    def contextMenuEvent(self, event):
        index = self.tabAt(event.pos())
        if index < 0:
            return
        menu = QMenu(self)
        menu.addAction('Duplicate Tab', lambda: self.duplicate_requested.emit(index))
        replace = menu.addAction('Replace WAV', lambda: self.replace_requested.emit(index))
        close = menu.addAction('Close', lambda: self.close_requested.emit(index))
        busy = (self.tabData(index) or {}).get('busy', False)
        replace.setEnabled(not busy)
        close.setEnabled(not busy)
        menu.exec(event.globalPos())

    def _drop(self, event):
        index = self.tabAt(event.position().toPoint())
        urls = event.mimeData().urls()
        if self.is_empty(index) and not (self.tabData(index) or {}).get('busy') and len(urls) == 1 and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.is_file() and path.suffix.lower() == '.wav':
                return index, str(path)
        return None

    def dragEnterEvent(self, event):
        if self._drop(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event):
        result = self._drop(event)
        if result:
            self.wav_dropped.emit(*result)
            event.acceptProposedAction()
        else:
            event.ignore()
