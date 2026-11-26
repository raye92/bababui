from copy import deepcopy
from threading import Event
from time import monotonic

import pytest
from PySide6.QtCore import QPointF, QRect, Qt, QUrl
from PySide6.QtGui import QTextCursor, QTextFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

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


def has_outline_edge(image, x, y):
    scale = image.devicePixelRatio()
    xs = range(round((x - 2) * scale), round((x + 2) * scale) + 1)
    for dy in range(-2, 3):
        row = round((y + dy) * scale)
        if not any(image.pixelColor(px, row).name() == '#d4a000' for px in xs):
            return False
    return True


def outline_edges(preview, word):
    selection = preview.document().find(word)
    assert selection.hasSelection()
    cursor = QTextCursor(preview.document())
    cursor.setPosition(selection.selectionStart())
    first = preview.cursorRect(cursor)
    cursor.setPosition(selection.selectionEnd())
    last = preview.cursorRect(cursor)
    image = preview.viewport().grab().toImage()
    center = first.center().y()
    return has_outline_edge(image, first.x(), center), has_outline_edge(image, last.x(), center)


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
    assert not preview.isReadOnly()
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
    assert outline_edges(preview, 'information') == (True, True)
    assert {mark.format.background().color().name() for mark in marks} == {'#9edcb0'}
    assert not any(mark.format.fontUnderline() for mark in marks)
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


