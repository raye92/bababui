import importlib.util
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.src.casecat.anchors import AnchoredSpan, Revision
from app.src.native_editor import NativeTranscriptEditor
from app.src.review_model import ReviewModel, ReviewSection
from app.src.suggestions import Suggestion


def revision(text):
    return Revision((AnchoredSpan('source', (0,), (), text),))


def comparison(before, after, ranges, bounds):
    original, incoming = revision(before), revision(after)
    edits = tuple(Suggestion(original, incoming, (span,)) for span in ranges)
    section = ReviewSection(bounds[:2], bounds[2:], tuple(range(len(edits))))
    return ReviewModel(original, incoming, edits, (section,))


def widget(model):
    assert importlib.util.find_spec('app.src.inline_review') is not None, 'The inline comparison widget is missing.'
    from app.src.inline_review import InlineReviewEditor
    app = QApplication.instance() or QApplication([])
    original = NativeTranscriptEditor(QFont('Courier New', 12))
    incoming = NativeTranscriptEditor(QFont('Courier New', 12))
    original.setPlainText(model.original.text)
    incoming.setPlainText(model.incoming.text)
    view = InlineReviewEditor(QFont('Courier New', 12))
    view.set_source_editors(original, incoming)
    view.set_model(model)
    view.resize(1000, 700)
    view.show()
    app.processEvents()
    return view


def outlined_rows(view):
    view.clearFocus()
    image = view.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    rows = []
    cursor = QTextCursor(view.document())
    for row in view.rows:
        if row.kind == 'equal':
            continue
        cursor.setPosition(row.display_start)
        y = round(view.cursorRect(cursor).center().y() * scale)
        if 0 <= y < image.height():
            # Include the margin occupied by a paragraph-break marker.
            left = max(0, round((row.x - 16) * scale))
            right = min(image.width(), round((view._page_width - 2) * scale))
            if any(image.pixelColor(x, y).name() == '#000000' for x in range(left, right)):
                rows.append(row.text)
    return rows


def wording_model():
    before = 'Intro.\nThe red car is large.\nTail.'
    after = 'Intro.\nThe blue car is small.\nTail.'
    ranges = [(before.index('red'), before.index('red')+3,
               after.index('blue'), after.index('blue')+4),
              (before.index('large'), before.index('large')+5,
               after.index('small'), after.index('small')+5)]
    return comparison(before, after, ranges,
                      (7, before.index('Tail.'), 7, after.index('Tail.')))


def test_section_pairs_whole_passage_with_exact_independent_highlights():
    model = wording_model()
    view = widget(model)
    assert view.toPlainText().splitlines() == [
        'Intro.', 'The red car is large.', 'The blue car is small.', 'Tail.']
    assert [row.kind for row in view.rows] == ['equal', 'original', 'incoming', 'equal']
    for side, word, color in [('original', 'red', '#f2aba7'), ('incoming', 'blue', '#9edcb0')]:
        position = view.display_position(side, getattr(model, side).text.index(word))
        cursor = QTextCursor(view.document())
        cursor.setPosition(position)
        cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
        assert cursor.charFormat().background().color().name() == color
    view.focus_edit(1)
    assert view.source_position() == ('original', model.original.text.index('large'))
    assert model.original.text == 'Intro.\nThe red car is large.\nTail.'
    view.close()


def test_ghost_rows_expand_source_page_without_renumbering():
    before = '\n'.join(f'Paragraph {i}.' for i in range(30))
    after = before.replace('Paragraph 2.', 'A longer proposed paragraph.\nAnother proposed paragraph.')
    a, b = before.index('Paragraph 2.'), before.index('Paragraph 3.')
    c, d = after.index('A longer'), after.index('Paragraph 3.')
    view = widget(comparison(before, after, [(a, b, c, d)], (a, b, c, d)))
    numbered = [(row.page, row.number) for row in view.rows if row.number]
    assert numbered == [(line.page, line.number) for line in view.source_editors[0].page_lines()]
    assert all(row.number == 0 for row in view.rows if row.kind == 'incoming')
    assert view.pages[0].height > view.source_editors[0]._page_height
    assert view.pages[1].top == view.pages[0].height
    assert view.rows[-1].page == 2
    view.close()


