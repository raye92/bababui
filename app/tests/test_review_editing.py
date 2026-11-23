"""A manual review edit keeps independent decisions and both native revisions."""
import json

import pytest

from app.src import review_model
from app.src.casecat.anchors import AnchoredSpan, Revision
from app.src.suggestions import Suggestion, preview_ranges
from app.tests.test_suggestions import revision


def transaction(*args, **kwargs):
    from app.src.review_editing import edit_review
    return edit_review(*args, **kwargs)


def review(old, new):
    return review_model.build_review(revision(old), revision(new))


def test_shared_edit_keeps_each_sides_audio_and_unrelated_decisions():
    old, new = (Revision((AnchoredSpan(side, (ref,), ('clock',), text),))
                for side, ref, text in [('old', 1, 'red beside large'), ('new', 2, 'blue beside small')])
    model = review_model.build_review(old, new)
    updated, _ = transaction(model, None, 'incoming', 5, 11, 'beyond')
    assert updated.original.text == 'red beyond large'
    assert updated.incoming.text == 'blue beyond small'
    assert len(updated.edits) == 2
    for ref, side in [(1, updated.original), (2, updated.incoming)]:
        assert next(span.stroke_refs for span in side.spans if span.content == 'beyond') == (ref,)


@pytest.mark.parametrize('side,expected', [('incoming', ('a cat ran', 'a fox ran')),
                                            ('original', ('a fox ran', 'a dog ran'))])
def test_colored_edit_only_amends_its_side(side, expected):
    model = review('a cat ran', 'a dog ran')
    updated, metadata = transaction(model, None, side, 2, 5, 'fox')
    assert (updated.original.text, updated.incoming.text) == expected
    reopened = review_model.build_review(updated.original, updated.incoming, review=json.loads(json.dumps(metadata)))
    assert len(reopened.edits) == 1
    from app.src.review_editing import resolve_review
    for accept in (False, True):
        finished, _ = resolve_review(reopened, metadata, 0, accept)
        assert finished.original.text == finished.incoming.text == expected[int(accept)]


@pytest.mark.parametrize('start,end', [(4, 9), (9, 4)])
def test_crossing_selection_uses_first_color_regardless_of_direction(start, end):
    model = review('cat green and large', 'dog green and small')
    updated, _ = transaction(model, None, 'incoming', start, end, 'NEW')
    assert updated.original.text == 'cat NEW and large'
    assert updated.incoming.text == 'dog NEW and small'
    updated, _ = transaction(model, None, 'incoming', 1, 6, 'X')
    assert updated.original.text == 'cateen and large'
    assert updated.incoming.text == 'dXeen and small'
    assert len(updated.edits) == 2


@pytest.mark.parametrize('affinity,old,first', [('left', 'a xcat ran', 3), ('right', 'a cat ran', 2)])
def test_boundary_affinity_survives_followup_letters(affinity, old, first):
    model = review('a cat ran', 'a dog ran')
    updated, meta = transaction(model, None, 'incoming', 2, 2, 'x', affinity=affinity)
    assert updated.original.text == old and updated.incoming.text == 'a xdog ran'
    assert preview_ranges(updated.edits[0])[0][2] == first
    further, _ = transaction(updated, meta, 'incoming', 3, 3, 'y', affinity='left')
    assert further.original.text == old.replace('x', 'xy')


def test_overlap_chooses_nearest_raw_change_then_earlier_and_preserves_group_after_reopen():
    old, new = revision('abXdeYgh'), revision('abCdeFgh')
    edits = tuple(Suggestion(old, new, ((i, i+1, i, i+1),)) for i in [2, 5])
    model = review_model.ReviewModel(old, new, edits, ())
    updated, meta = transaction(model, None, 'incoming', 3, 4, 'zz')
    reopened = review_model.build_review(updated.original, updated.incoming, review=json.loads(json.dumps(meta)))
    from app.src.review_editing import resolve_review
    result, meta = resolve_review(reopened, meta, 0, True)
    assert result.original.text == 'abCzzeYgh'
    assert len(result.edits) == 1
    result, _ = resolve_review(result, meta, 0, False)
    assert result.original.text == result.incoming.text == 'abCzzeYgh'


