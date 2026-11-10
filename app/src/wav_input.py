"""Centered toolbar control with native file browsing and WAV drops."""
from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QPushButton, QFileDialog


class WavInput(QPushButton):
    selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.setAcceptDrops(True)
        self.setMinimumWidth(160)
        self.setMinimumHeight(34)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName('WAV file input')
        self.setStyleSheet('QPushButton { border: 1px dashed #888; border-radius: 5px; padding: 6px; }')
        self.setText('Drop WAV here or click to browse')
        self.clicked.connect(self.browse)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose WAV recording',
            str(self.path.parent) if self.path else '', 'WAV audio (*.wav *.WAV)')
        if path:
            self.choose(path)

    def choose(self, path):
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != '.wav':
            return
        self.path = path
        self.setToolTip(str(path))
        self._update_text()
        self.selected.emit(str(path))

    def _update_text(self):
        if self.path:
            self.setText(self.fontMetrics().elidedText(self.path.name, Qt.ElideMiddle, max(80, self.width()-24)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_text()

    def _drop_path(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.is_file() and path.suffix.lower() == '.wav':
                return path
        return None

    def dragEnterEvent(self, event):
        if self.isEnabled() and self._drop_path(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self._drop_path(event)
        if self.isEnabled() and path:
            self.choose(path)
            event.acceptProposedAction()
        else:
            event.ignore()
