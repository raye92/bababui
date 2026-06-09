from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

DIFF_DELETE_BG = "#ffd7d5"
DIFF_DELETE_FG = "#82071e"
DIFF_INSERT_BG = "#ccffd8"
DIFF_INSERT_FG = "#116329"
ACTION_BAR_BG = "#f6f8fa"
CAPTION_COLOR = "#57606a"

ACCEPT_BUTTON_STYLE = (
    "border:none; background:#1f883d; color:white;"
    " padding:0 10px; border-radius:3px; font-size:11px;"
)
REJECT_BUTTON_STYLE = (
    "border:none; background:#cf222e; color:white;"
    " padding:0 10px; border-radius:3px; font-size:11px;"
)

MARKER_WIDTH = 24


def make_diff_row(text: str, kind: str, font: QFont) -> QWidget:
    if kind == "delete":
        bg = DIFF_DELETE_BG
        fg = DIFF_DELETE_FG
        mark = "\u2212"
    elif kind == "insert":
        bg = DIFF_INSERT_BG
        fg = DIFF_INSERT_FG
        mark = "+"
    else:
        bg = None
        fg = None
        mark = " "

    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    marker = QLabel(mark)
    marker.setFont(font)
    marker.setFixedWidth(MARKER_WIDTH)
    marker.setAlignment(Qt.AlignCenter)
    if bg:
        marker.setStyleSheet(f"background-color:{bg}; color:{fg};")

    content = QLabel(text if text else " ")
    content.setFont(font)
    content.setTextFormat(Qt.PlainText)
    content.setTextInteractionFlags(Qt.TextSelectableByMouse)
    content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    if bg:
        content.setStyleSheet(f"background-color:{bg}; color:{fg};")

    layout.addWidget(marker)
    layout.addWidget(content)
    return row


def make_action_button(label: str, variant: str) -> QPushButton:
    button = QPushButton(label)
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedHeight(22)
    if variant == "accept":
        button.setStyleSheet(ACCEPT_BUTTON_STYLE)
    else:
        button.setStyleSheet(REJECT_BUTTON_STYLE)
    return button