def test_linked_field_update_reanchors_all_occurrences_and_next_decision():
    original = revision('Top ').insert_field(4, 'NAME', 'Jane')
    original = original.replace(len(original.text), len(original.text), ' and ')
    original = original.insert_field(len(original.text), 'NAME', 'Jane')
    original = original.replace(len(original.text), len(original.text), ' was red.')
    incoming = original.set_field('NAME', 'Joan').revise(original.text.replace('Jane', 'Joan').replace('red', 'blue'))
    model = review_model.build_review(original, incoming)
    updated, meta = transaction(model, None, 'incoming', 5, 7, 'ulia')
    assert updated.original is original
    assert updated.incoming.text == 'Top Julian and Julian was blue.'
    from app.src.review_editing import resolve_review
    result, meta = resolve_review(updated, meta, 0, True)
    assert result.original.text == 'Top Julian and Julian was red.'
    assert len(result.edits) == 1


def test_native_paste_into_shared_text_preserves_structure_on_each_side():
    model = review('red tail', 'blue tail')
    changed = model.incoming.insert_field(5, 'NEWFIELD', 'June')
    updated, _ = transaction(model, None, 'incoming', 5, 5, 'June', native_revision=changed)
    assert updated.original.text == 'red June' + 'tail'
    assert updated.incoming.text == 'blue June' + 'tail'
    assert updated.original.elements[0].name == updated.incoming.elements[0].name == 'NEWFIELD'
    assert updated.original.definitions == updated.incoming.definitions == (('NEWFIELD', 'June'),)

def test_resolving_native_field_insert_keeps_only_the_chosen_definition():
    from app.src.review_editing import resolve_review
    model = review('old color, more red', 'new color, more blue')
    native = model.incoming.insert_field(1, 'INITIAL', 'J')
    updated, meta = transaction(model, None, 'incoming', 1, 1, 'J', native_revision=native)
    assert updated.original.definitions == ()
    kept, _ = resolve_review(updated, meta, 0, False)
    assert kept.original.text == 'old color, more red'
    assert kept.incoming.text == 'old color, more blue'
    assert kept.incoming.definitions == ()
    assert len(kept.edits) == 1


def test_shared_native_field_reuses_each_sides_pending_value():
    from app.src.casecat.fields import field_values
    from app.src.review_editing import resolve_review
    old = revision('').insert_field(0, 'NAME', 'Jane').replace(4, 4, ': And again. ')
    model = review_model.build_review(old, old.set_field('NAME', 'Jo'))
    pos = len(model.incoming.text)
    changed = model.incoming.insert_field(pos, 'NAME', 'Jo')
    updated, meta = transaction(model, None, 'incoming', pos, pos, 'Jo', native_revision=changed)
    assert updated.original.text == 'Jane: And again. Jane'
    assert updated.incoming.text == 'Jo: And again. Jo'
    assert field_values(updated.original) == {'NAME': 'Jane'}
    assert len(updated.edits) == 1
    assert len(updated.edits[0].ranges) == 2
    finished, _ = resolve_review(updated, meta, 0, False)
    assert finished.incoming.text == finished.original.text == 'Jane: And again. Jane'


def test_notice_moves_saved_decisions_with_testimony():
    from app.src.notice_review import remap_review
    model = review('a cat ran', 'a dog ran')
    updated, meta = transaction(model, None, 'incoming', 2, 5, 'fox')
    shifted = remap_review(meta, lambda p: p+5, lambda p: p+5)
    restored = review_model.build_review(revision('head '+updated.original.text),
                                         revision('head '+updated.incoming.text), review=shifted)
    assert restored.edits[0].ranges == ((7, 10, 7, 10),)


def test_speaker_override_after_manual_wording_keeps_the_edited_decision():
    from app.src.suggestion_filter import begin_review, override_speaker
    from app.tests.test_suggestion_filter import speakers
    from types import SimpleNamespace
    old = speakers(['MS. SIEMENS']*8 + ['MR. LEISER']*2)
    state = SimpleNamespace(original=old, incoming=old, review=None)
    proposed = old.text.replace('MS. SIEMENS:', 'SPEAKER 3:').replace('MR. LEISER:', 'SPEAKER 3:') + ' Perhaps.'
    begin_review(state, proposed)
    model = review_model.build_review(old, state.incoming)
    pos = state.incoming.text.index('Perhaps')
    result, state.review = transaction(model, state.review, 'incoming', pos, pos+7, 'Perhaps it is')
    state.original, state.incoming = result.original, result.incoming
    override_speaker(state, 'SPEAKER 3', 'MR. LEISER')
    restored = review_model.build_review(state.original, state.incoming, review=state.review)
    assert len(restored.edits) == 9
    assert len([e for e in restored.edits if e.kind == 'speaker']) == 8
    assert 'Perhaps it is' in restored.incoming.text

