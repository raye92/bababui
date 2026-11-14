import importlib.util
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.src.casecat.anchors import AnchoredSpan, Revision
from app.src.native_editor import NativeTranscriptEditor
from app.src.suggestions import Suggestion


def revision(text):
    return Revision((AnchoredSpan('source', (0,), (), text),))


def comparison(before, after, ranges, bounds):
    original, incoming = revision(before), revision(after)
    edits = tuple(Suggestion(original, incoming, (span,)) for span in ranges)
    section = SimpleNamespace(original_range=bounds[:2], incoming_range=bounds[2:],
                              edit_indices=tuple(range(len(edits))))
    return SimpleNamespace(original=original, incoming=incoming, edits=edits,
                           sections=(section,))


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
    for side, word in [('original', 'red'), ('incoming', 'blue')]:
        position = view.display_position(side, getattr(model, side).text.index(word))
        cursor = QTextCursor(view.document())
        cursor.setPosition(position)
        cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
        assert cursor.charFormat().background().color() != cursor.blockFormat().background().color()
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
    model = SimpleNamespace(original=revision(text), incoming=revision(text), edits=(), sections=())
    view = widget(model)
    assert len(view.rows) > 1
    view.selectAll()
    QTest.keyClick(view, Qt.Key_C, Qt.ControlModifier)
    assert QApplication.clipboard().text() == text
    view.close()


def test_unicode_mapping_and_review_history_shortcuts():
    text = 'Intro 😀 text.\nTail.'
    model = SimpleNamespace(original=revision(text), incoming=revision(text), edits=(), sections=())
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
