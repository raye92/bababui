import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from html import unescape
import re
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextCursor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QProgressBar, QPushButton
from app.src.review_view import ReviewView, change_diff
from app.src.suggestions import Suggestion, resolve
from app.tests.test_suggestion_filter import speakers
from app.tests.test_suggestions import revision
from app.tests.test_native_editor import native_window


def test_speaker_summary_is_fixed_and_cards_filter_to_mismatches():
    from types import SimpleNamespace
    from app.src.suggestion_filter import begin_review
    app = QApplication.instance() or QApplication([])
    original = speakers(['MS. SIEMENS']*8 + ['MR. LEISER']*2)
    state = SimpleNamespace(original=original)
    begin_review(state, original.text.replace('MS. SIEMENS:', 'SPEAKER 3:').replace('MR. LEISER:', 'SPEAKER 3:'))
    view = ReviewView()
    view.set_revisions(original, state.incoming, review=state.review)
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


@pytest.mark.parametrize('accept', [False, True])
def test_repeated_thank_you_counts_as_one_pending_speaker_change(accept):
    from types import SimpleNamespace
    from app.src.suggestion_filter import begin_review, track_decision

    app = QApplication.instance() or QApplication([])
    first = 'THE WITNESS: I brought the report.\nTHE WITNESS: The date is correct.\nTHE WITNESS: Thank you.\n'
    original = revision(first + ': Thank you.').insert_field(len(first), 'EZ SPEAKER 02', 'MS. JONES')
    state = SimpleNamespace(original=original)
    begin_review(state, original.text.replace('THE WITNESS:', 'SPEAKER 2:').replace('MS. JONES:', 'SPEAKER 2:'))
    view = ReviewView()
    view.set_revisions(original, state.incoming, review=state.review)
    assert view.speaker_scroll.widget().findChild(QProgressBar).format() == '2 matches · 1 mismatch'
    assert '1 to review' in view.summary.text()
    view.filter_speaker('SPEAKER 2')
    assert len(view.visible_indices) == 1
    assert any('Speaker attribution · Needs review' in label.text()
               for label in view.cards[view.current].findChildren(QLabel))
    change = view.changes[view.current]
    before = state.incoming.text
    state.original, state.incoming = resolve(original, state.incoming, change, accept)
    track_decision(state.review, change, before, state.incoming.text)
    view.set_revisions(state.original, state.incoming, review=state.review)
    assert view.speaker_scroll.widget().findChild(QProgressBar).format() == '2 matches · 0 mismatches'
    assert '0 to review' in view.summary.text() and not view.visible_indices
    view.close()


@pytest.mark.parametrize('accept_speaker', [False, True])
@pytest.mark.parametrize('wording_first', [False, True])
def test_speaker_fields_and_changed_answer_have_independent_cards(accept_speaker, wording_first):
    app = QApplication.instance() or QApplication([])
    original = revision(': Yes.').insert_field(0, 'EZ SPEAKER 02', 'JONES')
    incoming = revision(': Yeah.').insert_field(0, 'EZ SPEAKER 03', 'LEE')
    view = ReviewView()
    view.set_revisions(original, incoming)
    speaker, wording = view.changes
    assert (speaker.kind, wording.kind) == ('speaker', 'text')
    (a, b, c, d), = speaker.ranges
    assert (original.text[a:b], incoming.text[c:d]) == ('JONES', 'LEE')
    assert '1 to review' in view.summary.text()
    assert 'Needs review' in view.cards[0].findChild(QLabel).text()
    first = wording if wording_first else speaker
    original, incoming = resolve(original, incoming, first, not accept_speaker if wording_first else accept_speaker)
    view.set_revisions(original, incoming)
    remaining, = view.changes
    if wording_first:
        assert '1 to review' in view.summary.text()
        assert original.text.startswith('JONES:') and incoming.text.startswith('LEE:')
        original, incoming = resolve(original, incoming, remaining, accept_speaker)
    else:
        assert '0 to review' in view.summary.text()
        assert original.text.endswith(' Yes.') and incoming.text.endswith(' Yeah.')
        original, incoming = resolve(original, incoming, remaining, not accept_speaker)
    chosen = 'LEE: Yes.' if accept_speaker else 'JONES: Yeah.'
    assert original.text == incoming.text == chosen
    assert original.elements[0].name == incoming.elements[0].name == (
        'EZ SPEAKER 03' if accept_speaker else 'EZ SPEAKER 02')
    view.close()


