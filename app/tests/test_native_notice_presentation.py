"""Native notice controls, using a short synthetic reporter cover."""
import os
from pathlib import Path
import struct

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QMimeData, QRect, Qt
from PySide6.QtGui import QFont, QFontDatabase, QTextCursor
from PySide6.QtWidgets import QApplication

from app.src.casecat.archive import inspect_archive
from app.src.casecat.caption import BODY_DIVIDER
from app.src.casecat.codec import load_job
from app.src.casecat.cover import BOARD, _stock_layout
from app.src.inline_review import InlineReviewEditor
from app.src.native_editor import NativeTranscriptEditor
from app.src.review_model import ReviewModel
from app.tests.test_native_casecat import job_files, zip_bytes


@pytest.fixture(autouse=True)
def notice_font():
    app = QApplication.instance() or QApplication([])
    courier = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/cour.ttf'
    font_id = -1
    if not QFontDatabase.families() and courier.is_file():
        font_id = QFontDatabase.addApplicationFont(str(courier))
    yield
    if font_id >= 0:
        QFontDatabase.removeApplicationFont(font_id)


def native_editor(stream):
    app = QApplication.instance() or QApplication([])
    files = job_files(words=('',), audio=False)
    native = bytearray(files['jobs/example.sgngl']) + stream
    struct.pack_into('<I', native, 536, len(native) - 1024)
    layout = _stock_layout()
    struct.pack_into('<II', native, 540, len(native), len(layout))
    struct.pack_into('<I', native, 624, 1)
    files['jobs/example.sgngl'] = native + layout
    bundle = inspect_archive(zip_bytes(files))
    job = load_job(bundle, bundle.jobs[0])
    editor = NativeTranscriptEditor(QFont('Courier New', 12))
    editor.set_native_source(bundle, job)
    editor.setPlainText(job.text)
    return app, editor, job


def test_literal_nonbreaking_space_preserves_native_formatting_and_editor_text():
    app, editor, job = native_editor(b'\x16\x07\x00CAPTION\x16\x08\x00Firm\xa0name and hard\x01space.')
    assert editor.document().firstBlock().blockFormat().alignment() == Qt.AlignHCenter
    assert editor.toPlainText() == job.text == 'CAPTION\nFirm\xa0name and hard space.'
    editor.selectAll()
    assert editor.createMimeDataFromSelection().text() == job.text
    cursor = QTextCursor(editor.document())
    cursor.insertText('X')
    assert editor.toPlainText() == 'X' + job.text
    editor.undo()
    assert editor.toPlainText() == job.text
    pos = job.text.index(' space.') + 1
    cursor.setPosition(pos)
    editor.setTextCursor(cursor)
    pasted = QMimeData()
    pasted.setText('\xa0')
    editor.insertFromMimeData(pasted)
    assert editor.toPlainText() == job.text[:pos] + '\xa0' + job.text[pos:]
    editor.close()


def test_native_tabs_follow_the_same_ruler_in_the_editor_and_inline_review():
    app, editor, job = native_editor(b'\x16\x08\x00\t\t\t\tApplicant,\x16\x08\x00 \t\tvs.')
    inline = InlineReviewEditor(editor.font())
    inline.set_source_editors(editor, editor)
    inline.set_model(ReviewModel(job.revision, job.revision, (), ()))
    for view in (editor, inline):
        layout = view.document().documentLayout()
        layout.documentSize()
        for index, offset, twips in ((0, 4, 4320), (1, 3, 3600)):
            block = view.document().findBlockByNumber(index)
            x = layout.blockBoundingRect(block).left() + block.layout().lineAt(0).cursorToX(offset)[0]
            assert x == pytest.approx(twips * editor._twip_scale, abs=1)
    inline.close()
    editor.close()


