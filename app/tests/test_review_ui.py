import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from html import unescape
import re
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from app.src.review_view import ReviewView, change_diff
from app.src.suggestions import Suggestion
from app.tests.test_suggestion_filter import speakers
from app.tests.test_suggestions import revision


def test_speaker_summary_is_fixed_and_cards_filter_to_mismatches():
    from app.src.suggestion_filter import prepare
    app = QApplication.instance() or QApplication([])
    original = speakers(['MS. SIEMENS']*8 + ['MR. LEISER']*2)
    incoming, evidence = prepare(original, original.text.replace('MS. SIEMENS:', 'SPEAKER 3:').replace('MR. LEISER:', 'SPEAKER 3:'))
    view = ReviewView()
    view.set_revisions(original, incoming, review={'evidence':evidence,'overrides':{},'locations':[]})
    assert view.summary.parent() is view
    assert '8 matches' in view.summary.text()
    view.filter_speaker('SPEAKER 3')
    assert len(view.visible_indices) == 2
    assert sum(not card.isHidden() for card in view.cards) == 1
    previous = view.current
    view.navigate(1)
    assert view.current != previous
    assert sum(not card.isHidden() for card in view.cards) == 1
    view.select(1)
    assert view.current == 1
    view.close()


def highlighted_text(html):
    return [unescape(re.sub(r'<[^>]*>', '', text))
            for text in re.findall(r'<b\b[^>]*>(.*?)</b>', html, re.DOTALL)]


def plain_preview(html):
    return unescape(re.sub(r'<[^>]*>', '', html))


def test_preview_uses_authoritative_pair_without_splitting_word_changes():
    original = revision("You're familiar with the case of Timothy Welch?")
    incoming = original.revise("Okay. And you're familiar with the case of Timothy Walsh?")
    lead = Suggestion(original, incoming, ((0, 1, 0, 11),))
    name = Suggestion(original, incoming, ((41, 46, 51, 56),))
    (_, preview), = change_diff(lead)
    assert highlighted_text(preview) == ['Y', 'Okay. And y']
    assert plain_preview(preview) == "YOkay. And you're familiar with the case of Timothy Welch?"
    assert 'Walsh' not in plain_preview(preview)
    (_, preview), = change_diff(name)
    assert highlighted_text(preview) == ['Welch', 'Walsh']
    assert plain_preview(preview) == "You're familiar with the case of Timothy WelchWalsh?"
    assert 'Okay.' not in plain_preview(preview)


def test_preview_keeps_edits_visible_with_short_context_and_escapes_markup():
    original = revision(' '.join(f'word{i}' for i in range(20)) + ' <old> ' +
                        ' '.join(f'tail{i}' for i in range(20)))
    incoming = original.revise(original.text.replace('<old>', '<new>'))
    start = original.text.index('<old>')
    change = Suggestion(original, incoming, ((start, start+5, start, start+5),))
    (_, preview), = change_diff(change)
    assert highlighted_text(preview) == ['<old>', '<new>']
    assert '<old>' not in preview and '<new>' not in preview
    assert 'word0 ' not in plain_preview(preview)
    assert plain_preview(preview).count('word19') == 1
    assert plain_preview(preview).count('tail0') == 1
    assert 'tail19' not in plain_preview(preview)


def test_preview_explains_empty_and_whitespace_sides():
    original = revision('Before after.')
    incoming = original.revise('Before\nAfter after.')
    insertion = Suggestion(original, incoming, ((6, 6, 6, 12),), 'structure')
    (_, preview), = change_diff(insertion)
    assert len(highlighted_text(preview)) == 1
    assert 'After' in highlighted_text(preview)[0]
    assert '↵' in highlighted_text(preview)[0]
    assert '(nothing)' not in plain_preview(preview)
    assert plain_preview(preview).count('Before') == 1
    incoming = original.revise('Before\nafter.')
    boundary = Suggestion(original, incoming, ((6, 7, 6, 7),), 'structure')
    (_, preview), = change_diff(boundary)
    assert highlighted_text(preview)[0] == '·'
    assert '↵' in highlighted_text(preview)[1]