def test_different_native_speaker_slots_with_the_same_display_name_are_identifiable():
    app = QApplication.instance() or QApplication([])
    before = revision(': Thank you.').insert_field(0, 'EZ SPEAKER 02', 'SPEAKER 2')
    after = revision(': Thank you.').insert_field(0, 'EZ SPEAKER 03', 'SPEAKER 2')
    view = ReviewView()
    view.set_revisions(before, after)
    assert '1 to review' in view.summary.text()
    card, = view.cards
    assert any('EZ SPEAKER 02' in label.text() and 'EZ SPEAKER 03' in label.text()
               for label in card.findChildren(QLabel))
    view.close()


def test_speaker_dropdown_keeps_automatic_match_when_scrolling_and_lists_actual_labels():
    from types import SimpleNamespace
    from app.src.suggestion_filter import begin_review, override_speaker

    app = QApplication.instance() or QApplication([])
    original = speakers(['MR. REFF'] + ['MS. LIN'] * 10)
    original = original._replace(len(original.text), len(original.text), 'THE WITNESS: I found it.\n')
    for field, value in [
        ('CREATION DATE IN WORDS', 'October 28, 2026'),
        ('CREATION DAY OF WEEK', 'Wednesday'),
        ('DEPONENT', 'STEPHANE JOHNSON, M.D.'),
    ]:
        original = original._replace(0, 0, '\n').insert_field(0, field, value)
    state = SimpleNamespace(original=original)
    begin_review(state, original.text.replace('MS. LIN:', 'SPEAKER 2:'))
    view = ReviewView()
    view.set_revisions(original, state.incoming, review=state.review)
    view.show()
    app.processEvents()
    (combo,) = view.findChildren(QComboBox)
    assert {combo.itemData(i) for i in range(combo.count())} == {None, 'MR. REFF', 'MS. LIN', 'THE WITNESS'}
    assert combo.currentData() == 'MS. LIN'
    assert '10 matches' in view.summary.text()

    def select_name(speaker, name):
        override_speaker(state, speaker, name)
        view.set_revisions(original, state.incoming, review=state.review)

    view.mapping_requested.connect(select_name)
    point = combo.rect().center()
    event = QWheelEvent(point, combo.mapToGlobal(point), QPoint(), QPoint(0, 120),
                        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    QApplication.sendEvent(combo, event)
    assert combo.currentData() == 'MS. LIN' and state.review['overrides'] == {}
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key_Up)
    assert state.review['overrides'] == {'SPEAKER 2': 'MR. REFF'}
    assert '0 matches' in view.summary.text()
    view.close()


def test_speaker_dropdown_can_type_a_name_without_rejecting_an_edit(native_window, tmp_path):
    from app.tests.test_native_editor import source_zip

    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    view.editor.setPlainText('The car is red.\n' + speakers(['MS. LIN'] * 3 + ['DR. DAWSON']).text)
    original = view.document.original
    view.receive(original.replace('red', 'blue').replace('MS. LIN:', 'SPEAKER 1:'), [])
    combo = view.diff_view.speaker_scroll.widget().findChild(QComboBox)
    native_window.activateWindow()
    combo.setFocus()
    QApplication.processEvents()
    assert combo.hasFocus() and combo.currentText() == 'MS. LIN'
    assert view.diff_view.has_current

    QTest.keyClick(combo, Qt.Key_D)
    if view._review_worker is not None:
        assert view._review_worker.wait(5000)
        QApplication.processEvents()
    assert view.document.native.review['overrides'] == {'SPEAKER 1': 'DR. DAWSON'}
    assert view.document.incoming.startswith('The car is blue.')


