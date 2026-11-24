"""Transcript decisions follow the words through changes in turn formatting."""
from dataclasses import replace

import pytest

from app.src.review_model import build_review, model_from_edits
from app.src.suggestion_filter import automatic_reason
from app.src.suggestions import preview_ranges, propose, suggestions
from app.tests.test_suggestions import revision


def excerpts(edits):
    return [[(edit.original.text[a:b], edit.incoming.text[c:d]) for a, b, c, d in edit.ranges]
            for edit in edits]


def assert_replay(left, right, edits):
    a = c = 0
    for x, y, z, w in sorted(span for edit in edits for span in edit.ranges):
        assert x >= a and z >= c and left[a:x] == right[c:z]
        a, c = y, w
    assert left[a:] == right[c:]


def test_examiner_move_interruption_and_sentence_punctuation_have_separate_owners():
    left = ('MS. NORTH:  Would you repeat that.\n'
            'MR. EAST:  Did you inspect both of the damaged loading bays?\n'
            'THE WITNESS:  Both bays needed repairs. I had to close the north entrance.\n'
            'BY MR. EAST:\n     Q    When did it reopen?')
    right = ('MS. NORTH:  Would you repeat that?\n'
             'BY MR. EAST:\n     Q    Did you inspect both of the damaged loading bays?\n'
             '     A    Well, both bays needed repairs.\n     Q    Including --\n'
             '     A    I had to close the north entrance.\n     Q    When did it reopen?')
    edits = suggestions(revision(left), revision(right))
    pairs = excerpts(edits)
    assert [('.', '?')] in pairs
    assert automatic_reason(edits[pairs.index([('.', '?')])])
    labels = [pair for edit, pair in zip(edits, pairs) if edit.kind == 'turn_label']
    assert labels == [[('MR. EAST:  ', '     Q    ')], [('THE WITNESS:  ', '     A    ')]]
    move, = [edit for edit in edits if edit.kind == 'byline_move']
    assert sorted((a.strip(), b.strip()) for a, b in excerpts([move])[0]) == [
        ('', 'BY MR. EAST:'), ('BY MR. EAST:', '')]
    for shared in ('damaged loading bays', 'bays needed repairs', 'close the north entrance'):
        assert all(shared not in s for pair in pairs for raw in pair for s in raw)
    assert_replay(left, right, edits)


def test_added_exchange_stops_before_the_expanded_short_turn():
    left = ('MS. WEST:  We have time I wanted to check the final page.\n'
            'MR. EAST:  Read on.\nMS. WEST:  Thank you.\nBY MS. WEST:\n     Q    What happened next?')
    added = ' Were you waiting for me?\nMR. EAST:  I was reviewing the dates.\nMS. WEST:  Understood.'
    right = ('MS. WEST:  We have time. I want to check the final page.' + added +
             '\nMR. EAST:  Please read on while I look, or just read on.\n'
             'EXAMINATION\nBY MS. WEST:\n     Q    What happened next?')
    edits = suggestions(revision(left), revision(right))
    pairs = excerpts(edits)
    assert [('', '.')] in pairs
    assert [('', added)] in pairs
    assert all('MR. EAST:  Please' not in part for pair in pairs for raw in pair for part in raw)
    assert_replay(left, right, edits)


def test_repeated_request_cannot_displace_the_intervening_dialogue():
    left = ('BY MS. DAY:\nQ I need to ask for the line to be muted so everyone can hear.\n'
            'MR. FOX: Ask a relevant question and we can finish.\n'
            'MS. DAY: Okay.\nMR. FOX: At least read from the last dated report before deciding.\n'
            'MS. DAY: I am going to have to ask you to do that.\nMR. FOX: Put that on the record.')
    right = ('MS. DAY: I am going to have to ask you to mute the line so everyone can hear the answer.\n'
             'MR. FOX: Ask a relevant question and we could finish.\n'
             'MS. DAY: Okay, Doctor.\nMR. FOX: At least read from the last dated report before deciding that.\n'
             'MS. DAY: I am going to have to ask you to mute the line.\nMR. FOX: Put that on the record.')
    edits = suggestions(revision(left), revision(right))
    for raw in excerpts(edits):
        assert all('last dated report' not in part and 'relevant question' not in part for pair in raw for part in pair)
    assert_replay(left, right, edits)


def test_added_closing_turns_do_not_absorb_the_last_word_correction():
    left = 'MS. DAY:  Can the reporter leave?\nMR. FOX:  Agreed.'
    tail = '\nMS. DAY:  Thank you for appearing.\nTHE REPORTER:  Thank you all.'
    right = left.replace('Agreed.', 'Agree.') + tail
    pairs = excerpts(suggestions(revision(left), revision(right)))
    assert [('', tail)] in pairs
    assert [('d', '')] in pairs


def test_same_position_speaker_does_not_cross_a_repeated_spoken_reply():
    left = 'THE WITNESS: Did the records?\nA Did the records?\n'
    right = 'MR. KENT: Right.\nA Did records?'
    edits = suggestions(revision(left), revision(right))
    assert_replay(left, right, edits)
    assert all(e.kind != 'turn_label' for e in edits)


