from copy import deepcopy
from threading import Event
from time import monotonic

import pytest
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QTextCursor, QTextFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from app.tests.test_inline_integration import audio_review
from app.tests.test_native_editor import native_window, source_zip
from app.tests.test_native_pages import review_layout_bundle


def preview_action(window):
    action = next((action for action in window.file_btn.menu().actions()
                   if action.text() == 'Preview Accept All'), None)
    assert action is not None, 'File menu needs a Preview Accept All action.'
    return action


def wait_until(condition, timeout=3):
    end = monotonic() + timeout
    while not condition() and monotonic() < end:
        QTest.qWait(10)
    assert condition()


def visible_preview(view):
    ordinary_views = (None, view.editor, view.incoming_editor, view.inline_editor)
    wait_until(lambda: view.active_view() not in ordinary_views
               and view.active_view().toPlainText() == view.document.incoming)
    return view.active_view()


def test_preview_matches_accepted_native_layout_and_highlights_only_changes(native_window):
    from app.src.documents import import_casecat

    bundle = review_layout_bundle(('Cover sheet.\n\x0c\x16\x07\x00',
                                   'INDEX\nFirst entry.\nRemove this line.\nSecond entry.'))
    doc = import_casecat(bundle)
    view = native_window.add_document(doc)
    proposal = (doc.original.replace('Cover sheet', 'Cover information')
                .replace('Remove this line.\n', '')
                .replace('First entry.', 'First entry includes ' + 'additional testimony ' * 7 + 'today.'))
    view.receive(proposal, [])
    doc.dirty = False
    before = doc.native.original, doc.native.incoming, deepcopy(doc.native.review), doc.dirty

    action = preview_action(native_window)
    assert action.isCheckable() and not action.isChecked()
    action.trigger()
    preview = visible_preview(view)
    assert preview.isReadOnly()
    assert (doc.native.original, doc.native.incoming, doc.native.review, doc.dirty) == before
    assert 'Remove this line.' not in preview.toPlainText()
    assert preview.document().pageCount() == 2
    lines = preview.page_lines()
    assert lines[2].text == 'INDEX' and lines[2].page == 2
    assert len(lines) > len(proposal.split('\n'))
    formats = [preview.document().findBlockByNumber(i).blockFormat()
               for i in range(preview.document().blockCount())]
    assert formats[2].alignment() == Qt.AlignHCenter
    assert all(fmt.background().style() == Qt.NoBrush for fmt in formats)
    marks = [mark for mark in preview.extraSelections() if mark.format.background().style() != Qt.NoBrush]
    assert 'information' in [mark.cursor.selectedText() for mark in marks]
    assert [mark.cursor.selectedText() for mark in marks
            if mark.format.background().color().name() == '#ffe08a'] == ['information']
    assert {mark.format.background().color().name() for mark in marks} == {'#9edcb0', '#ffe08a'}
    assert all(not mark.format.boolProperty(QTextFormat.FullWidthSelection) for mark in marks)

    accept_all = next(a for a in native_window.edit_btn.menu().actions() if a.text() == 'Accept All')
    accept_all.trigger()
    wait_until(lambda: not doc.busy)
    assert doc.original == proposal and not view.review_model.edits
    assert view.active_editor() is view.editor
    assert view.editor.page_lines() == lines
    assert [view.editor.document().findBlockByNumber(i).blockFormat()
            for i in range(view.editor.document().blockCount())] == formats
    assert action.isChecked()


def test_preview_option_is_per_tab_and_accessible_from_incoming(native_window, tmp_path):
    action = preview_action(native_window)
    assert not action.isEnabled()
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.receive('Hello earth.\n', [])
    native_window.toggle_view_btn.click()
    assert view.active_view() is view.incoming_editor

    action.trigger()
    preview = visible_preview(view)
    native_window.toggle_view_btn.click()
    assert view.active_view() is view.incoming_editor
    native_window.toggle_view_btn.click()
    assert view.active_view() is preview

    duplicate = native_window.duplicate_tab()
    assert not action.isChecked()
    assert duplicate.active_view() is duplicate.inline_editor
    native_window.tabs.setCurrentWidget(view)
    assert action.isChecked()
    action.trigger()
    assert not action.isChecked()
    assert view.active_view() is view.inline_editor