def test_preview_applies_all_linked_occurrences_in_the_same_context():
    original = revision('Said: ').insert_field(6, 'SPEAKER', 'Jane')
    original = original.replace(10, 10, ' and ')
    original = original.insert_field(15, 'SPEAKER', 'Jane')
    incoming = original.set_field('SPEAKER', 'Joan')
    change = Suggestion(original, incoming, ((6, 10, 6, 10), (15, 19, 15, 19)),
                        'field', 'SPEAKER')
    rows = change_diff(change)
    assert len(rows) == 1
    assert plain_preview(rows[0][1]) == 'Said: JaneJoan and JaneJoan'
    assert highlighted_text(rows[0][1]) == ['Jane', 'Joan', 'Jane', 'Joan']


def test_metadata_preview_shows_each_definition_name_once():
    app = QApplication.instance() or QApplication([])
    original = revision('Shared text.').define_field('NAME', 'Jane')
    incoming = original.set_field('NAME', 'Joan')
    view = ReviewView()
    view.set_revisions(original, incoming)
    labels = view.cards[0].findChildren(QLabel, 'comparison')
    assert len(labels) == 1
    assert plain_preview(labels[0].text()) == 'NAME: JaneJoan'
    assert highlighted_text(labels[0].text()) == ['Jane', 'Joan']
    view.close()


def test_one_card_accepts_or_rejects_the_selected_edit():
    from app.src.review_model import build_review
    app = QApplication.instance() or QApplication([])
    original = revision('The red car is large.')
    incoming = original.revise('The blue car is small.')
    view = ReviewView()
    view.set_model(build_review(original, incoming))
    view.show()
    app.processEvents()
    requests, selected = [], []
    view.requested.connect(lambda index, accept: requests.append((index, accept)))
    view.selected.connect(selected.append)
    view.navigate(1)
    assert view.current == 1
    assert sum(not card.isHidden() for card in view.cards) == 1
    card = view.cards[1]
    labels = card.findChildren(QLabel, 'comparison')
    assert len(labels) == 1
    assert plain_preview(labels[0].text()) == 'The red car is largesmall.'
    QTest.mouseClick(card.findChild(QLabel), Qt.LeftButton)
    assert selected[-1] == 1
    buttons = {button.text(): button for button in card.findChildren(QPushButton)}
    assert set(buttons) == {'Accept', 'Reject'}
    buttons['Accept'].click()
    buttons['Reject'].click()
    assert requests == [(1, True), (1, False)]
    assert original.text == 'The red car is large.'
    view.close()


def test_old_card_cannot_select_or_resolve_a_new_model_index():
    from app.src.review_model import build_review
    from app.src.suggestions import resolve
    app = QApplication.instance() or QApplication([])
    original = revision('The red car is large.')
    model = build_review(original, original.revise('The blue car is small.'))
    view = ReviewView()
    view.set_model(model)
    old_card = view.cards[0]
    old_accept = next(button for button in old_card.findChildren(QPushButton)
                      if button.text() == 'Accept')
    requests, selected = [], []
    view.requested.connect(lambda index, accept: requests.append((index, accept)))
    view.selected.connect(selected.append)
    original, incoming = resolve(model.original, model.incoming, model.edits[0], True)
    view.set_model(build_review(original, incoming))
    old_accept.click()
    old_card.clicked.emit()
    assert not requests
    assert not selected
    next(button for button in view.cards[0].findChildren(QPushButton)
         if button.text() == 'Accept').click()
    assert requests == [(0, True)]
    view.close()