def test_label_conversion_cannot_split_a_native_field_containing_testimony():
    left = revision(' waited for the reporter.').insert_field(0, 'CUSTOM', 'MR. KENT:  We')
    right = propose(left, 'Q We waited for the reporter.')
    for edit in suggestions(left, right):
        for a, b, c, d in edit.ranges:
            assert (a, b) == left.atomic_range(a, b)
            assert (c, d) == right.atomic_range(c, d)


def test_note_is_a_barrier_to_inferred_turn_conversions():
    left = 'MR. DAY:  Explain the missing dates.\n(Off the record.)\nMS. WEST:  No further questions.'
    right = '(Off the record.)\nQ Explain the missing dates.\nMS. WEST:  No further questions.'
    edits = suggestions(revision(left), revision(right))
    assert all(e.kind != 'turn_label' for e in edits)
    assert_replay(left, right, edits)


def test_long_proposal_computes_character_edits_in_anchored_passages(monkeypatch):
    from app.src import advanced_diff
    from app.src.suggestions import text_edits
    old = '\n'.join(f'MS. DAY:  Did you inspect loading bay {i} before the shipment arrived?' for i in range(320))
    new = old.replace('MS. DAY:  ', '     Q    ').replace('before', 'after')
    inner = advanced_diff.text_edits
    def bounded(a, b):
        assert max(len(a), len(b)) < len(old), 'The full character comparison exceeds the interactive diff budget'
        return inner(a, b)
    monkeypatch.setattr(advanced_diff, 'text_edits', bounded)
    ranges = text_edits(old, new)
    for a, b, c, d in reversed(ranges):
        old = old[:a] + new[c:d] + old[b:]
    assert old == new


def test_rejecting_realigned_label_keeps_the_destination_stroke_order():
    from types import SimpleNamespace
    from app.src.casecat.anchors import AnchoredSpan, Revision
    from app.src.casecat.structure import group_targets
    from app.src.review_editing import resolve_review
    def native(parts):
        return Revision(tuple(AnchoredSpan(str(i), (i,), (), part) for i, part in enumerate(parts)))
    left = native(('Opening.\nMR. FOX:  ', 'Was the letter received?\n', 'Q First date?'))
    right = native(('', 'Opening.\n     Q    Was the letter received?\n', 'Q Second date?'))
    model = build_review(left, right)
    index, = [i for i, e in enumerate(model.edits) if e.kind == 'turn_label']
    result, _ = resolve_review(model, None, index, False)
    assert result.incoming.text == right.text.replace('     Q    ', 'MR. FOX:  ')
    job = SimpleNamespace(baseline=left, revision=result.incoming, text=result.incoming.text)
    assert ''.join(group_targets(job)) == result.incoming.text


@pytest.mark.parametrize('stored', [False, True])
def test_quote_pair_owns_one_wrapped_passage_with_independent_inner_edit(stored):
    left = 'She read the lengthy report in full and carefully checked the dates before leaving.'
    right = 'She read "the lengthy report in full and carefully checked those dates" before leaving.'
    model = build_review(revision(left), revision(right))
    if stored:
        edits = tuple(replace(e, highlights=preview_ranges(e)) for e in model.edits)
        model = model_from_edits(model.original, model.incoming, edits)
    quote, = [i for i, e in enumerate(model.edits) if e.kind == 'quotation']
    rows = lambda t: [(p, min(p + 14, len(t))) for p in range(0, len(t), 14)]
    sections = [s for _, _, s in model.compare_rows(rows(left), rows(right)) if quote in s.edit_indices]
    assert len(sections) == 1
    assert len(sections[0].edit_indices) == 2
    assert len(model.edits[quote].ranges) == 2


@pytest.mark.parametrize('proposal', [True, False])
def test_proposed_moved_byline_keeps_native_control_and_field(tmp_path, proposal):
    from app.src.casecat import archive, codec
    from app.tests.test_native_fields import FIELD, ORPHAN, field_job, native_stream
    bundle, job = field_job()
    line, body = job.text.split('\n', 1)
    target = body + '\n' + line
    incoming = propose(job.revision, target) if proposal else job.revision.revise(target)
    edits = suggestions(job.revision, incoming)
    assert [e.kind for e in edits] == ['byline_move']
    assert_replay(job.text, target, edits)
    dest = tmp_path / 'moved.zip'
    archive.export_zip(bundle, job.with_revision(incoming), dest)
    restored = codec.load_job(archive.inspect_archive(dest), job.key)
    assert restored.text == target
    stream = native_stream(restored)
    assert stream.count(FIELD) == 2 and stream.count(b'\x16\x05\x00') == 1 and ORPHAN in stream