@pytest.mark.parametrize('accepted', [True, False])
def test_green_preview_click_seeks_and_keeps_the_suggestion_actionable(native_window, audio_review, accepted, request):
    view = audio_review
    doc = view.document
    action = preview_action(native_window)
    action.trigger()
    preview = visible_preview(view)
    assert view.diff_view.current == 0
    player = view.playback.player
    request.addfinalizer(lambda: player.setSource(QUrl()))
    player.setPosition(20000)
    native_window.activateWindow()

    cursor = QTextCursor(preview.document())
    cursor.setPosition(doc.incoming.index('copper') + len('copper') - 1)
    right = QTextCursor(cursor)
    right.movePosition(QTextCursor.NextCharacter)
    rect = preview.cursorRect(cursor)
    # Click the right half of the last letter, where the nearest caret is outside the highlight.
    point = rect.center()
    point.setX(preview.cursorRect(right).x() - 2)
    page = view.original_stack.currentWidget()
    surface_point = preview.viewport().mapTo(preview, point)
    projected = page.mapFromScene(page.proxy.mapToScene(QPointF(surface_point)))
    QTest.mouseClick(page.viewport(), Qt.LeftButton, pos=projected)
    assert view.diff_view.current == 1
    colors = {mark.cursor.selectedText(): mark.format.background().color().name()
              for mark in preview.extraSelections()}
    assert colors['copper'] == '#ffe08a' and colors['Orange'] == '#9edcb0'
    assert 10840 <= player.position() <= 11040
    assert not player.isPlaying()
    before = doc.original, doc.incoming

    key = Qt.Key_A if accepted else Qt.Key_D
    QTest.keyClick(preview, key)
    wait_until(lambda: not doc.busy and len(view.review_model.edits) == 1)
    after = doc.original, doc.incoming
    assert ('copper' in doc.original, 'copper' in doc.incoming) == (accepted, accepted)
    preview = visible_preview(view)
    assert action.isChecked()
    QTest.keyClick(preview, Qt.Key_Z, Qt.ControlModifier)
    assert (doc.original, doc.incoming) == before
    preview = visible_preview(view)
    preview.redo()
    assert (doc.original, doc.incoming) == after
    visible_preview(view)