@pytest.mark.parametrize(('caption', 'expected', 'speaker'), [
    ('Accept All', 'The blue car is small and new.', 'MS. SIEMENS'),
    ('Reject All', 'The blue car is large and old.', 'MR. LEISER'),
])
def test_bulk_review_resolves_remaining_suggestions_in_one_history_step(
        tmp_path, monkeypatch, caption, expected, speaker):
    from copy import deepcopy
    from app.src.document_view import DocumentView
    from app.tests.test_native_projects import native_doc

    app = QApplication.instance() or QApplication([])
    doc, _ = native_doc(tmp_path, monkeypatch)
    original = speakers(['MS. SIEMENS'] * 8 + ['MR. LEISER'] * 2)
    original = original.replace(0, 0, 'The red car is large and old.\n')
    doc.set_text('original', original.text, revision=original)
    doc.set_text('incoming', original.text, revision=original)
    view = DocumentView(doc)
    proposal = original.text.replace('red car is large and old', 'blue car is small and new')
    view.receive(proposal.replace('MS. SIEMENS:', 'SPEAKER 3:').replace('MR. LEISER:', 'SPEAKER 3:'), [])
    view.review(0, True)
    before = doc.native.original, doc.native.incoming, deepcopy(doc.native.review)
    doc.dirty = False
    assert len(view.review_model.edits) == 4
    view.diff_view.filter_speaker('SPEAKER 3')
    assert len(view.diff_view.visible_indices) == 2

    buttons = {button.text(): button for button in view.diff_view.findChildren(QPushButton)}
    assert caption in buttons
    assert buttons[caption].isEnabled()
    buttons[caption].click()
    if view._review_worker is not None:
        assert view._review_worker.wait(5000)
        app.processEvents()

    assert doc.original == doc.incoming
    assert doc.original.splitlines()[0] == expected
    locations = doc.native.review['locations']
    assert sum(location['resolved'] for location in locations) == 2
    assert all(doc.incoming[location['start']:location['end']] == speaker for location in locations[-2:])
    assert not view.review_model.edits
    assert all(not buttons[label].isEnabled() for label in ('Accept All', 'Reject All'))
    assert doc.dirty
    view.undo_review()
    assert (doc.native.original, doc.native.incoming, doc.native.review) == before
    assert len(view.review_model.edits) == 4
    view.redo_review()
    assert doc.original == doc.incoming
    assert doc.original.splitlines()[0] == expected
    view.close()


@pytest.mark.parametrize('risk', ['zero matches', 'shared default'])
def test_accept_all_confirms_questionable_automatic_speaker_names(tmp_path, monkeypatch, risk):
    from PySide6.QtWidgets import QMessageBox
    from app.src.document_view import DocumentView
    from app.src.suggestion_filter import begin_review, override_speaker
    from app.tests.test_native_projects import native_doc

    app = QApplication.instance() or QApplication([])
    doc, _ = native_doc(tmp_path, monkeypatch)
    original = speakers(['MS. SIEMENS'] * 4 + ['MR. LEISER'] * 2)
    state = doc.native
    state.original = original
    lines = original.text.splitlines(keepends=True)
    proposal = ''.join(line.replace('MS. SIEMENS:', f'SPEAKER {1 if i < 2 else 2}:')
                       for i, line in enumerate(lines))
    # Give one tag a pending attribution while retaining frozen evidence from
    # the aligned passages. Saved reviews can carry both of these defaults.
    begin_review(state, proposal)
    override_speaker(state, 'SPEAKER 1', 'MR. LEISER')
    state.review['evidence']['speakers']['SPEAKER 1']['mapped'] = state.review['overrides'].pop('SPEAKER 1')
    if risk == 'shared default':
        summary = state.review['evidence']['speakers']['SPEAKER 1']
        summary['counts']['MR. LEISER'] = 3
        override_speaker(state, 'SPEAKER 2', 'MR. LEISER')
        state.review['evidence']['speakers']['SPEAKER 2']['mapped'] = state.review['overrides'].pop('SPEAKER 2')
    view = DocumentView(doc)
    before = state.original
    prompts = []

    def cancel(*args, **kwargs):
        prompts.append(args[2])
        return QMessageBox.Cancel

    monkeypatch.setattr(QMessageBox, 'question', cancel)
    view.diff_view.bulk_buttons[0].click()
    assert len(prompts) == 1 and 'SPEAKER 1' in prompts[0]
    assert not doc.busy and state.original == before and view.review_model.edits
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.Yes)
    view.diff_view.bulk_buttons[0].click()
    assert view._review_worker.wait(5000)
    app.processEvents()
    assert state.original.text == state.incoming.text and not view.review_model.edits
    view.undo_review()
    assert state.original == before and view.review_model.edits
    view.close()


def test_page_fit_changes_display_scale_without_reflow():
    from app.src.page_view import PageView
    from app.src.native_editor import NativeTranscriptEditor
    from PySide6.QtGui import QFont
    app = QApplication.instance() or QApplication([])
    editor = NativeTranscriptEditor(QFont('Courier New', 12))
    editor.setPlainText('     Q    ' + 'Example wording. ' * 100)
    view = PageView(editor)
    view.resize(700, 700)
    view.show()
    app.processEvents()
    before = [(p.page,p.number,p.position,p.text) for p in editor.page_lines()]
    view.resize(500, 700)
    app.processEvents()
    assert view.transform().m11() < 1
    assert view.transform().m11() * editor.width() <= view.viewport().width()+1
    assert [(p.page,p.number,p.position,p.text) for p in editor.page_lines()] == before
    view.close()
