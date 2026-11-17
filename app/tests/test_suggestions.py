import pytest

from app.src.casecat.anchors import Revision, AnchoredSpan
from app.src.casecat.elements import NativeElement
from app.src.review_model import build_review
from app.src.suggestions import preview_ranges, suggestions, propose, resolve


def test_invalid_proposed_field_values_are_rejected_before_review():
    import pytest
    old = revision('one ').insert_field(4, 'NAME', 'Jane')
    for value in ('Ja \noe', 'Ja😀ne'):
        with pytest.raises(ValueError, match='single line|Windows-1252'):
            propose(old, 'one ' + value)


def revision(text):
    return Revision((AnchoredSpan('test', (0,), (), text),))


def test_layout_only_is_not_a_proposal():
    old = revision('Q What is your name?\nA Jane.\n')
    new = propose(old, '     Q    What is your name?\n     A    Jane.\n')
    assert new == old
    assert suggestions(old, new) == []


@pytest.mark.parametrize('trailing', ['', '  '])
@pytest.mark.parametrize('added', [True, False])
def test_answer_opening_edit_keeps_native_label_out_of_highlight(trailing, added):
    question = 'Do you know what part of body that relates to?'
    label = '     A    '
    body = 'I would have to go into his subjective reports.'
    before, after = ('', 'Well, ') if added else ('Well, ', '')
    start = len(question + trailing + '\n')
    symbol = NativeElement(start, start + len(label), 'symbol', '160300', source=1)
    original = Revision((AnchoredSpan('test', (0,), (), question + trailing + '\n' + label + before + body),),
                        (symbol,))
    incoming = propose(original, question + '\n' + label + after + body)
    edits = build_review(original, incoming).edits
    pairs = [(original.text[a:b], incoming.text[c:d])
             for edit in edits for a, b, c, d in preview_ranges(edit)]

    assert pairs == ([(trailing, '')] if trailing else []) + [(before, after)]
    assert incoming.elements[0].source == symbol.source
    accepted, _ = resolve(original, incoming, edits[-1], True)
    _, rejected = resolve(original, incoming, edits[-1], False)
    assert accepted.text == question + trailing + '\n' + label + after + body
    assert rejected.text == question + '\n' + label + before + body


def test_negated_off_record_note_does_not_anchor_paragraph_alignment():
    old = revision('Q What happened before the examination?\n'
                   '(The parties did not go off the record.)\n'
                   '     A    I waited for the court reporter to return.\n'
                   'Q What happened next?\n')
    incoming = ('Q What happened before the examination?\n'
                'A I waited for the court reporter to return.\n'
                '(Off the record.)\n'
                'Q What happened next?\n')
    assert propose(old, incoming).text == incoming.replace('A I waited', '     A    I waited')


def test_independent_words_across_all_paragraphs():
    old = revision('Q Is the car red and large?\nA Yes it is.\n')
    new = propose(old, '     Q    Is the car blue and small?\n     A    No it is.\n')
    changes = suggestions(old, new)
    assert len(changes) == 3
    old, new = resolve(old, new, changes[1], True)
    assert 'red and small' in old.text
    changes = suggestions(old, new)
    old, new = resolve(old, new, changes[0], False)
    assert 'red and small' in new.text
    old, new = resolve(old, new, suggestions(old, new)[0], True)
    assert old == new
    assert 'No it is.' in old.text


def test_structural_change_and_repeated_words():
    old = revision('One word word. Two sentences.')
    new = propose(old, 'One word word.\nTwo sentences.')
    changes = suggestions(old, new)
    assert len(changes) == 1
    assert changes[0].kind == 'structure'
    accepted, pending = resolve(old, new, changes[0], True)
    assert accepted == pending
    assert accepted.text == new.text


@pytest.mark.parametrize('separated, joined', [
    ('correspond responding', 'corresponding'),
    ('note book', 'notebook'),
])
@pytest.mark.parametrize('join', [True, False])
def test_preview_highlights_both_words_when_an_edit_joins_or_splits_them(separated, joined, join):
    before, after = (separated, joined) if join else (joined, separated)
    old, new = revision(f'The {before} was here.'), revision(f'The {after} was here.')
    change, = suggestions(old, new)
    (a, b, c, d), = change.ranges
    assert (c == d) if join else (a == b)
    (a, b, c, d), = preview_ranges(change)
    assert (old.text[a:b], new.text[c:d]) == (before, after)


