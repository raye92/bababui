import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QLabel
from app.src.diff_view import DiffView, _EqualBlock
from app.src.documents import Document
from app.src.document_view import DocumentView
from app.src.transcript_diff import parse_transcript
from transcript_formatting import TranscriptFormatter


@pytest.fixture
def view():
    app = QApplication.instance() or QApplication([])
    widget = DiffView()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def content(text):
    return [b.text for b in parse_transcript(text)]


def buttons(view, text):
    return [b for b in view.findChildren(QPushButton) if text in b.text() and not b.isHidden()]


def click(view, text, index=0):
    buttons(view, text)[index].click()
    QApplication.sendPostedEvents(None, 0)


def test_heading_name_and_examiner_have_separate_controls(view):
    fmt = TranscriptFormatter().apply_formatting
    old = fmt('BY MR. BRAULT:\nQ Good morning, Dr. Goebel. My name is Patrick Brault.\nA Yes.')[0]
    new = fmt('EXAMINATION\nBY SPEAKER 2:\nQ Good morning, Dr. Hill Bell. My name is Patrick Brault.\nA Yes.')[0]
    view.set_texts(old, new)
    assert len(buttons(view, 'Accept')) == 3
    changes = [label.text() for label in view.findChildren(QLabel)]
    assert any('<span' in text and 'Goebel' in text for text in changes)
    results = []
    view.resolved.connect(lambda a, b: results.append((a, b)))
    click(view, 'Accept')  # insert heading
    assert content(results[-1][0])[:2] == ['EXAMINATION', 'BY MR. BRAULT:']
    assert len(buttons(view, 'Accept')) == 2
    click(view, 'Deny', 1)  # retain correct witness name
    click(view, 'Deny')  # retain examiner
    assert results[-1][0] == results[-1][1]
    assert content(results[-1][0]) == ['EXAMINATION', 'BY MR. BRAULT:',
        'Q Good morning, Dr. Goebel. My name is Patrick Brault.', 'A Yes.']
    assert '          1' in results[-1][0]


def test_layout_only_incoming_does_not_leave_unresolvable_review(view):
    plain = 'Q Please describe the records you reviewed before the examination.\nA Yes.'
    document = Document(original=plain, incoming=TranscriptFormatter().apply_formatting(plain)[0])
    widget = DocumentView(document)
    try:
        assert widget.original_stack.currentWidget() is widget.editor
        assert document.original == document.incoming == plain
    finally:
        widget.close()


def test_repeated_equal_edits_keep_later_accept_at_correct_location(view):
    view.set_texts('Shared\nOld', 'Shared\nNew')
    results = []
    view.resolved.connect(lambda a, b: results.append((a, b)))
    shared = view.findChildren(_EqualBlock)[0]
    shared.setPlainText('Shared\nAdded')
    shared.setPlainText('Shared\nAdded\nMore')
    click(view, 'Accept')
    assert results[-1] == ('Shared\nAdded\nMore\nNew',) * 2


def test_split_paragraph_equal_edit_updates_both_sides(view):
    view.set_texts('Some long paragraph here.\nOld', 'Some long\nparagraph here.\nNew')
    events = []
    view.autosaved.connect(lambda a, b: events.append((a, b)))
    view.findChildren(_EqualBlock)[0].setPlainText('Edited shared paragraph.')
    assert events[-1] == ('Edited shared paragraph.\nOld', 'Edited shared paragraph.\nNew')


@pytest.mark.parametrize('action', ['Accept', 'Deny'])
def test_empty_side_can_be_resolved(view, action):
    view.set_texts('', 'EXAMINATION\nQ Hello?')
    events = []
    view.resolved.connect(lambda a, b: events.append((a, b)))
    for _ in range(3):
        if not buttons(view, action):
            break
        click(view, action)
    assert not buttons(view, action)
    assert events[-1][0] == events[-1][1]
    assert content(events[-1][0]) == (['EXAMINATION', 'Q Hello?'] if action == 'Accept' else [])


