from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pytest

from app.tests.test_native_editor import native_window, source_zip


@pytest.fixture
def audio_review(native_window, tmp_path):
    from app.src.documents import import_casecat
    from app.tests.test_native_audio import audio_archive

    view = native_window.add_document(import_casecat(audio_archive(tmp_path)))
    state = view.document.native
    state.original = state.original.revise('Alpha \nAn unchanged sentence.\nbeta \ngamma.')
    state.incoming = state.original
    view.receive(state.original.text.replace('Alpha', 'Orange').replace('beta', 'copper'), [])
    player = view.playback.player
    for _ in range(100):
        if player.isSeekable():
            break
        QTest.qWait(10)
    assert player.isSeekable()
    return view


@pytest.mark.parametrize('key, expected', [(Qt.Key_A, 'The car is blue.'), (Qt.Key_D, 'The car is red.')])
def test_review_decision_hotkeys_resolve_only_the_selected_suggestion(native_window, tmp_path, key, expected):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText('The car is red.\nThe house is old.')
    view.receive('The car is blue.\nThe house is new.', [])
    native_window.activateWindow()
    view.inline_editor.setFocus()
    QApplication.processEvents()

    QTest.keyClick(view.inline_editor, key)
    for _ in range(100):
        if not view.document.busy:
            break
        QTest.qWait(10)
    assert not view.document.busy
    assert view.document.original == f'{expected}\nThe house is old.'
    assert view.document.incoming == f'{expected}\nThe house is new.'


def test_w_replays_the_selected_edit_with_a_lead_in_even_after_the_caret_moves(native_window, audio_review):
    view = audio_review
    view.diff_view.select(1)
    view.inline_editor.set_source_position('original', 0)
    player = view.playback.player
    player.play()
    player.pause()
    player.setPosition(20000)
    native_window.activateWindow()
    view.inline_editor.setFocus()
    QApplication.processEvents()

    QTest.keyClick(view.inline_editor, Qt.Key_W)
    assert player.isPlaying()
    assert abs(player.position() - 10940) < 100
    assert view.inline_editor.source_position() == ('original', 0)


def test_s_uses_the_saved_forward_interval_and_preserves_pause(native_window, audio_review):
    view = audio_review
    player = view.playback.player
    native_window.activateWindow()
    view.inline_editor.setFocus()
    QApplication.processEvents()
    player.play()
    player.pause()
    player.setPosition(10000)

    QTest.keyClick(view.inline_editor, Qt.Key_S)
    assert player.position() == 15000 and not player.isPlaying()

    native_window.settings_btn.click()
    native_window.tabs.currentWidget().forward_seconds.setValue(9)
    native_window.tabs.setCurrentWidget(view)
    view.inline_editor.setFocus()
    QApplication.processEvents()
    player.setPosition(10000)
    QTest.keyClick(view.inline_editor, Qt.Key_S)
    assert player.position() == 19000 and not player.isPlaying()
    view.playback.forward_button.click()
    assert player.position() == 28000

    view.review(None, False)
    view.editor.setFocus()
    cursor = view.editor.textCursor()
    cursor.movePosition(QTextCursor.Start)
    view.editor.setTextCursor(cursor)
    QTest.keyClicks(view.editor, 'wasd')
    assert view.document.original.startswith('wasdAlpha')
    assert player.position() == 28000


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