def test_inline_review_is_read_only_even_on_unchanged_text():
    view = widget(wording_model())
    text = view.toPlainText()
    view.set_source_position('original', 1)
    QTest.keyClicks(view, 'X')
    QTest.keyClick(view, Qt.Key_Backspace)
    QApplication.clipboard().setText('replacement')
    view.selectAll()
    view.cut()
    view.paste()
    assert view.toPlainText() == text
    assert view.isReadOnly()
    view.close()


def test_copy_uses_source_text_across_visual_wraps():
    text = 'Word ' * 30 + 'end.'
    model = ReviewModel(revision(text), revision(text), (), ())
    view = widget(model)
    assert len(view.rows) > 1
    view.selectAll()
    QTest.keyClick(view, Qt.Key_C, Qt.ControlModifier)
    assert QApplication.clipboard().text() == text
    view.close()


def test_unicode_mapping_and_review_history_shortcuts():
    text = 'Intro 😀 text.\nTail.'
    model = ReviewModel(revision(text), revision(text), (), ())
    view = widget(model)
    position = text.index('text')
    view.set_source_position('original', position)
    assert view.source_position() == ('original', position)
    history = []
    view.history_requested.connect(history.append)
    QTest.keyClick(view, Qt.Key_Z, Qt.ControlModifier)
    QTest.keyClick(view, Qt.Key_Y, Qt.ControlModifier)
    assert history == [True, False]
    view.close()


def test_space_activates_playback_shortcut_on_unchanged_text():
    view = widget(wording_model())
    toggles = []
    shortcut = QShortcut(QKeySequence(Qt.Key_Space), view)
    shortcut.setContext(Qt.WidgetWithChildrenShortcut)
    shortcut.activated.connect(lambda: toggles.append(True))
    view.set_source_position('original', 1)
    view.activateWindow()
    view.setFocus()
    QApplication.processEvents()
    QTest.keyClick(view, Qt.Key_Space)
    assert toggles == [True]
    view.close()


def test_empty_side_has_visible_clickable_boundary_without_duplicate_context():
    model = comparison('Kept.', 'Added.\nKept.', [(0, 0, 0, 7)], (0, 0, 0, 7))
    view = widget(model)
    assert [row.kind for row in view.rows] == ['original', 'incoming', 'equal']
    assert view.toPlainText().count('Kept.') == 1
    assert hasattr(view, 'boundary_marks'), 'Empty ranges need a visible review target.'
    marker = next(mark for mark in view.boundary_marks if mark.side == 'original')
    selected = []
    view.selected.connect(selected.append)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.boundary_rect(marker).center().toPoint())
    assert selected == [0]
    assert [(row.page, row.number) for row in view.rows if row.number] == [(1, 1)]
    view.close()


def test_click_beside_insertion_marker_seeks_the_clicked_character():
    before, after = 'We would go.', "We wouldn't go."
    boundary = before.index(' go')
    model = comparison(before, after, [(boundary, boundary, boundary, boundary + 3)],
                       (0, len(before), 0, len(after)))
    view = widget(model)
    cursor = QTextCursor(view.document())
    cursor.setPosition(view.display_position('original', boundary))
    rect = view.cursorRect(cursor)
    activated = []
    view.source_activated.connect(lambda side, position: activated.append((side, position)))

    # Click the right half of the final letter in "would".
    QTest.mouseClick(view.viewport(), Qt.LeftButton,
                     pos=QPoint(rect.x() - 1, rect.center().y()))
    view.close()

    assert activated == [('original', boundary - 1)]


def test_unchanged_paragraph_context_is_shown_once_around_whole_paragraph_changes():
    from app.src.review_model import build_review
    for before, after, shared in [
            ('BY COUNSEL:\nQuestion.', 'EXAMINATION\nBY COUNSEL:\nQuestion.', 'BY COUNSEL:'),
            ('Gone.\nKept.', 'Kept.', 'Kept.'),
            ('First.\nSecond.', 'First.\n\nSecond.', 'Second.')]:
        view = widget(build_review(revision(before), revision(after)))
        assert view.toPlainText().count(shared) == 1
        assert any(row.kind == 'equal' and shared in row.text for row in view.rows)
        view.close()