def test_preview_draws_one_outline_across_wraps_and_paragraphs(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText('Opening.\nClosing.')
    added = 'The half-pink form was included with the other signed forms. ' * 3
    view.receive('Opening.\n' + added.rstrip() + '\n\nA short final line.\nClosing.', [])
    preview_action(native_window).trigger()
    preview = visible_preview(view)
    assert len(view.review_model.edits) == 1
    lines = []
    for number in (1, 2, 3):
        block = preview.document().findBlockByNumber(number)
        bounds = preview.document().documentLayout().blockBoundingRect(block)
        layout = block.layout()
        lines.extend(layout.lineAt(i).naturalTextRect().translated(bounds.topLeft())
                     for i in range(layout.lineCount()))
    assert len(lines) > 3
    left = min(rect.left() for rect in lines if rect.width()) - preview.horizontalScrollBar().value()
    right = max(rect.right() for rect in lines) - preview.horizontalScrollBar().value()
    image = preview.viewport().grab().toImage()
    for line in lines:
        y = line.center().y() - preview.verticalScrollBar().value()
        assert has_outline_edge(image, left, y) and has_outline_edge(image, right, y)
    scale = image.devicePixelRatio()
    middle = round((left + right) / 2 * scale)
    border = [image.pixelColor(middle, y).name() == '#d4a000' for y in range(image.height())]
    assert sum(on and not previous for previous, on in zip([False] + border, border)) == 2


def test_preview_outlines_the_green_word_at_a_text_direction_change(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText('שלום black example.')
    view.receive('שלום pink example.', [])
    preview_action(native_window).trigger()
    preview = visible_preview(view)
    image = preview.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    y = preview.cursorRect(preview.document().find('pink')).center().y()
    colors = [image.pixelColor(x, round(y * scale)).name() for x in range(image.width())]
    green = [i for i, color in enumerate(colors) if color == '#9edcb0']
    yellow = [i for i, color in enumerate(colors) if color == '#d4a000']
    assert 0 < min(green) - min(yellow) <= 4 * scale
    assert 0 < max(yellow) - max(green) <= 4 * scale


@pytest.mark.parametrize('original,proposal', [
    ('ready for review', '"ready for review"'),
    ('"ready for review"', 'ready for review'),
    ('"ready for review"', 'ready for review!'),
])
def test_preview_uses_one_outline_for_both_ends_of_a_quotation(native_window, tmp_path, original, proposal):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText(f'He said {original}, then left.')
    view.receive(f'He said {proposal}, then left.', [])
    change, = view.review_model.edits
    assert len(change.ranges) == 2
    preview_action(native_window).trigger()
    preview = visible_preview(view)
    image = preview.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    cursor = QTextCursor(preview.document())
    cursor.setPosition(change.ranges[0][2])
    first = preview.cursorRect(cursor)
    cursor.setPosition(change.ranges[-1][3])
    last = preview.cursorRect(cursor)
    y = first.center().y()
    assert has_outline_edge(image, first.x(), y) and has_outline_edge(image, last.x(), y)
    interior = range(round((first.x() + 4) * scale), round((last.x() - 4) * scale))
    assert all(image.pixelColor(x, round(y * scale)).name() != '#d4a000' for x in interior)


@pytest.mark.parametrize('accepted', [True, False])
def test_green_preview_click_seeks_and_keeps_the_suggestion_actionable(native_window, audio_review, accepted, request):
    view = audio_review
    doc = view.document
    action = preview_action(native_window)
    action.trigger()
    preview = visible_preview(view)
    assert view.diff_view.current == 0
    assert outline_edges(preview, 'Orange') == (True, True)
    assert outline_edges(preview, 'copper') == (False, False)
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
    assert outline_edges(preview, 'Orange') == (False, False)
    assert outline_edges(preview, 'copper') == (True, True)
    assert 10840 <= player.position() <= 11040
    assert not player.isPlaying()
    before = doc.original, doc.incoming

    key = Qt.Key_A if accepted else Qt.Key_D
    QTest.keyClick(preview, key, Qt.AltModifier)
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


def test_typed_preview_keeps_shared_edits_and_rejects_amended_green(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText('First black statement.')
    view.receive('First green statement.', [])
    preview_action(native_window).trigger()
    preview = visible_preview(view)
    assert view.active_editor() is preview
    cursor = preview.textCursor()
    cursor.setPosition(2)
    preview.setTextCursor(cursor)
    QTest.keyClicks(preview, 'wasd ')
    assert view.document.original == 'Fiwasd rst black statement.'
    cursor = preview.document().find('green')
    preview.setTextCursor(cursor)
    QTest.keyClicks(preview, 'blue')
    assert view.document.incoming == 'Fiwasd rst blue statement.'
    assert view.document.original == 'Fiwasd rst black statement.'
    assert len(view.review_model.edits) == 1
    assert any(mark.cursor.selectedText() == 'blue' for mark in preview.extraSelections())
    view.review(0, False)
    assert view.document.incoming == view.document.original == 'Fiwasd rst black statement.'
    view.undo_review()
    assert view.document.incoming == 'Fiwasd rst blue statement.'


@pytest.mark.parametrize('invalid, reason', [('\n', 'single line'), ('😀', 'Windows-1252')])
def test_rejected_edit_rolls_back_only_the_typed_character(native_window, tmp_path, monkeypatch, invalid, reason):
    from app.src import native_editor
    from app.tests.test_native_casecat import zip_bytes
    from app.tests.test_native_fields import field_files

    path = tmp_path / 'fields.zip'
    path.write_bytes(zip_bytes(field_files()))
    native_window.import_zip(0, path)
    view = native_window.current
    view.receive(view.document.original.replace('More.', 'More testimony.'), [])
    preview_action(native_window).trigger()
    editor = visible_preview(view)
    before = view.document.incoming
    field = next(e for e in view.review_model.incoming.elements if e.kind == 'field')
    comparisons = []
    matcher = native_editor.SequenceMatcher

    def record_comparison(junk, left, right, **kwargs):
        comparisons.append(max(len(left), len(right)))
        return matcher(junk, left, right, **kwargs)

    monkeypatch.setattr(native_editor, 'SequenceMatcher', record_comparison)
    cursor = editor.textCursor()
    cursor.setPosition(field.start + 1)
    cursor.setPosition(field.start + 2, QTextCursor.KeepAnchor)
    cursor.insertText(invalid)
    assert reason in view.document.status
    assert editor.toPlainText() == view.document.incoming == before
    assert max(comparisons, default=0) <= 1
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)
    QTest.keyClicks(editor, 'x')
    assert editor.toPlainText() == view.document.incoming == before + 'x'


def test_typing_and_smart_keys_are_scoped_to_transcript_tabs(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    editor = view.editor
    editor.setPlainText('one two')
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)
    QTest.keyClicks(editor, ' wasd[]')
    assert view.document.original == 'one two wasd[]'
    QTest.keyClick(editor, Qt.Key_Slash)
    assert view.smart_keys
    assert view.document.original == 'one two wasd[]'
    QTest.keyClick(editor, Qt.Key_Space)
    assert view.document.original.endswith('[] ')
    QTest.keyClick(editor, Qt.Key_Slash)
    QTest.keyClick(editor, Qt.Key_Slash, Qt.ControlModifier | Qt.ShiftModifier)
    assert view.document.original.endswith('[] /')
    assert not view.smart_keys
    QTest.keyClick(editor, Qt.Key_Slash)
    clone = native_window.duplicate_tab()
    assert view.smart_keys and not clone.smart_keys


def test_preview_smart_keys_blink_over_the_current_character(native_window, tmp_path, request):
    flash_time = QApplication.cursorFlashTime()
    request.addfinalizer(lambda: QApplication.setCursorFlashTime(flash_time))
    QApplication.setCursorFlashTime(250)
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText('Well-known draft.')
    view.receive('Well-known wording.', [])
    native_window.keyboard_mode_btn.click()
    preview_action(native_window).trigger()
    editor = visible_preview(view)
    native_window.activateWindow()
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.setPosition(4)
    editor.setTextCursor(cursor)

    def cell_color(position):
        probe = QTextCursor(editor.document())
        probe.setPosition(position)
        left = editor.cursorRect(probe)
        probe.movePosition(QTextCursor.NextCharacter)
        x = (left.x() + editor.cursorRect(probe).x()) // 2
        return editor.viewport().grab(QRect(x, left.y() + 2, 1, 1)).toImage().pixelColor(0, 0)

    background = cell_color(5)
    # The preview paints its own hyphens over the transcript text.
    wait_until(lambda: cell_color(4) != background)
    wait_until(lambda: cell_color(4) == background)
    QTest.keyClick(editor, Qt.Key_Right)
    assert editor.textCursor().position() == 5 and not editor.textCursor().hasSelection()
    wait_until(lambda: cell_color(5) != background)
    assert cell_color(4) == background

    QTest.keyClick(editor, Qt.Key_Slash, Qt.ControlModifier | Qt.ShiftModifier)
    assert view.document.incoming == 'Well-/known wording.'
    QTest.keyClick(editor, Qt.Key_Slash)
    assert cell_color(6) == background
    QTest.keyClicks(editor, 'X')
    assert view.document.incoming == 'Well-/Xknown wording.'


def test_brackets_play_from_the_preview_caret_and_stop(native_window, audio_review):
    view = audio_review
    preview_action(native_window).trigger()
    editor = visible_preview(view)
    cursor = editor.document().find('copper')
    cursor.setPosition(cursor.selectionStart())
    editor.setTextCursor(cursor)
    player = view.playback.player
    player.setPosition(20000)
    QTest.keyClick(editor, Qt.Key_Slash)
    QTest.keyClick(editor, Qt.Key_BracketLeft)
    assert player.isPlaying() and abs(player.position() - 10940) < 200
    QTest.keyClick(editor, Qt.Key_BracketRight)
    assert not player.isPlaying() and player.position() == 0
    QTest.keyClick(editor, Qt.Key_F9, Qt.ShiftModifier)
    assert player.isPlaying()
    QTest.keyClick(editor, Qt.Key_F9, Qt.ControlModifier)
    assert not player.isPlaying() and player.position() == 0
    assert view.playback._highlight_editor is None
    # A WAV without passage timing starts from its own playback head.
    view.playback.timing = None
    view.playback.seek(6000)
    QTest.keyClick(editor, Qt.Key_BracketLeft)
    assert player.isPlaying() and abs(player.position()-6000) < 200
    native_window.open_settings()
    QTest.qWait(20)
    assert not player.isPlaying() and player.position() == 0
    native_window.tabs.setCurrentWidget(view)
    QTest.keyClick(editor, Qt.Key_BracketLeft)
    assert player.isPlaying()
    QTest.keyClick(editor, Qt.Key_BracketRight)
    QTest.qWait(20)
    assert not player.isPlaying() and player.position() == 0


def test_imported_shortcuts_macro_history_and_text_input(native_window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from app.src.smart_keys import Binding, SmartKeyProfile

    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText('one two')
    view.set_smart_keys(True)
    QTest.keyClick(view.editor, Qt.Key_W, Qt.ControlModifier)
    assert native_window.current is view and view.document.original == 'two one'
    QTest.keyClick(view.editor, Qt.Key_Z, Qt.ControlModifier)
    assert view.document.original == 'one two'
    action = native_window.settings_page
    native_window.open_settings()
    QTest.keyClicks(action.profile_search, '/wasd[]')
    assert action.profile_search.text() == '/wasd[]'
    custom = tmp_path / 'Portable.sgkbd'
    custom.write_text('a=Replacement\nb=[Nonexistent Function]\nc=')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(custom), ''))
    action.import_keyboard()
    native_window.tabs.setCurrentWidget(view)
    view.editor.selectAll()
    QTest.keyClicks(view.editor, 'abc')
    assert view.document.original == 'Replacement'
    assert 'Nonexistent Function' in view.document.status
    assert native_window.persist_session()
    from app.src.documents import load_session_state
    settings = load_session_state(native_window.session_path)[-1]
    assert SmartKeyProfile.from_dict(settings['keyboard/profile']).get('a').value == 'Replacement'

    macro = Binding('x', 'macro', 'Phrase', (('literal', 'first'), ('literal', ' second')))
    blocked = Binding('y', 'macro', 'Needs dictionary', (('literal', 'bad'), ('command', 'D-Define')))
    action._apply_profile(SmartKeyProfile('Recorded', (macro, blocked)))
    view.editor.selectAll()
    QTest.keyClicks(view.editor, 'xy')
    assert view.document.original == 'first second'
    view.undo_review()
    assert view.document.original == 'Replacement'


def test_preview_formats_new_paragraph_after_typing_idle(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText('Opening.\nOld testimony.')
    view.receive('Opening.\nNew testimony.', [])
    preview_action(native_window).trigger()
    editor = visible_preview(view)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.Start)
    editor.setTextCursor(cursor)
    QTest.keyClicks(editor, 'EXAMINATION')
    QTest.keyClick(editor, Qt.Key_Return)
    caret = editor.textCursor().position()
    wait_until(lambda: editor.document().firstBlock().blockFormat().alignment() == Qt.AlignHCenter, timeout=5)
    assert editor.textCursor().position() == caret
    assert view.document.original.startswith('EXAMINATION\n')


def test_smart_undo_retains_prior_typing_selection_and_redo_on_failed_macro(native_window, tmp_path, monkeypatch):
    from app.src.smart_keys import Binding
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    editor = view.editor
    editor.setPlainText('example')
    QTest.keyClicks(editor, 'abc')
    QTest.keyClick(editor, Qt.Key_Slash)
    cursor = editor.textCursor()
    cursor.setPosition(7)
    cursor.setPosition(4, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key_0)
    QTest.keyClick(editor, Qt.Key_O)
    assert view.document.original == 'abcexample'
    assert (editor.textCursor().anchor(), editor.textCursor().position()) == (7, 4)
    QTest.keyClick(editor, Qt.Key_O)
    assert view.document.original == 'example'
    macro = Binding('x', 'macro', 'Failed search', (('literal', 'X'), ('command', 'Go To Bookmarked Cursor')))
    assert view.keyboard.run(macro, editor)
    assert view.document.original == 'example'
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ('', False))
    cancelled = Binding('y', 'macro', 'Find', (('literal', 'A'), ('command', 'Search'), ('literal', 'B')))
    assert not view.keyboard.run(cancelled, editor)
    assert view.document.original == 'example'
    view.redo_review()
    assert view.document.original == 'abcexample'