@pytest.mark.parametrize('reverse', [False, True])
def test_join_with_a_spelling_correction_is_one_decision(reverse):
    separated = 'His sleep was not rest full and he kept the red report.'
    joined = 'His sleep was not restful, and he kept the blue report.'
    before, after = (joined, separated) if reverse else (separated, joined)
    original = revision(before)
    incoming = original.revise(after)

    joined_word, color = suggestions(original, incoming)
    a, b, c, d = preview_ranges(joined_word)[0]
    assert (before[a:b], after[c:d]) == (('restful,', 'rest full') if reverse else ('rest full', 'restful,'))
    accepted, _ = resolve(original, incoming, joined_word, True)
    _, rejected = resolve(original, incoming, joined_word, False)
    assert accepted.text == (separated.replace('red', 'blue') if reverse else joined.replace('blue', 'red'))
    assert rejected.text == (joined.replace('blue', 'red') if reverse else separated.replace('red', 'blue'))
    assert len(color.ranges) == 1


def test_join_with_a_correction_leaves_the_next_sentence_independent():
    original = revision('His sleep was not rest full. Word.')
    incoming = original.revise('His sleep was not restful. Back.')
    joined_word, next_sentence = suggestions(original, incoming)
    accepted, _ = resolve(original, incoming, joined_word, True)
    assert accepted.text == 'His sleep was not restful. Word.'
    accepted, _ = resolve(original, incoming, next_sentence, True)
    assert accepted.text == 'His sleep was not rest full. Back.'


@pytest.mark.parametrize('opening,closing', [('"', '"'), ('“', '”'), ('‘', '’'), ("'", "'")])
@pytest.mark.parametrize('remove', [False, True])
def test_quote_marks_are_one_decision_and_keep_nearby_wording_independent(opening, closing, remove):
    plain = "They called it activities of Daily Living, then filed it under red."
    quoted = f"They called it {opening}Activities of Daily Living,{closing} then filed it under blue."
    before, after = (quoted, plain) if remove else (plain, quoted)
    original = revision(before)
    incoming = original.revise(after)

    quotation, color = suggestions(original, incoming)
    assert len(quotation.ranges) == 2
    accepted, _ = resolve(original, incoming, quotation, True)
    _, rejected = resolve(original, incoming, quotation, False)
    assert accepted.text == (plain.replace('red.', 'blue.') if remove else quoted.replace('blue.', 'red.'))
    assert rejected.text == (quoted.replace('blue.', 'red.') if remove else plain.replace('red.', 'blue.'))
    assert len(color.ranges) == 1


def test_adjacent_quotations_remain_separate():
    original = revision('The labels were blue green and rough paper on the box.')
    incoming = original.revise('The labels were "blue green" and "rough paper" on the box.')
    first_quote, second_quote = suggestions(original, incoming)
    accepted, _ = resolve(original, incoming, first_quote, True)
    assert accepted.text == 'The labels were "blue green" and rough paper on the box.'
    accepted, _ = resolve(original, incoming, second_quote, True)
    assert accepted.text == 'The labels were blue green and "rough paper" on the box.'


def test_quote_pairs_separated_by_one_space_can_be_accepted_individually():
    original = revision('He said alpha beta, then left.')
    incoming = original.revise('He said "alpha" "beta", then left.')
    first, second = suggestions(original, incoming)
    first_accepted, _ = resolve(original, incoming, first, True)
    second_accepted, _ = resolve(original, incoming, second, True)
    assert first_accepted.text == 'He said "alpha" beta, then left.'
    assert second_accepted.text == 'He said alpha "beta", then left.'


def test_single_quotation_keeps_an_internal_possessive_apostrophe():
    from app.src.suggestion_filter import automatic_reason

    original = revision("He mentioned the witnesses' lawyers in the notes.")
    incoming = original.revise("He mentioned 'the witnesses' lawyers' in the notes.")
    quotation, = suggestions(original, incoming)
    assert not automatic_reason(quotation)
    _, rejected = resolve(original, incoming, quotation, False)
    assert rejected.text == original.text


def test_accepting_quotation_keeps_unrelated_wording_and_the_existing_audio_span():
    shared = AnchoredSpan('middle', (1,), (), 'red bottle had ')
    original = Revision((AnchoredSpan('start', (0,), (), 'He said the '), shared,
                         AnchoredSpan('end', (2,), (), 'cracked inside.')))
    incoming = original.revise('He said the "red bottle had leaked inside."')

    quotation, wording = suggestions(original, incoming)
    accepted, _ = resolve(original, incoming, quotation, True)
    assert accepted.text == 'He said the "red bottle had cracked inside."'
    assert shared in accepted.spans
    accepted, _ = resolve(original, incoming, wording, True)
    assert accepted.text == 'He said the red bottle had leaked inside.'