def test_switching_preview_keeps_the_visible_passage(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    original = '\n'.join(f'Testimony segment {i}.' for i in range(85))
    added = '\n'.join(f'Additional passage {i}.' for i in range(32))
    view.editor.setPlainText(original)
    view.receive(added + '\n' + original, [])
    QTest.qWait(30)
    anchor = 'Testimony segment 49.'
    editor = view.inline_editor
    editor.scroll_to_center_line(next(i for i, line in enumerate(editor.page_lines()) if line.text == anchor))

    action = preview_action(native_window)
    action.trigger()
    preview = visible_preview(view)
    wait_until(lambda: preview.page_lines()[preview.center_line()].text == anchor)
    action.trigger()
    wait_until(lambda: editor.page_lines()[editor.center_line()].text == anchor)


def test_speaker_card_follows_the_displayed_page_and_line(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    original = ('MS. LIN: This testimony refers to the signed contract.\n'
                'MS. LIN: The schedule was attached to the last page.\n'
                'MS. LIN JONES: Everyone received a copy the next morning.')
    view.editor.setPlainText(original)
    extra = ''.join(f'Additional testimony {i}.\n' for i in range(28))
    view.receive(extra + original.replace('MS. LIN:', 'SPEAKER 1:')
                 .replace('MS. LIN JONES:', 'SPEAKER 1:'), [])
    sidebar = view.diff_view
    sidebar.filter_speaker('SPEAKER 1')
    assert len(sidebar.visible_indices) == 1

    def location(editor):
        line = next(line for line in editor.page_lines() if 'Everyone received' in line.text)
        return f'Page {line.page}, line {line.number}'

    def heading():
        return sidebar.cards[sidebar.current].findChild(QLabel).text()

    original_location = location(view.editor)
    assert original_location in heading()
    action = preview_action(native_window)
    action.trigger()
    preview_location = location(visible_preview(view))
    assert preview_location != original_location
    assert preview_location in heading()
    native_window.toggle_view_btn.click()
    assert location(view.incoming_editor) in heading()
    native_window.toggle_view_btn.click()
    assert preview_location in heading()
    action.trigger()
    assert original_location in heading()


def test_preview_locates_first_visible_addition_after_a_page_break(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    original = '\n'.join(f'Testimony {i}.' for i in range(25))
    view.editor.setPlainText(original)
    view.receive(original + '\nMS. LIN: Good afternoon.', [])
    preview_action(native_window).trigger()
    preview = visible_preview(view)
    view.diff_view.select(0)

    line = next(line for line in preview.page_lines() if 'Good afternoon.' in line.text)
    assert (line.page, line.number) == (2, 1)
    assert 'Page 2, line 1' in view.diff_view.cards[0].findChild(QLabel).text()
    assert preview.textCursor().position() == line.position


@pytest.mark.parametrize('change', ['paragraph break', 'deletion', 'metadata'])
def test_preview_keeps_suggestions_without_added_text_in_the_sidebar(native_window, tmp_path, change):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    state = view.document.native
    if change == 'metadata':
        state.incoming = state.original.define_field('NAME', 'Jane')
        view.refresh()
    else:
        original = ('First sentence. Second sentence.' if change == 'paragraph break'
                    else 'First sentence.\nRemove this.\nSecond sentence.')
        view.editor.setPlainText(original)
        view.receive('First sentence.\nSecond sentence.', [])
    expected = state.incoming

    preview_action(native_window).trigger()
    preview = visible_preview(view)
    assert not any(mark.format.background().style() != Qt.NoBrush for mark in preview.extraSelections())
    assert len(view.review_model.edits) == 1 and view.diff_view.has_current
    view.diff_view.decision_buttons[0].click()
    wait_until(lambda: not view.document.busy)
    assert not view.review_model.edits
    assert state.original.text == expected.text
    assert state.original.definitions == expected.definitions


def test_preview_discards_completed_work_for_a_replaced_proposal(native_window, tmp_path, monkeypatch):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.receive('Hello earth.\n', [])
    action = preview_action(native_window)
    from app.src import accept_all_preview

    started, release = Event(), Event()
    resolve = accept_all_preview.resolve_all

    def slow_first(original, incoming, ranges, accept):
        if 'earth' in incoming.text:
            started.set()
            assert release.wait(5)
        return resolve(original, incoming, ranges, accept)

    monkeypatch.setattr(accept_all_preview, 'resolve_all', slow_first)
    action.trigger()
    try:
        wait_until(started.is_set)
        assert view.original_stack.currentWidget().text() == 'Preparing Accept All preview…'
        view.receive('Hello moon.\n', [])
    finally:
        release.set()
    preview = visible_preview(view)
    assert preview.toPlainText() == 'Hello moon.\n'
    assert view.document.original == 'Hello world.\n'


def test_preview_failure_restores_regular_review(native_window, tmp_path, monkeypatch):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.receive('Hello earth.\n', [])
    action = preview_action(native_window)
    from app.src import accept_all_preview

    def fail(*_):
        raise ValueError('Test preview error')

    monkeypatch.setattr(accept_all_preview, 'resolve_all', fail)
    action.trigger()
    wait_until(lambda: not action.isChecked())
    assert view.active_view() is view.inline_editor
    assert 'Test preview error' in native_window.status_label.text()
    assert view.document.original == 'Hello world.\n'