def test_unchanged_wrapped_rows_are_shared_and_changed_row_pair_is_compact():
    from app.src.review_model import build_review
    before = ('The witness reviewed the report and the earlier testimony. ' * 3
              + 'Volume II, so the next question concerns the written account. '
              + 'The witness reviewed the report and the earlier testimony. ' * 3)
    after = before.replace('Volume II, so', 'Volume 2. So')
    view = widget(build_review(revision(before), revision(after)))
    old_lines = view.source_editors[0].page_lines()
    assert len(old_lines) >= 7
    assert len([row for row in view.rows if row.kind == 'original']) < len(old_lines)
    assert sum(row.text == view.rows[0].text for row in view.rows) == 1
    changed = [row for row in view.rows if row.kind != 'equal']
    last_old = next(row for row in reversed(changed) if row.kind == 'original')
    first_new = next(row for row in changed if row.kind == 'incoming')
    assert first_new.y-last_old.y < view.source_editors[0]._line_height
    assert first_new.y-last_old.y == last_old.pitch
    assert [(row.page, row.number) for row in view.rows if row.number] == [
        (line.page, line.number) for line in old_lines]
    for row in view.rows:
        layout = view.document().findBlock(row.display_start).layout()
        # Qt rounds the root-frame margin to a physical pixel.
        assert abs(layout.position().y()+layout.lineAt(0).y()-row.y) < 0.5
    view.close()


def test_separate_changed_wrapped_rows_pair_next_to_their_local_incoming_rows():
    from app.src.review_model import build_review
    before = ('Opening testimony about this report. ' * 2 + 'The red vehicle. '
              + 'Further testimony explains the same report. ' * 4 + 'A large truck. '
              + 'Closing testimony about this report. ' * 3)
    after = before.replace('red', 'tan').replace('large', 'small')
    view = widget(build_review(revision(before), revision(after)))
    groups = []
    for row in view.rows:
        if row.kind == 'equal':
            continue
        if not groups or groups[-1][0] != row.section:
            groups.append((row.section, []))
        groups[-1][1].append(row.kind)
    assert len(groups) == 2
    assert all(kinds == ['original', 'incoming'] for _, kinds in groups)
    view.close()


def test_adjacent_changes_show_each_removal_with_its_own_addition():
    old = 'Opening.\nFirst removed line.\n\nSecond removed line.\nThe car is red.\nClosing.'
    new = 'Opening.\nFirst added line.\nSecond added line.\nThe car is blue.\nClosing.'
    a, c = old.index('First'), new.index('First')
    b, d = old.index('The car'), new.index('The car')
    ranges = [(a, b, c, d), (old.index('red'), old.index('red') + 3,
                               new.index('blue'), new.index('blue') + 4)]
    view = widget(comparison(old, new, ranges, (a, len(old), c, len(new))))
    assert [(row.kind, row.text) for row in view.rows if row.kind != 'equal'] == [
        ('original', 'First removed line.'), ('original', ''), ('original', 'Second removed line.'),
        ('incoming', 'First added line.'), ('incoming', 'Second added line.'),
        ('original', 'The car is red.'), ('incoming', 'The car is blue.')]
    view.focus_edit(0)
    assert outlined_rows(view) == ['First removed line.', 'Second removed line.',
                                   'First added line.', 'Second added line.']
    view.focus_edit(1)
    assert outlined_rows(view) == ['The car is red.', 'The car is blue.']
    view.close()


