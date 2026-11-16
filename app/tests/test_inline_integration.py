from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.tests.test_native_editor import native_window, source_zip


def test_pending_review_blocks_direct_edits_until_resolved(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    state = view.document.native
    state.original = state.original.revise('Shared passage.\nThe car is red.')
    state.incoming = state.original.revise('Shared passage.\nThe car is blue.')
    view.refresh()

    before = state.original, state.incoming
    assert view.active_view() is view.inline_editor
    assert view.active_editor() is None
    assert view.inline_editor.set_source_position('original', 1)
    QTest.keyClicks(view.inline_editor, 'X')
    assert (state.original, state.incoming) == before

    view.review(0, True)
    assert view.active_editor() is view.editor
    assert state.original.text == 'Shared passage.\nThe car is blue.'
    view.undo_review()
    assert (state.original, state.incoming) == before
    assert view.active_editor() is None
    view.redo_review()
    assert view.active_editor() is view.editor


def test_ctrl_z_undoes_review_with_focus_on_sidebar(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    state = view.document.native
    state.original = state.original.revise('The car is red. The house is old.')
    state.incoming = state.original.revise('The car is blue. The house is new.')
    view.refresh()
    original = state.original
    view.review(0, True)
    assert state.original != original

    native_window.show()
    native_window.activateWindow()
    button = view.diff_view.decision_buttons[0]
    button.setFocus()
    QApplication.processEvents()
    assert button.hasFocus()
    QTest.keyClick(button, Qt.Key_Z, Qt.ControlModifier)
    assert state.original == original


def test_unmatched_speaker_marks_only_the_label_and_keeps_the_diff(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    state = view.document.native
    state.original = state.original.revise('     A    Correct.\n     THE WITNESS: I read the contract.')
    state.incoming = state.original
    view.receive(state.original.text.replace('A    Correct.', 'SPEAKER 4:  Correct.'), [])
    view.diff_view.filter_speaker('SPEAKER 4')

    cursor = QTextCursor(view.inline_editor.document())

    def color_at(side, text, content):
        position = view.inline_editor.display_position(side, text.index(content))
        cursor.setPosition(position + 1)
        return cursor.charFormat().background().color().name()

    assert color_at('original', state.original.text, 'A    ') == '#f2aba7'
    assert color_at('incoming', state.incoming.text, 'SPEAKER 4') == '#ffe08a'
    assert color_at('incoming', state.incoming.text, ':  Correct') == '#9edcb0'
    assert [mark.cursor.selectedText() for mark in view.incoming_editor.extraSelections()
            if mark.format.background().color().name() == '#ffe08a'] == ['SPEAKER 4']

    view.change_speaker_mapping('SPEAKER 4', 'THE WITNESS')
    assert color_at('incoming', state.incoming.text, 'THE WITNESS:  Correct') == '#9edcb0'
