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
    ('the patients or the applicant', 'the patient’s or the applicant'),
    ("the patient's report", 'the patients report'),
])
def test_general_rules_accept_complete_authorized_edits(before, after):
    original = revision(before)
    incoming = original.revise(after)
    changes = suggestions(original, incoming)
    assert changes
    assert all(filters.automatic_reason(c) for c in changes)


@pytest.mark.parametrize('contracted,expanded', [
    ("the left arm isn't mentioned", 'the left arm is not mentioned'),
    ('the left arm isn’t mentioned', 'the left arm is not mentioned'),
    ("I don't remember.", 'I do not remember.'),
    ("I can't tell.", 'I cannot tell.'),
    ('That won’t work.', 'That will not work.'),
    ("IT ISN'T READY.", 'IT IS NOT READY.'),
])
@pytest.mark.parametrize('contract', [False, True])
def test_negative_contractions_are_bidirectional_and_respect_toggle(contracted, expanded, contract):
    before, after = (expanded, contracted) if contract else (contracted, expanded)
    original = revision(before)
    changes = suggestions(original, original.revise(after))
    assert changes
    assert all(filters.automatic_reason(change, disabled_rules={
        'capitalization', 'punctuation', 'short_common_words'}) for change in changes)
    assert all(not filters.automatic_reason(change, disabled_rules={'contractions'}) for change in changes)


@pytest.mark.parametrize('before,after,disabled', [
    ('Yes I saw it.', 'Yes, I saw it.', 'punctuation'),
    ('the patients report', "the patient's report", 'punctuation'),
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
    ("isn't working", 'is working'), ("can't work", 'can work'),
    ('1.5', '15'), ('11-17-1999', '11171999'), ('911', '9/11'),
    ('5', '-5'), ('value 5', 'value -5'), ('12:30', '1230'),
    ("he's done", 'he is done'), ("I'd go", 'I would go'),
    ('patient', "patient's"), ('word\u00a0word', 'word word'),
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


@pytest.mark.parametrize('keep', [False, True])
def test_trailing_whitespace_mode_before_review(keep):
    original = revision('     A    Yes.\u00a0\n     Q    Two  words? \t\n')
    state = SimpleNamespace(original=original, incoming=original, review=None)
    filters.begin_review(state, 'A Yes.\nQ Two  words?\n')
    filters.auto_accept(state, disabled_rules={'trailing_whitespace'} if keep else frozenset())

    expected = original.text if keep else '     A    Yes.\n     Q    Two  words?\n'
    assert state.original.text == state.incoming.text == expected
    assert not suggestions(state.original, state.incoming)


@pytest.mark.parametrize('ordinal,plain', [
    ('On page 4 of your September 3rd report.', 'On page 4 of your September 3 report.'),
    ('It was October 21st.', 'It was October 21.'),
    ('Meet on 2nd of Feb.', 'Meet on 2 of Feb.'),
    ('Dated the 11th of May.', 'Dated the 11 of May.'),
    ('Take the 3rd floor.', 'Take the 3 floor.'),
    ('It was the 100th item.', 'It was the 100 item.'),
])
@pytest.mark.parametrize('add_suffix', [False, True])
def test_ordinal_suffixes_are_accepted_in_both_directions(ordinal, plain, add_suffix):
    before, after = (plain, ordinal) if add_suffix else (ordinal, plain)
    original = revision(before)
    state = SimpleNamespace(original=original, incoming=original.revise(after), review=None)
    changes = suggestions(state.original, state.incoming)
    assert changes
    assert all(not filters.automatic_reason(change, disabled_rules={'date_ordinals'}) for change in changes)
    assert [record['rule'] for record in filters.auto_accept(state)] == ['ordinal suffix']
    assert state.original == state.incoming
    assert state.original.text == after


@pytest.mark.parametrize('before,after', [
    ('The May 3rd report.', 'The May 4 report.'),
    ('The May 3rd report.', 'The June 3 report.'),
    ('It was May 3.5.', 'It was May 3rd.5.'),
    ('It was the 3rd.', 'It was the 3?'),
    ('The 3rd floor.', 'The 3th floor.'),
    ('The 3rd floor.', 'The 3 loft.'),
    ('The May 3rd report.', 'The May 3rd statement.'),
])
def test_ordinal_suffix_rule_leaves_other_edits_pending(before, after):
    original = revision(before)
    changes = suggestions(original, original.revise(after))
    assert changes
    assert all(not filters.automatic_reason(change) for change in changes)


@pytest.mark.parametrize('before,after,rule', [
    ("     A    Correct that's an outline.", "     A    Right.  That's an outline.", 'positive_confirmations'),
    ('     Q    Is that correct?', '     Q    Is that true?', 'positive_confirmations'),
    ('The report is dated May 4, right?', 'The report is dated May 4, correct?', 'positive_confirmations'),
    ('He rated it a five out of five it did help.', 'He rated it a 5 out of 5.  It did help.', 'number_forms'),
    ('There were 25 people.', 'There were twenty-five people.', 'number_forms'),
    ('There were one hundred and five people.', 'There were 105 people.', 'number_forms'),
    ('It came to a hundred.', 'It came to 100.', 'number_forms'),
    ('It came to one thousand.', 'It came to 1,000.', 'number_forms'),
])
def test_auto_accept_preserves_equivalent_confirmations_and_numbers(before, after, rule):
    original = revision(before)
    incoming = original.revise(after)
    disabled = SimpleNamespace(original=original, incoming=incoming, review=None)
    assert not filters.auto_accept(disabled, disabled_rules={rule})

    state = SimpleNamespace(original=original, incoming=incoming, review=None)
    assert filters.auto_accept(state)
    assert state.original.text == state.incoming.text == after


@pytest.mark.parametrize('before,after', [
    ('The right arm hurts.', 'The correct arm hurts.'),
    ('Which way did you turn? Was it right, left, or straight?',
     'Which way did you turn? Was it true, left, or straight?'),
    ('Correct that error.', 'Right that error.'),
    ("That's not right.", "That's true."),
    ('There were five people.', 'There were 6 people.'),
    ('There were fifty people.', 'There were 15 people.'),
    ('I picked a seven.', 'I picked 7.'),
    ('I called Mr. Four about it.', 'I called Mr. 4 about it.'),
    ('It was five.', 'It was -5.'),
    ('It was five.', 'It was 5.0.'),
    ('It was one .5.', 'It was 1.5.'),
    ('It was five out of six.', 'It was 5/6.'),
    ('It was twenty - five.', 'It was 25.'),
    ('It was twenty five.', 'It was twenty 5.'),
    ('It was five point five.', 'It was 5 point five.'),
    ('It was five.', 'It was 05.'),
])
def test_confirmation_and_number_filters_leave_meaningful_edits_pending(before, after):
    original = revision(before)
    state = SimpleNamespace(original=original, incoming=original.revise(after), review=None)
    assert not filters.auto_accept(state)
    assert state.original.text == before