def test_unchanged_long_turn_resizes_without_hiding_text(view):
    from PySide6.QtGui import QFontDatabase
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/cour.ttf')
    text = 'Q ' + 'Please describe this record. ' * 40
    view.resize(1000, 600)
    view.set_texts(text + '\nA Old.', text + '\nA New.')
    view.show()
    QApplication.processEvents()
    block = view.findChildren(_EqualBlock)[0]
    wide_height = block.height()
    view.resize(400, 600)
    QApplication.processEvents()
    assert block.height() > wide_height
    assert block.height() >= block.blockBoundingRect(block.document().begin()).height()


def test_mouse_accept_after_adding_line_to_equal_block(view):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    view.resize(800, 600)
    view.set_texts('Shared\nOld', 'Shared\nNew')
    view.show()
    QApplication.processEvents()
    shared = view.findChildren(_EqualBlock)[0]
    shared.setFocus()
    shared.setPlainText('Shared\nAdded')
    events = []
    view.resolved.connect(lambda a, b: events.append((a, b)))
    QTest.mouseClick(buttons(view, 'Accept')[0], Qt.LeftButton)
    QApplication.processEvents()
    assert events == [('Shared\nAdded\nNew', 'Shared\nAdded\nNew')]


def test_adjacent_equal_turns_share_an_editor(view):
    view.set_texts('Q First?\nA Yes.\nQ Second?\nA Old.',
                   'Q First?\nA Yes.\nQ Second?\nA New.')
    editors = view.findChildren(_EqualBlock)
    assert len(editors) == 1
    assert editors[0].toPlainText() == 'Q First?\nA Yes.\nQ Second?'


def test_logical_numbers_and_question_deletion(view):
    fmt = TranscriptFormatter().apply_formatting
    old = 'Q First?\nA First.\nQ Removed?\nA Yes, I am.\nQ Good?'
    new = 'Q First?\nA First.\nA Yes, I am.\nQ Good?'
    view.set_texts(fmt(old)[0], fmt(new)[0])
    assert len(buttons(view, 'Accept')) == 1
    assert [w._start_line for w in view.findChildren(_EqualBlock)] == [1, 4]
    events = []
    view.resolved.connect(lambda a,b: events.append((a,b)))
    click(view, 'Accept')
    assert content(events[-1][0]) == content(new)
    assert events[-1][0] == events[-1][1]


def test_deny_question_deletion_retains_indented_paragraph(view):
    old = 'Q First?\n          Separate topic.\nA First.\nQ Removed?\nA Yes.\nQ Good?'
    new = old.replace('Q Removed?\n', '')
    view.set_texts(old,new)
    events=[]
    view.resolved.connect(lambda a,b: events.append((a,b)))
    click(view,'Deny')
    assert events[-1] == (old,old)


@pytest.mark.parametrize('deleting', [False, True])
@pytest.mark.parametrize('action', ['Accept', 'Deny'])
def test_consecutive_one_sided_changes_share_one_action(view, deleting, action):
    short = 'Q Before?\nA Before.\nQ After?\nA After.'
    long = short.replace('Q After?', 'EXAMINATION\nBY MR. TEST:\nQ Added?\n          Separate paragraph.\nA Added.\nQ After?')
    old, new = (long, short) if deleting else (short, long)
    view.set_texts(old, new)
    assert len(buttons(view, 'Accept')) == 1
    events = []
    view.resolved.connect(lambda a, b: events.append((a, b)))
    click(view, action)
    expected = new if action == 'Accept' else old
    assert events[-1] == (expected, expected)


def test_one_sided_groups_stop_at_unchanged_content(view):
    view.set_texts('Q First?\nA First.\nQ Last?',
                   'EXAMINATION\nBY MR. TEST:\nQ First?\nA First.\nQ Added?\nA Added.\nQ Last?')
    assert len(buttons(view, 'Accept')) == 2


def test_adjacent_replacement_pairs_stay_separate(view):
    view.set_texts('Q First old?\nA First old.\nQ Second old?\nA Second old.',
                   'Q First new?\nA First new.\nQ Second new?\nA Second new.')
    assert len(buttons(view, 'Accept')) == 4