def test_metadata_only_decision_disappears_after_accept_or_reject():
    from app.src.review_editing import resolve_review
    old = revision('same')
    model = review_model.build_review(old, old.define_field('NAME', 'Jane'))
    for accept in (False, True):
        updated, _ = resolve_review(model, None, 0, accept)
        assert not updated.edits
        assert updated.original.definitions == updated.incoming.definitions


def test_speaker_insertion_at_boundary_moves_location_without_resolving_it():
    model = review('old. SPEAKER 1: Yes', 'new. SPEAKER 1: Yes')
    metadata = {'version': 1, 'evidence': {'speakers': {}, 'occurrences': []}, 'overrides': {},
                'locations': [{'start': 5, 'end': 14, 'resolved': False, 'speaker': 'SPEAKER 1'}]}
    updated, meta = transaction(model, metadata, 'incoming', 5, 5, 'Intro: ')
    assert updated.incoming.text[meta['locations'][0]['start']:meta['locations'][0]['end']] == 'SPEAKER 1'
    assert not meta['locations'][0]['resolved']
    _, changed = transaction(updated, meta, 'incoming', 15, 15, 'x')
    assert changed['locations'][0]['resolved']
    assert metadata['locations'][0]['start'] == 5


def test_deleting_all_insertion_removes_only_its_decision():
    model = review('First. Last is red.', 'First. Extra. Last is blue.')
    a, b = model.edits[0].ranges[0][2:]
    updated, _ = transaction(model, None, 'incoming', a, b, '')
    assert len(updated.edits) == 1
    assert updated.original.text == 'First. Last is red.'
    assert updated.incoming.text == 'First. Last is blue.'


def test_equidistant_highlight_is_owned_by_earlier_change():
    from app.src.review_editing import resolve_review
    old, new = revision('abXdefYhi'), revision('abCdefFhi')
    edits = tuple(Suggestion(old, new, ((i, i+1, i, i+1),)) for i in [2, 6])
    model = review_model.ReviewModel(old, new, edits, ())
    updated, meta = transaction(model, None, 'incoming', 4, 5, 'z')
    result, _ = resolve_review(updated, meta, 0, True)
    assert result.original.text == 'abCdzfYhi'


def test_save_reopen_preserves_manual_decisions_and_native_anchors(tmp_path, monkeypatch):
    from app.src import documents
    from app.tests.test_native_projects import native_doc
    doc, _ = native_doc(tmp_path, monkeypatch)
    old = doc.native.original.replace(0, len(doc.original), 'One cat sat on red.')
    inc = old.revise('One dog sat on blue.')
    model, meta = transaction(review_model.build_review(old, inc), None, 'incoming', 4, 7, 'fox')
    doc.native.original, doc.native.incoming, doc.native.review = model.original, model.incoming, meta
    path = tmp_path / 'manual.bababui'
    documents.save_document(doc, path)
    restored = documents.open_document(path).native
    reopened = review_model.build_review(restored.original, restored.incoming, review=restored.review)
    assert reopened.edits == model.edits
    assert reopened.incoming.spans == model.incoming.spans

@pytest.mark.parametrize('broken', [{'kind': 'text'}, {'kind': 'text', 'ranges': None, 'highlights': []},
                                     {'kind': 'text', 'ranges': [], 'highlights': [], 'definitions': 'bad'}])
def test_damaged_saved_decisions_raise_a_project_error(broken):
    with pytest.raises(ValueError):
        review_model.build_review(revision('old'), revision('new'), review={'pending_decisions': [broken]})


def test_shared_space_insertion_uses_the_destination_stroke_at_the_editor_caret():
    old = Revision((AnchoredSpan('left', (1,), (), 'old'),
                    AnchoredSpan('gap', (2,), (), ' '), AnchoredSpan('right', (3,), (), 'next')))
    new = old.replace(0, 3, 'new')
    model = review_model.build_review(old, new)
    result, _ = transaction(model, None, 'incoming', 3, 3, ' add', affinity='right')
    assert result.original.text == 'old add next'
    assert next(s.stroke_refs for s in result.original.spans if 'add' in s.content) == (2,)


