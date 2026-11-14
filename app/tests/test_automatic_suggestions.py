from types import SimpleNamespace

import pytest

from app.src.casecat.anchors import Revision, AnchoredSpan
from app.src.suggestions import suggestions
from app.src import suggestion_filter as filters


def revision(text):
    return Revision((AnchoredSpan('root', (0,), (12,), text),))


@pytest.mark.parametrize('before,after', [
    ("I'm counsel.", 'I am counsel.'),
    ('We\u2019re ready.', 'We are ready.'),
    ('capacity as qualified', 'capacity of qualified'),
    ('Those three', 'And those three'),
    ('That was on may 14', 'And that was on May 14'),
    ("I'm there which page?", "I'm there.  Which page?"),
    ('page 15 under employment', 'page 15.  Under employment'),
    ('report?', 'report --'),
    ('report?', 'report'),
    ('an injury.  So this', 'a injury; so this'),
    ('year.   March', 'year, March'),
    ('the report', 'report'),
    ('report correct?', 'report; correct?'),
])
def test_general_rules_accept_complete_authorized_edits(before, after):
    original = revision(before)
    incoming = original.revise(after)
    changes = suggestions(original, incoming)
    assert changes
    assert all(filters.automatic_reason(c) for c in changes)


@pytest.mark.parametrize('before,after,disabled', [
    ('Yes I saw it.', 'Yes, I saw it.', 'punctuation'),
    ('It was may.', 'It was May.', 'capitalization'),
    ("We're ready.", 'We are ready.', 'contractions'),
    ('I saw the report.', 'I saw report.', 'short_common_words'),
    ('an injury.  So this', 'a injury; so this', 'punctuation'),
    ('an injury.  So this', 'a injury; so this', 'capitalization'),
    ('an injury.  So this', 'a injury; so this', 'short_common_words'),
])
def test_disabled_rule_keeps_eligible_card_pending(before, after, disabled):
    original = revision(before)
    changes = suggestions(original, original.revise(after))
    blocked = [change for change in changes
               if not filters.automatic_reason(change, disabled_rules={disabled})]
    assert blocked
    assert all(filters.automatic_reason(change) for change in blocked)


@pytest.mark.parametrize('before,after,enabled', [
    ('Yes I saw it.', 'Yes, I saw it.', 'punctuation'),
    ('It was may.', 'It was May.', 'capitalization'),
    ('We\u2019re ready.', 'We are ready.', 'contractions'),
    ('I saw the report.', 'I saw report.', 'short_common_words'),
])
def test_each_rule_can_accept_edits_on_its_own(before, after, enabled):
    rules = {'punctuation', 'capitalization', 'contractions', 'short_common_words'}
    original = revision(before)
    changes = suggestions(original, original.revise(after))
    assert changes
    assert all(filters.automatic_reason(change, disabled_rules=rules - {enabled}) for change in changes)


@pytest.mark.parametrize('before,after', [
    ('And I have all of them', 'Then I have all of them'),
    ("I'm there which page?", 'And there which page?'),
    ('stayed', 'stated'), ('form', 'from'), ('Kristin', 'Kristen'),
    ('no work', 'to work'), ('not working', 'working'),
    ('1.5', '15'), ('11-17-1999', '11171999'), ('911', '9/11'),
    ('5', '-5'), ('value 5', 'value -5'), ('12:30', '1230'),
    ("he's done", 'he is done'), ("I'd go", 'I would go'),
    ('persons', "person's"), ('word\u00a0word', 'word word'),
    ('Q    Yes.', 'A    Yes.'), ('First\nSecond', 'First Second'),
    ('SPEAKER 2: Hello', 'SPEAKER 3: Hello'),
    ('THE WITNESS: Yes', 'THE DOCTOR: Yes'),
    ('Hello  there', 'Hello there'),
])
def test_substantive_structural_and_protected_changes_stay_pending(before, after):
    original = revision(before)
    assert all(not filters.automatic_reason(c) for c in suggestions(original, original.revise(after)))


def test_native_batch_keeps_pending_edits_and_is_idempotent():
    from copy import deepcopy
    original = revision('And I have all of them.\nThose were dated may 21.\n')
    state = SimpleNamespace(original=original, incoming=original, review=None)
    filters.begin_review(state, 'Then I have all of them.\nAnd those were dated May 21;\n')
    evidence = deepcopy(state.review['evidence'])
    result = filters.auto_accept(state)
    assert len(result) == 3
    assert state.original.text == 'And I have all of them.\nAnd those were dated May 21;\n'
    assert len(suggestions(state.original, state.incoming)) == 1
    assert state.review['evidence'] == evidence
    assert filters.auto_accept(state) == []


def test_native_field_values_never_auto_accept_even_case_only():
    original = revision('').insert_field(0, 'name', 'MS. OLD')
    incoming = original.set_field('NAME', 'Ms. Old')
    assert not filters.automatic_reason(suggestions(original, incoming)[0])