@pytest.mark.parametrize('stored', [False, True])
@pytest.mark.parametrize('disabled,undone', [(False, False), (True, False), (False, True)])
def test_legacy_reopen_upgrades_once_and_preserves_user_decisions(stored, disabled, undone):
    from types import SimpleNamespace
    from app.src.notice_review import auto_accept_document
    from app.src.review_editing import _metadata, restore_decisions
    left = revision('Q We saw red tiles.\nMR. FOX:  Say that again.\n'
                    'MS. DAY:  Was the packaging damaged when it arrived?\n'
                    'BY MS. DAY:\n     Q    What else did you see?')
    right = revision('Q We saw blue tiles.\nMR. FOX:  Say that again?\n'
                     'BY MS. DAY:\n     Q    Was the packaging damaged when it arrived?\n'
                     '     Q    What else did you see?')
    previous = list(suggestions(left, right, legacy=True))
    previous[0] = replace(previous[0], highlights=((0, 18, 1, 19),))
    audit = [] if undone else [{'rule': 'earlier action'}]
    review = _metadata(None, model_from_edits(left, right, tuple(previous)))
    review.pop('grouping_version', None)
    review.update(automatic_filter=1, automatic_changes=audit.copy())
    if not stored:
        review.pop('pending_decisions')
    state = SimpleNamespace(original=left, incoming=right, review=review, body_position=lambda rev: 0)
    undo = []
    rules = {'punctuation'} if disabled else set()
    records = auto_accept_document(state, disabled_rules=rules, remember_undo=undo.append)
    assert bool(records) == (not disabled and not undone)
    assert state.review['automatic_changes'] == audit + records
    pending = restore_decisions(state.original, state.incoming, state.review['pending_decisions'])
    assert any(e.kind == 'turn_label' for e in pending)
    if stored:
        assert pending[0].highlights == previous[0].highlights
    assert 'again?' in state.original.text if records else 'again.' in state.original.text
    assert auto_accept_document(state, disabled_rules=set()) == []
    if undo:
        state.original, state.incoming, state.review = undo[0]
        assert state.review['automatic_changes'] == audit
        restored = build_review(state.original, state.incoming, state.review)
        assert [('.', '?')] in excerpts(restored.edits)
        assert auto_accept_document(state, disabled_rules=set()) == []


def test_unfiltered_saved_cards_keep_valid_ranges_after_first_open():
    from types import SimpleNamespace
    from app.src.review_editing import _metadata, restore_decisions
    from app.src.notice_review import auto_accept_document
    left = revision('MR. DAY:  The crate was red and sealed')
    right = revision('MR. DAY:  The crate was blue and sealed.')
    edits = list(suggestions(left, right, legacy=True))
    edits[0] = replace(edits[0], highlights=((10, 26, 11, 28),))
    metadata = _metadata(None, model_from_edits(left, right, tuple(edits)))
    del metadata['grouping_version']
    state = SimpleNamespace(original=left, incoming=right, review=metadata, body_position=lambda revision: 0)
    records = auto_accept_document(state, disabled_rules=set())
    assert [r['after'] for r in records] == ['.']
    pending, = restore_decisions(state.original, state.incoming, state.review['pending_decisions'])
    assert pending.highlights == edits[0].highlights and pending.ranges == edits[0].ranges


def test_unfiltered_saved_review_cleans_trailing_spaces_only_in_testimony():
    from types import SimpleNamespace
    from app.src.notice_review import auto_accept_document
    from app.src.review_editing import _metadata, restore_decisions
    head = 'Cover   \n'
    left = revision(head + 'Q Please wait.   \nQ The crate is red.   ')
    right = revision(left.text.replace('red.', 'blue.'))
    edits = list(suggestions(left, right, legacy=True))
    a, b, c, d = edits[0].ranges[0]
    edits[0] = replace(edits[0], highlights=((a-2, b, c-1, d),))
    review = _metadata(None, model_from_edits(left, right, tuple(edits)))
    review.pop('grouping_version')
    state = SimpleNamespace(original=left, incoming=right, review=review, body_position=lambda rev: len(head))
    undo = []
    records = auto_accept_document(state, disabled_rules=set(), remember_undo=undo.append)
    assert len(records) == 4 and all(r['rule'] == 'trailing whitespace' for r in records)
    assert state.original.text == head + 'Q Please wait.\nQ The crate is red.'
    remaining, = restore_decisions(state.original, state.incoming, state.review['pending_decisions'])
    assert remaining.highlights == ((a-5, b-3, c-4, d-3),)
    assert undo[0][:2] == (left, right)


def test_first_whitespace_batch_can_finish_an_old_saved_review():
    from types import SimpleNamespace
    from app.src.notice_review import auto_accept_document
    from app.src.review_editing import _metadata
    right = revision('Q Was it received?')
    left = right.replace(len(right.text), len(right.text), '  ')
    review = _metadata(None, model_from_edits(left, right, tuple(suggestions(left, right, legacy=True))))
    review.pop('grouping_version')
    state = SimpleNamespace(original=left, incoming=right, review=review, body_position=lambda rev: 0)
    auto_accept_document(state, disabled_rules=set())
    assert state.original == state.incoming
    assert not state.review['pending_decisions']