@pytest.mark.parametrize('reverse', [False, True], ids=['forward', 'reverse'])
@pytest.mark.parametrize('original,proposal,old_rows,new_rows,context_only', [
    ('The car.', 'Today The car.', ['The car.'], ['Today The car.'], None),
    ('The car.', 'The car. Today.', ['The car.'], ['The car. Today.'], None),
    ('Kept.', 'Kept.\nAdded.', [''], ['Added.'], None),
    ('Kept.', 'Added.\nKept.', [''], ['Added.'], None),
    ('First.\nSecond.', 'First. Second.', ['First.', 'Second.'], ['First. Second.'], 'Second.'),
    ('First.\nSecond.', 'First.Second.', ['First.', 'Second.'], ['First.Second.'], 'Second.'),
    ('Kept.\n', 'Kept.\nAdded.', [''], ['Added.'], None),
])
def test_model_and_editor_pair_complete_affected_rows(original, proposal, old_rows, new_rows, context_only, reverse):
    from app.src.review_model import build_review
    if reverse:
        original, proposal, old_rows, new_rows = proposal, original, new_rows, old_rows
    model = build_review(revision(original), revision(proposal))
    view = widget(model)
    assert [row.text for row in view.rows if row.kind == 'original'] == old_rows
    assert [row.text for row in view.rows if row.kind == 'incoming'] == new_rows
    section, = model.sections
    assert original[slice(*section.original_range)].strip('\n') == '\n'.join(old_rows)
    assert proposal[slice(*section.incoming_range)].strip('\n') == '\n'.join(new_rows)
    view.focus_edit(0)
    assert outlined_rows(view) == [text for text in old_rows + new_rows if text != context_only]
    view.close()


def test_adjacent_edits_stay_paired_when_a_replacement_moves_the_wrap():
    from app.src.review_model import build_review

    old = ('The witness inspected a red car after a scheduled meeting near the old house '
           'on Sunday morning. Other witnesses agreed with that account.')
    new = old.replace('red', 'bright emerald green').replace('old', 'modern')
    model = build_review(revision(old), revision(new))
    view = widget(model)
    pairs = []
    for index in range(len(model.edits)):
        rows = [row for row in view.rows if index in row.edit_indices]
        pairs.append(rows)
        view.focus_edit(index)
        focused = outlined_rows(view)
        for side in ('original', 'incoming'):
            assert any(r.text in focused for r in rows if r.kind == side)
    assert len(pairs) == 2
    assert 'red' in pairs[0][0].text and any('green' in r.text for r in pairs[0] if r.kind == 'incoming')
    assert 'old' in pairs[1][0].text and any('modern' in r.text for r in pairs[1] if r.kind == 'incoming')
    assert pairs[0][-1].display_start < pairs[1][0].display_start
    view.close()


def test_paired_paragraphs_stay_together_inside_one_multiline_decision():
    from app.src.review_model import build_review
    from app.src.suggestions import resolve

    old = revision('The sign says red.\nBlue marks the next gate.')
    new = revision('The sign says orange.\nGreen marks the next gate.')
    model = build_review(old, new)
    edit, = model.edits
    view = widget(model)
    assert [s.edit_indices for s in model.sections] == [(0,), (0,)]
    assert [(r.kind, r.text) for r in view.rows] == [
        ('original', 'The sign says red.'), ('incoming', 'The sign says orange.'),
        ('original', 'Blue marks the next gate.'), ('incoming', 'Green marks the next gate.')]
    view.focus_edit(0)
    assert outlined_rows(view) == [r.text for r in view.rows]
    assert resolve(old, new, edit, True)[0].text == new.text
    assert resolve(old, new, edit, False)[1].text == old.text
    view.close()


@pytest.mark.parametrize('add', [True, False], ids=['insert', 'delete'])
def test_selecting_a_trailing_paragraph_break_finds_its_empty_row(add):
    from app.src.review_model import build_review
    text = 'Opening.\nLast line.'
    before, after = (text, text + '\n') if add else (text + '\n', text)
    view = widget(build_review(revision(before), revision(after)))
    view.set_source_position('original', 0)
    view.focus_edit(0)
    side = 'incoming' if add else 'original'
    row = next(row for row in view.rows if row.kind == side)
    assert view.textCursor().position() == row.display_start
    assert any(mark.display_position == row.display_start and mark.side == side and not mark.empty
               for mark in view.boundary_marks)
    view.close()


def test_selected_word_owns_its_first_wrapped_row_and_scrolls_into_view():
    from app.src.review_model import build_review
    prefix = 'Kept.\n' * 55
    word = 'a' * 85
    model = build_review(revision(prefix + word + 'B'), revision(prefix + word + 'C'))
    view = widget(model)
    view.verticalScrollBar().setValue(0)
    view.focus_edit(0)
    originals = [r for r in view.rows if r.kind == 'original']
    assert len(originals) >= 2 and originals[0].source_start == len(prefix)
    assert view.textCursor().position() == originals[0].display_start
    assert view.verticalScrollBar().value() > 0
    assert originals[0].text in outlined_rows(view)
    view.close()


