from PySide6.QtTest import QTest

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