def test_review_skips_new_turns_for_known_speaker_and_keeps_sidebar_diff_colors():
    from types import SimpleNamespace
    from app.src.suggestion_filter import begin_review

    app = QApplication.instance() or QApplication([])
    original = speakers(['MS. SIEMENS', 'MS. SIEMENS', 'MR. LEISER', 'MR. LEISER'])
    lines = original.text.splitlines()
    proposal = '\n'.join(
        ['     SPEAKER 3:' + line.split(':', 1)[1] for line in lines[:3]]
        + ['     SPEAKER 7:' + lines[3].split(':', 1)[1],
           '     SPEAKER 3: I have an entirely new statement.', ''])
    state = SimpleNamespace(original=original)
    begin_review(state, proposal)
    view = ReviewView()
    view.set_revisions(original, state.incoming, review=state.review)
    assert len(view.changes) > 2
    view.filter_speaker('SPEAKER 3')
    assert len(view.visible_indices) == 1
    assert 'MR. LEISER' in plain_preview(view.cards[view.current].findChild(QLabel, 'comparison').text())
    view.filter_speaker('SPEAKER 7')
    assert len(view.visible_indices) == 1
    card = view.cards[view.current]
    comparison = card.findChild(QLabel, 'comparison').text()
    assert '#ffe08a' not in comparison
    assert '#ffd7d5' in comparison and '#ccffd8' in comparison
    assert any('Needs review' in label.text() for label in card.findChildren(QLabel))
    label = next(label for label in view.speaker_scroll.widget().findChildren(QLabel)
                 if 'SPEAKER 7' in label.text())
    assert '#ffe08a' not in label.styleSheet()
    view.close()


def test_literal_speaker_mismatch_is_one_review_decision():
    from types import SimpleNamespace
    from app.src.suggestion_filter import begin_review

    app = QApplication.instance() or QApplication([])
    original = revision('MS. LIN: This testimony refers to the signed contract.\n'
                        'MS. LIN: The schedule was attached to the last page.\n'
                        'MS. LIN JONES: Everyone received a copy the next morning.')
    state = SimpleNamespace(original=original)
    begin_review(state, original.text.replace('MS. LIN:', 'SPEAKER 1:').replace('MS. LIN JONES:', 'SPEAKER 1:'))
    view = ReviewView()
    view.set_revisions(original, state.incoming, review=state.review)
    view.filter_speaker('SPEAKER 1')
    assert len(view.visible_indices) == 1
    ((a, b, c, d),) = view.changes[view.current].ranges
    assert (original.text[a:b], state.incoming.text[c:d]) == ('MS. LIN JONES', 'MS. LIN')
    _, rejected = resolve(original, state.incoming, view.changes[view.current], False)
    assert rejected.text == original.text
    view.close()


@pytest.mark.parametrize('height', [480, 904])
def test_long_speaker_menu_scrolls_without_covering_decisions(height):
    from types import SimpleNamespace
    from app.src.suggestion_filter import begin_review

    app = QApplication.instance() or QApplication([])
    original = speakers(['MS. SIEMENS'] * 12)
    state = SimpleNamespace(original=original)
    begin_review(state, '\n'.join(line.replace('MS. SIEMENS:', f'SPEAKER {i}:')
                                 for i, line in enumerate(original.text.split('\n'), 1)))
    view = ReviewView()
    view.resize(340, height)
    view.set_revisions(original, state.incoming, review=state.review)
    view.show()
    view.filter_speaker('SPEAKER 4')
    app.processEvents()
    assert view.height() == height
    assert view.speaker_scroll.height() > height // 3
    assert view.speaker_scroll.verticalScrollBar().maximum() > 0
    buttons = [b for b in view.findChildren(QPushButton) if b.text() in ('Accept', 'Reject')]
    assert len(buttons) == 2
    for button in buttons:
        assert not view.scroll.isAncestorOf(button)
        assert button.isEnabled() and button.mapTo(view, button.rect().bottomLeft()).y() < view.height()
    view.close()