@pytest.mark.parametrize('index,selected', [(0, ('red', 'blue')), (1, ('large', 'small'))])
def test_black_border_follows_only_the_selected_words(index, selected):
    view = widget(wording_model())
    view.highlight_edit(index)
    image = view.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    for word in ('red', 'blue', 'large', 'small'):
        cursor = view.document().find(word)
        last = view.cursorRect(cursor)
        cursor.setPosition(cursor.selectionStart())
        first = view.cursorRect(cursor)
        left, right = (round(rect.x() * scale) for rect in (first, last))
        top, bottom = round(first.top() * scale), round((first.bottom() + 1) * scale)
        middle_x, middle_y = (left + right) // 2, (top + bottom) // 2
        for x, y, dx, dy in ((left, middle_y, 1, 0), (right, middle_y, 1, 0),
                             (middle_x, top, 0, 1), (middle_x, bottom, 0, 1)):
            tolerance = round(2 * scale)
            black = any(image.pixelColor(x + dx * i, y + dy * i).name() == '#000000'
                        for i in range(-tolerance, tolerance + 1))
            assert black == (word in selected), (word, x, y)
    assert not any(mark.format.fontUnderline() for mark in view.extraSelections())
    view.close()


def test_four_pixel_outline_grows_outward_and_preserves_the_shared_edge():
    view = widget(wording_model())
    view.clearFocus()
    view.highlight_edit(0)
    image = view.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    cursor = view.document().find('red')
    block = cursor.block()
    line = block.layout().lineAt(0)
    y = round(view.cursorRect(cursor).center().y() * scale)
    for pos, outward in ((cursor.selectionStart(), -1), (cursor.selectionEnd(), 1)):
        edge = block.layout().position().x() + line.cursorToX(pos - block.position())[0]
        pixels = [x for x in range(round((edge - 5) * scale), round((edge + 5) * scale))
                  if image.pixelColor(x, y).name() == '#000000']
        assert abs(len(pixels) - 4 * scale) < 1
        center = (pixels[0] + pixels[-1] + 1) / 2
        assert center == pytest.approx((edge + outward) * scale, abs=0.51)
    # At the shared red/green edge the old one-pixel inset on each side remains.
    cursor.setPosition(cursor.selectionStart())
    x = round((view.cursorRect(cursor).x() + 5) * scale)
    shared = view.cursorRect(view.document().find('blue')).top()
    ink = sum(image.pixelColor(x, y).name() == '#000000'
              for y in range(round((shared - 4) * scale), round((shared + 4) * scale)))
    assert abs(ink - 2 * scale) < 1
    view.close()


def test_consecutive_comparisons_have_one_blank_line_between_pairs():
    from app.src.review_model import build_review
    original = revision('The car is red.\nThe house is old.\nShared testimony.')
    incoming = revision('The car is blue.\nThe house is new.\nShared testimony.')
    view = widget(build_review(original, incoming))
    a, b, c, d, shared = view.rows
    assert [r.kind for r in view.rows] == ['original', 'incoming', 'original', 'incoming', 'equal']
    assert b.y - a.y == pytest.approx(a.pitch, abs=1)
    assert c.y - (b.y + b.pitch) == pytest.approx(b.pitch, abs=1)
    assert d.y - c.y == pytest.approx(c.pitch, abs=1)
    assert shared.y - d.y == pytest.approx(d.pitch, abs=1)
    assert [line.number for line in view.page_lines()] == [1, 2, 3]
    assert view.document().blockCount() == 5
    view.close()


def test_selected_outline_closes_over_adjacent_highlights():
    old, new = 'A muchlongerword, old.', 'A bit, new.'
    model = comparison(old, new, [(2, old.index(','), 2, new.index(',')),
                                  (old.index('old'), len(old) - 1, new.index('new'), len(new) - 1)],
                       (0, len(old), 0, len(new)))
    view = widget(model)
    view.highlight_edit(0)
    cursor = view.document().find('muchlongerword')
    last = view.cursorRect(cursor)
    cursor.setPosition(cursor.selectionStart())
    first = view.cursorRect(cursor)
    image = view.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    bottom = round((first.bottom() + 1) * scale)
    tolerance = round(2 * scale)
    for x in range(round((first.x() + 2) * scale), round((last.x() - 2) * scale)):
        assert any(image.pixelColor(x, y).name() == '#000000'
                   for y in range(bottom - tolerance, bottom + tolerance + 1)), x
    view.close()


