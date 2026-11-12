"""Local WAV playback with native passage timing and non-editing highlighting."""
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QSignalBlocker
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QLabel, QSlider,
                               QTextEdit, QStyle, QStyleOptionSlider, QSizePolicy)

from app.src.casecat.anchors import utf16_index


def timestamp(milliseconds):
    seconds = max(0, milliseconds) // 1000
    return f'{seconds // 60}:{seconds % 60:02d}'


class SeekSlider(QSlider):
    """Seek to the clicked time, retaining handle dragging and keyboard control."""

    def _geometry(self):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
        return option, groove, handle

    def _seek_at(self, point):
        option, groove, handle = self._geometry()
        value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
            point.x() - self._grab_offset - groove.left(),
            max(1, groove.width() - handle.width()), option.upsideDown)
        self.setSliderPosition(value)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        _, _, handle = self._geometry()
        point = event.position().toPoint()
        self._grab_offset = point.x() - handle.left() if handle.contains(point) else handle.width() // 2
        self.setFocus(Qt.MouseFocusReason)
        self.setSliderDown(True)
        self._seek_at(point)
        event.accept()

    def mouseMoveEvent(self, event):
        if not self.isSliderDown():
            return super().mouseMoveEvent(event)
        self._seek_at(event.position().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self.isSliderDown():
            return super().mouseReleaseEvent(event)
        self._seek_at(event.position().toPoint())
        self.setSliderDown(False)
        event.accept()


class PlaybackBar(QWidget):
    def __init__(self, wav_path, timing, context, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.timing, self.context = timing, context
        self._highlight_editor = None
        self._pending_seek = None
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.play_button = QPushButton('Play')
        self.back_button = QPushButton('−5 s')
        self.back_button.setAccessibleName('Back 5 seconds')
        self.back_button.setToolTip('Back 5 seconds')
        self.forward_button = QPushButton('+5 s')
        self.forward_button.setAccessibleName('Forward 5 seconds')
        self.forward_button.setToolTip('Forward 5 seconds')
        self.slider = SeekSlider(Qt.Horizontal)
        self.slider.setAccessibleName('Audio position')
        self.slider.setToolTip('Click or drag to seek. Click the transcript to seek to its source passage.')
        self.clock = QLabel('0:00 / 0:00')
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        for widget in (self.back_button, self.play_button, self.forward_button, self.slider, self.clock):
            row.addWidget(widget)
        self.play_button.clicked.connect(self.toggle)
        self.back_button.clicked.connect(lambda: self.seek(self.player.position() - 5000))
        self.forward_button.clicked.connect(lambda: self.seek(self.player.position() + 5000))
        self.slider.valueChanged.connect(self.seek)
        self.player.positionChanged.connect(self.show_position)
        self.player.durationChanged.connect(self._duration)
        self.player.playbackStateChanged.connect(self._state)
        self.player.mediaStatusChanged.connect(self._loaded)
        self.player.errorOccurred.connect(lambda _error, message: self._error(message))
        self.player.setSource(QUrl.fromLocalFile(str(Path(wav_path).resolve())))

    def _duration(self, duration):
        self.slider.setRange(0, duration)
        self.show_position(self.player.position())

    def _state(self, state):
        self.play_button.setText('Pause' if state == QMediaPlayer.PlayingState else 'Play')

    def _loaded(self, status):
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and self._pending_seek is not None:
            position, self._pending_seek = self._pending_seek, None
            self.player.setPosition(position)

    def _error(self, message):
        print(f'Audio playback: {message}')
        self.clock.setText('Audio unavailable')
        self.clock.setToolTip(message)

    def cursor_position_ms(self):
        editor, revision = self.context()
        if editor is None or revision is None or self.timing is None:
            return None
        position = utf16_index(revision.text, editor.textCursor().position())
        return self.timing.position_ms(revision, position)

    def seek_from_cursor(self):
        position = self.cursor_position_ms()
        if position is None:
            return
        self.seek(position)

    def seek_passage(self, revision, position):
        if self.timing is not None:
            milliseconds = self.timing.position_ms(revision, position)
            if milliseconds is not None:
                self.seek(milliseconds)

    def seek(self, position):
        """Move the playback head without changing playing/paused state."""
        position = max(0, position)
        if self.player.duration() > 0:
            position = min(position, self.player.duration())
        self._pending_seek = position
        self.player.setPosition(position)
        if self.player.isSeekable():
            self._pending_seek = None

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self):
        self._pending_seek = None
        self.player.stop()
        self.clear_highlight()

    def clear_highlight(self):
        if self._highlight_editor is not None:
            self._highlight_editor.setExtraSelections([])
            self._highlight_editor = None

    def show_position(self, position):
        if not self.slider.isSliderDown():
            with QSignalBlocker(self.slider):
                self.slider.setValue(position)
        self.clock.setText(f'{timestamp(position)} / {timestamp(self.player.duration())}')
        editor, revision = self.context()
        self.clear_highlight()
        if editor is None or revision is None or self.timing is None:
            return
        passage = self.timing.range_at(revision, position)
        if passage is None:
            return
        start, end = passage
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(editor.document())
        selection.cursor.setPosition(len(revision.text[:start].encode('utf-16-le')) // 2)
        selection.cursor.setPosition(len(revision.text[:end].encode('utf-16-le')) // 2,
                                     QTextCursor.KeepAnchor)
        selection.format.setBackground(QColor(120, 165, 220, 85))
        editor.setExtraSelections([selection])
        self._highlight_editor = editor

    def hideEvent(self, event):
        self.stop()
        super().hideEvent(event)