@pytest.mark.parametrize('long_preview', [False, True], ids=['short', 'scrolling'])
def test_decisions_follow_preview_until_it_needs_to_scroll(long_preview):
    app = QApplication.instance() or QApplication([])
    before, after = 'The car is red.', 'The car is blue.'
    if long_preview:
        before += '\n' + '\n'.join(f'Additional wording {i}.' for i in range(48))
    original = revision(before)
    view = ReviewView()
    view.resize(300, 800)
    view.set_revisions(original, original.revise(after))
    if long_preview:
        view.select(len(view.changes) - 1)
    view.show()
    app.processEvents()
    button = next(b for b in view.findChildren(QPushButton) if b.text() == 'Accept')
    y = button.mapTo(view, QPoint()).y()
    if long_preview:
        assert view.scroll.verticalScrollBar().maximum() > 0
        assert view.height() - 75 < y < view.height() - button.height()
    else:
        assert view.scroll.verticalScrollBar().maximum() == 0
        assert y < view.height() // 2
    view.close()


def highlighted_text(html):
    return [unescape(re.sub(r'<[^>]*>', '', text))
            for text in re.findall(r'<b\b[^>]*>(.*?)</b>', html, re.DOTALL)]


def plain_preview(html):
    return unescape(re.sub(r'<[^>]*>', '', html.replace('<br>', '\n')))


@pytest.mark.parametrize('before, after, span, expected', [
    ('She is talking here.', 'She is speaking here.', (7, 11, 7, 12), ['talking', 'speaking']),
    ('She is talking here.', 'She is tallking here.', (10, 10, 10, 11), ['l']),
    ('She is tallking here.', 'She is talking here.', (10, 11, 10, 10), ['l']),
])
def test_replacements_highlight_whole_words_and_one_sided_edits_stay_exact(before, after, span, expected):
    original = revision(before)
    change = Suggestion(original, original.revise(after), (span,))
    (_, preview), = change_diff(change)
    assert highlighted_text(preview) == expected


def test_paragraph_join_highlights_whole_word_on_both_sides():
    from app.src.review_model import build_review
    from app.tests.test_inline_review import widget
    original = revision('     Q    \n     MR. GUERRA:  This is regarding my client.')
    incoming = original.revise('     Q    Okay.  Excellent.  So this is regarding my client.')
    model = build_review(original, incoming)
    (edit,) = model.edits
    assert edit.kind == 'structure'
    (_, preview), = change_diff(edit)
    removed, added = highlighted_text(preview)
    assert removed.endswith(' This')
    assert added.endswith(' this')
    inline = widget(model)
    inline.focus_edit(0)
    cursor = QTextCursor(inline.document())
    for side, word, color in [('original', ' This', '#f2aba7'), ('incoming', ' this', '#9edcb0')]:
        start = getattr(model, side).text.index(word)
        for offset in range(len(word)):
            cursor.setPosition(inline.display_position(side, start + offset))
            cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            assert cursor.charFormat().background().color().name() == color
    inline.close()
    assert resolve(original, incoming, edit, True)[0].text == incoming.text
    assert resolve(original, incoming, edit, False)[1].text == original.text


def test_preview_uses_authoritative_pair_without_splitting_word_changes():
    original = revision("You're familiar with the case of Timothy Welch?")
    incoming = original.revise("Okay. And you're familiar with the case of Timothy Walsh?")
    lead = Suggestion(original, incoming, ((0, 1, 0, 11),))
    name = Suggestion(original, incoming, ((41, 46, 51, 56),))
    (_, preview), = change_diff(lead)
    assert highlighted_text(preview) == ["You're", "Okay. And you're"]
    assert plain_preview(preview) == "You'reOkay. And you're familiar with the case of Timothy Welch?"
    assert 'Walsh' not in plain_preview(preview)
    (_, preview), = change_diff(name)
    assert highlighted_text(preview) == ['Welch', 'Walsh']
    assert plain_preview(preview) == original.text.replace('Welch', 'WelchWalsh')
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
    assert plain_preview(preview).count('word19') == plain_preview(preview).count('tail0') == 1
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
    buttons = {b.text(): b for b in view.findChildren(QPushButton) if b.text() in ('Accept', 'Reject')}
    assert set(buttons) == {'Accept', 'Reject'}
    buttons['Accept'].click()
    buttons['Reject'].click()
    assert requests == [(1, True), (1, False)]
    assert original.text == 'The red car is large.'
    view.close()