def test_inch_marks_are_not_grouped_as_quotations():
    original = revision('The box measured 5" by 6".')
    incoming = original.revise('The box measured 5 by 6.')
    first, _ = suggestions(original, incoming)
    accepted, _ = resolve(original, incoming, first, True)
    assert accepted.text == 'The box measured 5 by 6".'


def test_leading_elision_and_possessive_are_independent_apostrophe_edits():
    original = revision("It was 'cause the witnesses' names changed.")
    incoming = original.revise('It was cause the witnesses names changed.')
    first, _ = suggestions(original, incoming)
    accepted, _ = resolve(original, incoming, first, True)
    assert accepted.text == "It was cause the witnesses' names changed."


def test_linked_fields_are_one_decision():
    old = revision('Said: ').insert_field(6, 'SPEAKER', 'Jane')
    old = old.replace(len(old.text), len(old.text), ' and ')
    old = old.insert_field(len(old.text), 'SPEAKER', 'Jane')
    new = old.set_field('SPEAKER', 'Joan')
    changes = suggestions(old, new)
    assert len(changes) == 1
    accepted, pending = resolve(old, new, changes[0], True)
    assert accepted == pending
    assert accepted.text.count('Joan') == 2


def test_accept_all_keeps_inserted_wording_at_its_destination_stroke():
    from app.src.suggestions import resolve_all

    old = Revision((AnchoredSpan('first', (0,), (), 'Alpha '),
                    AnchoredSpan('second', (1,), (), 'beta gamma.')))
    incoming = propose(old, 'Alpha inserted beta delta.')
    ranges = tuple(span for change in suggestions(old, incoming) for span in change.ranges)

    accepted, pending = resolve_all(old, incoming, ranges, True)

    assert accepted == pending
    assert accepted.text == 'Alpha inserted beta delta.'
    assert next(span.stroke_refs for span in accepted.spans if 'inserted' in span.content) == (1,)


def test_stale_decision_is_rejected():
    import pytest
    old = revision('red and large')
    new = propose(old, 'blue and small')
    changes = suggestions(old, new)
    old, new = resolve(old, new, changes[0], True)
    with pytest.raises(ValueError, match='stale'):
        resolve(old, new, changes[1], True)


def test_review_undo_redo_and_recovery(tmp_path, monkeypatch):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.tests.test_native_projects import native_doc
    from app.src.document_view import DocumentView
    from app.src.documents import save_document, open_document
    app = QApplication.instance() or QApplication([])
    doc, _ = native_doc(tmp_path, monkeypatch)
    doc.set_text('original', 'red and large')
    doc.set_text('incoming', doc.original, revision=doc.native.original)
    view = DocumentView(doc)
    view.receive('blue and small', [])
    baseline = doc.native.original, doc.native.incoming
    view.review(0, True)
    assert doc.original == 'blue and large'
    accepted = doc.native.original, doc.native.incoming
    view.undo_review()
    assert (doc.native.original, doc.native.incoming) == baseline
    view.redo_review()
    assert (doc.native.original, doc.native.incoming) == accepted
    target = tmp_path/'pending.bababui'
    save_document(doc, target)
    restored = open_document(target)
    assert len(suggestions(restored.native.original, restored.native.incoming)) == 1
    view.close()


def test_review_undo_menu_available_while_pending(tmp_path, monkeypatch):
    from app.src.main import TranscriptEditor
    from app.src import documents
    from app.tests.test_native_casecat import zip_bytes, job_files
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    source = tmp_path/'example.zip'
    source.write_bytes(zip_bytes(job_files(audio=False)))
    window = TranscriptEditor(session_path=tmp_path/'session.json')
    window.import_zip(0, source)
    window.current.receive('Changed text.', [])
    assert window.edit_btn.isEnabled()
    window.close()


def test_field_removal_can_be_accepted_or_rejected():
    old = revision('Said: ').insert_field(6, 'SPEAKER', 'Jane')
    old = old.replace(len(old.text), len(old.text), ' went home.')
    new = propose(old, 'Said: went home.')
    change = suggestions(old, new)[0]
    accepted, pending = resolve(old, new, change, True)
    assert accepted.text == pending.text == new.text
    kept, rejected = resolve(old, new, change, False)
    assert kept.text == rejected.text == old.text
    assert len([e for e in rejected.elements if e.kind == 'field']) == 1


def test_repetitive_transcript_compares_only_changed_passages():
    text = ('     Q    Did you see the red car on the road that day?\n     A    Yes I did.\n') * 600
    old = revision(text)
    new = propose(old, text.replace('red', 'blue', 1))
    change, = suggestions(old, new)
    a, b, c, d = change.ranges[0]
    assert (old.text[a:b], new.text[c:d]) == ('red', 'blue')
    assert a == old.text.index('red') and c == new.text.index('blue')