def test_preview_keeps_native_caption_tables_and_linked_fields(native_window, monkeypatch):
    from app.src.documents import import_casecat
    from app.src.native_dialogs import FillFieldDialog
    from app.tests.test_native_fields import field_files
    from app.tests.test_native_notice_cover import covered, details

    _, _, bundle, job, _, body = covered(field_files(), details())
    doc = import_casecat(bundle)
    view = native_window.add_document(doc)
    view.receive(job.text[:body] + 'Changed testimony.\n' + job.text[body:], [])
    preview_action(native_window).trigger()
    editor = visible_preview(view)
    frames = editor.document().rootFrame().childFrames()
    assert len(frames) == 2
    monkeypatch.setattr(FillFieldDialog, 'get_value', lambda *args: ('A NEW PLAINTIFF', True))
    editor.fill_native_field('PLAINTIFF')
    for revision in (doc.native.original, doc.native.incoming):
        fields = [e for e in revision.elements if e.name == 'PLAINTIFF']
        assert len(fields) == 2 and all(e.value == 'A NEW PLAINTIFF' for e in fields)
    wait_until(lambda: not view._format_timer.isActive() and not view._format_running, timeout=6)
    assert editor.toPlainText() == doc.incoming
    assert len(editor.document().rootFrame().childFrames()) == 2
    view.review(None, False)
    assert 'Changed testimony.' not in doc.original
    assert 'A NEW PLAINTIFF' in doc.original


def test_typing_away_the_last_suggestion_keeps_the_live_caret(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText('First red word.')
    view.receive('First blue word.', [])
    preview_action(native_window).trigger()
    editor = visible_preview(view)
    editor.setTextCursor(editor.document().find('blue'))
    QTest.keyClicks(editor, 'red')
    assert not view.review_model.edits and view.active_editor() is editor
    QTest.qWait(550)
    QTest.keyClicks(editor, 'der')
    assert view.document.original == view.document.incoming == 'First redder word.'
    view.set_accept_all_preview(False)
    assert view.active_editor() is view.editor
    assert view.editor.toPlainText() == view.document.original


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
    assert not preview._focus_rect().isEmpty()
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