def test_old_card_cannot_select_a_new_model_index():
    from app.src.review_model import build_review
    from app.src.suggestions import resolve
    app = QApplication.instance() or QApplication([])
    original = revision('The red car is large.')
    model = build_review(original, original.revise('The blue car is small.'))
    view = ReviewView()
    view.set_model(model)
    old_card = view.cards[0]
    requests, selected = [], []
    view.requested.connect(lambda index, accept: requests.append((index, accept)))
    view.selected.connect(selected.append)
    original, incoming = resolve(model.original, model.incoming, model.edits[0], True)
    view.set_model(build_review(original, incoming))
    old_card.clicked.emit()
    assert not requests
    assert not selected
    next(button for button in view.findChildren(QPushButton) if button.text() == 'Accept').click()
    assert requests == [(0, True)]
    view.close()


@pytest.mark.parametrize(('caption', 'expected', 'speaker'), [
    ('Accept All', 'The blue car is small and new.', 'MS. SIEMENS'),
    ('Reject All', 'The blue car is large and old.', 'MR. LEISER'),
])
def test_bulk_review_resolves_remaining_suggestions_in_one_history_step(
        native_window, tmp_path, monkeypatch, caption, expected, speaker):
    from copy import deepcopy
    from app.tests.test_native_projects import native_doc

    app = QApplication.instance() or QApplication([])
    doc, _ = native_doc(tmp_path, monkeypatch)
    original = speakers(['MS. SIEMENS'] * 8 + ['MR. LEISER'] * 2)
    original = original.replace(0, 0, 'The red car is large and old.\n')
    doc.set_text('original', original.text, revision=original)
    doc.set_text('incoming', original.text, revision=original)
    view = native_window.add_document(doc)
    proposal = original.text.replace('red car is large and old', 'blue car is small and new')
    view.receive(proposal.replace('MS. SIEMENS:', 'SPEAKER 3:').replace('MR. LEISER:', 'SPEAKER 3:'), [])
    view.review(0, True)
    before = doc.native.original, doc.native.incoming, deepcopy(doc.native.review)
    doc.dirty = False
    assert len(view.review_model.edits) == 4
    view.diff_view.filter_speaker('SPEAKER 3')
    assert len(view.diff_view.visible_indices) == 2

    actions = {action.text(): action for action in native_window.edit_btn.menu().actions()}
    assert not {b.text() for b in native_window.findChildren(QPushButton)} & {'Accept All', 'Reject All'}
    assert actions[caption].isVisible() and actions[caption].isEnabled()
    actions[caption].trigger()
    if view._review_worker is not None:
        assert view._review_worker.wait(5000)
        app.processEvents()

    assert doc.original == doc.incoming
    assert doc.original.splitlines()[0] == expected
    locations = doc.native.review['locations']
    assert sum(location['resolved'] for location in locations) == 2
    assert all(doc.incoming[location['start']:location['end']] == speaker for location in locations[-2:])
    assert not view.review_model.edits
    assert all(not actions[label].isEnabled() for label in ('Accept All', 'Reject All'))
    assert doc.dirty
    view.undo_review()
    assert (doc.native.original, doc.native.incoming, doc.native.review) == before
    assert len(view.review_model.edits) == 4
    view.redo_review()
    assert doc.original == doc.incoming
    assert doc.original.splitlines()[0] == expected


@pytest.mark.parametrize('risk', ['zero matches', 'shared default'])
def test_accept_all_confirms_questionable_automatic_speaker_names(native_window, tmp_path, monkeypatch, risk):
    from PySide6.QtWidgets import QMessageBox
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
    view = native_window.add_document(doc)
    action = next(action for action in native_window.edit_btn.menu().actions()
                  if action.text() == 'Accept All')
    before = state.original
    prompts = []

    def cancel(*args, **kwargs):
        prompts.append(args[2])
        return QMessageBox.Cancel

    monkeypatch.setattr(QMessageBox, 'question', cancel)
    action.trigger()
    assert len(prompts) == 1 and 'SPEAKER 1' in prompts[0]
    assert not doc.busy and state.original == before and view.review_model.edits
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.Yes)
    action.trigger()
    assert view._review_worker.wait(5000)
    app.processEvents()
    assert state.original.text == state.incoming.text and not view.review_model.edits
    view.undo_review()
    assert state.original == before and view.review_model.edits


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