def test_selected_tab_is_boxed_at_its_actual_tab_stop():
    old, new = '😀A\tZ tail.', '😀A Z tail.'
    view = widget(comparison(old, new, [(2, 3, 2, 3)], (0, len(old), 0, len(new))))
    view.highlight_edit(0)
    cursor = view.document().find('\t')
    assert cursor.hasSelection()
    last = view.cursorRect(cursor)
    cursor.setPosition(cursor.selectionStart())
    first = view.cursorRect(cursor)
    image = view.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    y = round(first.center().y() * scale)
    for edge in (first.x(), last.x()):
        assert any(image.pixelColor(x, y).name() == '#000000'
                   for x in range(round((edge - 2) * scale), round((edge + 2) * scale) + 1))
    assert image.pixelColor(round((first.x() + last.x()) * scale / 2), y).name() == '#f2aba7'
    view.close()


def test_native_paragraph_space_inside_a_comparison_stays_blank():
    old, new = 'First original line.\nSecond original line.', 'Replacement.'
    span = (0, len(old), 0, len(new))
    model = comparison(old, new, [span], span)
    view = widget(model)
    source = view.source_editors[0].document()
    cursor = QTextCursor(source.findBlockByNumber(1))
    fmt = cursor.blockFormat()
    fmt.setTopMargin(60)
    cursor.setBlockFormat(fmt)
    view.set_model(model)
    first, second, _ = view.rows
    assert first.section == second.section
    assert second.y - first.y - first.pitch == pytest.approx(60, abs=1)
    view.highlight_edit(0)
    image = view.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    middle = round((first.y + first.pitch + 30 - view.verticalScrollBar().value()) * scale)
    assert image.pixelColor(round((first.x + 10) * scale), middle) == image.pixelColor(
        round((first.x - 20) * scale), middle)
    view.close()


def test_scrolling_scaled_rows_keeps_the_two_diff_backgrounds_in_contact():
    from app.src.inline_review import InlineReviewEditor
    from app.src.native_editor import _paper_font
    from app.src.page_view import PageView
    from app.src.review_model import build_review

    app = QApplication.instance() or QApplication([])
    # The nonbreaking hyphen uses a fallback font with a different ascent on Windows.
    model = build_review(revision('A record\u2011keeping example.'), revision('A filing example.'))
    view = InlineReviewEditor(_paper_font('Courier New', 18))
    view.set_model(model)
    page = PageView(view)
    page.setAttribute(Qt.WA_DontShowOnScreen)
    page.resize(610, 240)
    page.show()
    app.processEvents()
    a, b = view.rows
    for offset in range(12):
        view.verticalScrollBar().setValue(offset)
        app.processEvents()
        image = page.viewport().grab().toImage()
        scale = image.devicePixelRatio()
        x = round(page.mapFromScene(view._page_width - 30, 0).x() * scale)
        top, bottom = [round(page.mapFromScene(0, r.y + r.pitch/2 - offset).y() * scale)
                       for r in (a, b)]
        colors = {image.pixelColor(x, y).name() for y in range(top, bottom + 1)}
        assert colors == {'#fbe9e7', '#e7f5ea'}, (offset, colors)
    page.close()


def test_review_formats_rows_without_relaying_out_each_row():
    from app.src.inline_review import InlineReviewEditor
    from app.src.review_model import build_review

    app = QApplication.instance() or QApplication([])
    view = InlineReviewEditor(QFont('Courier New', 12))
    before = revision(''.join(f'Page {i} discusses the written account.\n' for i in range(100)))
    model = build_review(before, before.replace(0, 4, 'Volume'))
    sizes = []
    view.document().documentLayout().documentSizeChanged.connect(sizes.append)

    view.set_model(model)

    assert len(view.rows) >= 100
    assert len(sizes) < len(view.rows) // 4
    assert 'Volume 0 discusses' in view.toPlainText()
    view.close()