def tabbed_cover():
    centered, new, same = b'\x16\x07\x00', b'\x16\x08\x00', b'\x16\xff\x00'
    board = BOARD.encode()
    title = (centered + board + centered + b'STATE OF CALIFORNIA' + new + b'\x12\x09' +
             same + new + b'PARTY,\tCASE NO.:  1234\x0a' +
             same + b'\t\t\t\tApplicant,' + same + new + b' \t\tvs.' + new +
             new + b'ENTITY, INC.,' + new + new + b' \t  \t\tDefendant.\x0a' +
             new + b'~' * 30 + new + new + same * 3 + b'\x12\x89' + new + centered + b'DEPOSITION OF')
    following = (b'\x0c' + centered + board + new + b'\x12\x09' + b'\x0c' +
                 centered + b'APPEARANCES' + same + same + b'FIRST FIRM' + same +
                 b'SUITE 12' + b'\x12\x89' + new + b'Stating a license number' + BODY_DIVIDER + b'Testimony')
    return title + following


def test_tabbed_caption_and_single_spaced_page_follow_the_numbered_grid():
    app, editor, job = native_editor(tabbed_cover())
    lines = editor.page_lines()
    for page, expected, label in ((1, 1, BOARD), (1, 2, 'STATE OF CALIFORNIA'),
                                  (1, 4, 'PARTY,'), (1, 5, 'Applicant,'), (1, 6, 'vs.'),
                                  (1, 7, 'ENTITY, INC.,'), (1, 8, 'Defendant.'), (1, 9, '~' * 30),
                                  (1, 13, 'DEPOSITION OF'), (3, 1, 'APPEARANCES'),
                                  (3, 2, 'FIRST FIRM'), (3, 2.5, 'SUITE 12')):
        line = next(row for row in lines if row.page == page and label.casefold() in row.text.casefold())
        y = (page - 1) * editor._page_height + editor._top + (expected - 1) * editor._line_height
        assert line.y == pytest.approx(y, abs=1), label
        if expected == int(expected):
            assert line.number == expected, label
    editor.close()


def test_unchanged_inline_cover_prints_one_gutter_number_per_full_line():
    app, editor, job = native_editor(tabbed_cover())
    inline = InlineReviewEditor(editor.font())
    inline.set_source_editors(editor, editor)
    inline.set_model(ReviewModel(job.revision, job.revision, (), ()))
    for view in (editor, inline):
        view.resize(940, 650)
        view.show()
        view.verticalScrollBar().setValue(0)
    app.processEvents()
    # Both views show the same ink throughout the gutter, including the space
    # between numbered lines occupied by the caption's half-line returns.
    gutter = QRect(40, round(editor._top), 89, round(9 * editor._line_height))
    assert inline.viewport().grab(gutter).toImage() == editor.viewport().grab(gutter).toImage()
    inline.close()
    editor.close()


def test_fractional_pixel_rounding_keeps_both_half_line_references_on_line_fourteen():
    app, editor, job = native_editor(tabbed_cover())
    for physical_row in (13.48, 13.50, 13.51):
        y = editor._top + (physical_row - 1) * editor._line_height
        assert editor.number_at_y(0, y, 22) == 14
    editor.close()


def test_automatic_cover_page_break_fits_the_last_half_line_and_starts_the_next_sheet_on_line_one():
    centered, new = b'\x16\x07\x00', b'\x16\x08\x00'
    board = centered + BOARD.encode()
    stream = (board + new + b'\x12\x09' + new * 47 + b'LAST HALF LINE' + board +
              new + b'\x12\x89Stating a license number' + BODY_DIVIDER + b'First answer.')
    app, editor, job = native_editor(stream)
    lines = editor.page_lines()
    last = next(row for row in lines if row.text == 'LAST HALF LINE')
    assert (last.page, last.y) == (1, pytest.approx(editor._top + 24.5 * editor._line_height, abs=1))
    next_board = [row for row in lines if row.text == BOARD][1]
    assert (next_board.page, next_board.y) == (2, pytest.approx(editor._page_height + editor._top, abs=1))
    editor.close()