def test_q_a_symbol_edit_expands_inside_symbol_even_for_an_insertion():
    old = revision('     Q    Now red.').replace(10, 10, 'Really? ')
    incoming = old.revise(old.text.replace('red', 'blue'))
    model = review_model.build_review(old, incoming)
    result, _ = transaction(model, None, 'incoming', 5, 5, 'A')
    assert result.original.text == '     A    Really? Now red.'
    assert result.incoming.text == '     A    Really? Now blue.'
    assert result.original.elements[0].raw == result.incoming.elements[0].raw == '160300'

def test_removing_one_linked_occurrence_resolves_without_shifting_other_ranges():
    from app.src.review_editing import resolve_review
    old = revision('').insert_field(0, 'NAME', 'Jane').replace(4, 4, ' and ')
    old = old.insert_field(len(old.text), 'NAME', 'Jane').replace(13, 13, ' was red')
    incoming = old.set_field('NAME', 'Jo').revise('Jo and Jo was blue')
    model = review_model.build_review(old, incoming)
    changed, meta = transaction(model, None, 'incoming', 0, 2, '')
    assert changed.incoming.text == ' and Jo was blue'
    accepted, _ = resolve_review(changed, meta, 0, True)
    assert accepted.original.text == ' and Jo was red'
    assert len(accepted.original.elements) == 1 and accepted.original.definitions == (('NAME', 'Jo'),)
    assert len(accepted.edits) == 1

def test_accepting_wording_with_an_inserted_pending_field_keeps_its_separate_value_decision():
    from app.src.review_editing import resolve_review
    old = revision('').insert_field(0, 'NAME', 'Jane').replace(4, 4, ' read red.')
    inc = old.set_field('NAME', 'Jo').revise('Jo read blue.')
    model = review_model.build_review(old, inc)
    p = inc.text.index('blue')+2
    native = inc.insert_field(p, 'NAME', 'Jo')
    model, meta = transaction(model, None, 'incoming', p, p, 'Jo', native_revision=native)
    kept, meta = resolve_review(model, meta, 1, True)
    assert kept.original.text == 'Jane read blJaneue.'
    assert kept.incoming.text == 'Jo read blJoue.'
    field, = kept.edits
    assert field.field == 'NAME' and len(field.ranges) == 2
    final, _ = resolve_review(kept, meta, 0, False)
    assert final.incoming.text == final.original.text == 'Jane read blJaneue.'


def test_native_operation_cannot_write_past_its_selected_range():
    model = review('red tail', 'blue tail')
    outside = model.incoming.replace(5, 9, 'else')
    with pytest.raises(ValueError):
        transaction(model, None, 'incoming', 1, 2, 'x', native_revision=outside)


def test_manual_red_field_insert_tracks_speaker_after_different_incoming_value():
    old = revision('').insert_field(0, 'NAME', 'Jane').replace(4, 4, ' read. SPEAKER 1: Yes.')
    inc = old.set_field('NAME', 'Jo')
    model = review_model.build_review(old, inc)
    p = old.text.index('read')
    loc = inc.text.index('SPEAKER 1')
    review = {'version':1, 'evidence':{'speakers':{}, 'occurrences':[]}, 'overrides':{},
              'locations':[{'start':loc, 'end':loc+9, 'speaker':'SPEAKER 1', 'resolved':False}]}
    native = old.insert_field(p, 'NAME', 'Jane')
    changed, meta = transaction(model, review, 'original', p, p, 'Jane', native_revision=native)
    location, = meta['locations']
    assert changed.incoming.text[location['start']:location['end']] == 'SPEAKER 1'


def test_shared_reference_still_tracks_linked_value_after_an_occurrence_was_removed():
    from app.src.casecat.fields import field_values
    old = revision('').insert_field(0, 'NAME', 'Jane').replace(4, 4, ' and ')
    old = old.insert_field(len(old.text), 'NAME', 'Jane').replace(13, 13, ' again ')
    model = review_model.build_review(old, old.set_field('NAME', 'Jo'))
    changed, meta = transaction(model, None, 'incoming', 0, 2, '')
    end = len(changed.incoming.text)
    native = changed.incoming.insert_field(end, 'NAME', 'Jo')
    updated, _ = transaction(changed, meta, 'incoming', end, end, 'Jo', native_revision=native)
    assert updated.original.text == 'Jane and Jane again Jane'
    assert field_values(updated.original) == {'NAME':'Jane'}
    assert len(updated.edits) == 1 and len(updated.edits[0].ranges) == 3
