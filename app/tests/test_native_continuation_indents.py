"""Native continuation indents in prepared proposals and accepted CaseCAT exports."""
import struct

import pytest

from app.src import documents
from app.src.casecat.archive import inspect_archive
from app.src.casecat.codec import records
from app.src.casecat.presentation import presentation
from app.src.notice_review import begin_document_review
from app.src.review_model import build_review
from app.src.suggestions import resolve_all
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_fields import native_stream
from app.tests.test_native_layout import layout_bytes
from app.tests.test_native_structure import container_files


def continuation_document(words, continuation=3600, left=2160):
    layout = bytearray(layout_bytes(first=3600))
    style = bytearray(layout[1024:1536])
    struct.pack_into('<H', style, 170, left)
    struct.pack_into('<H', style, 176, continuation)
    layout[1536:1536] = style * 3  # Question, Answer and Colloquy.
    struct.pack_into('<I', layout, 4, 4)
    files = container_files(words, layout=layout)
    del files['jobs/example.wav']
    return documents.import_casecat(inspect_archive(zip_bytes(files)))


@pytest.mark.parametrize('symbol, label, boundary, continuation, retained_spaces', [
    (2, '     Q    ', '\x16\x02\x00', 3600, 0),
    (2, '     Q    ', '  ', 3600, 0),
    (3, '     A    ', '  ', 2880, 0),
    (4, '     MR. COUNSEL:  ', '  ', 3600, 0),
    (2, '     Q    ', '  ', 2160, 10),
], ids=['removed-question-label', 'split-question', 'custom-answer-indent', 'split-colloquy', 'flush-layout'])
def test_proposed_continuation_uses_one_indent_in_review_and_export(
        tmp_path, symbol, label, boundary, continuation, retained_spaces):
    speaker = 'MR. COUNSEL:  ' if symbol == 4 else ''
    doc = continuation_document((f'\x16{chr(symbol)}\x00{speaker}First topic.', boundary, 'Another topic.'), continuation)
    proposal = label + 'First topic.\n          Another topic.'
    begin_document_review(doc.native, proposal)
    expected = label + 'First topic.\n' + ' ' * retained_spaces + 'Another topic.'
    assert doc.incoming == expected

    original, incoming = doc.native.original, doc.native.incoming
    model = build_review(original, incoming)
    doc.native.original, doc.native.incoming = resolve_all(original, incoming, model.ranges, True)
    target = tmp_path / 'accepted.zip'
    doc.export_casecat(target)
    reopened = documents.import_casecat(target)
    assert reopened.original == expected
    offset = expected.index('\n') + 1
    for state in (doc.native, reopened.native):
        _, styles, _ = presentation(state.job.with_revision(state.original), state.bundle)
        assert styles[offset].first == continuation
        assert styles[offset].prefix_length == 0


@pytest.mark.parametrize('replacement', ['A small detail.', 'A finer detail.'])
def test_proposal_keeps_an_indented_sentence_starting_with_a(replacement):
    doc = continuation_document(('\x16\x02\x00First topic.', '\x16\xff\x00          A small detail.'))
    proposal = doc.original.replace('A small detail.', replacement)
    begin_document_review(doc.native, proposal)
    assert doc.incoming == proposal


@pytest.mark.parametrize('join', [False, True], ids=['split', 'merge'])
@pytest.mark.parametrize('spaces', [5, 10, 12])
def test_proposal_preserves_the_first_indent_when_regrouping_literal_paragraphs(join, spaces):
    source_boundary = '\x16\xff\x00          ' if join else '  '
    doc = continuation_document(('\x16\x02\x00Introduction.', '\x16\xff\x00' + ' ' * spaces + 'One topic.',
                                 source_boundary + 'Two topics.'))
    first = '     Q    Introduction.\n          One topic.'
    proposal = first + ('  ' if join else '\n          ') + 'Two topics.'
    begin_document_review(doc.native, proposal)
    assert doc.incoming == first.replace(' ' * 10, ' ' * spaces) + ('  ' if join else '\n') + 'Two topics.'


def test_split_preserves_source_indent_when_words_are_inserted_before_the_first_word():
    doc = continuation_document(('\x16\x02\x00First topic.', '\x16\xff\x00     Monday was busy. Tuesday was quiet.'))
    begin_document_review(doc.native, '     Q    First topic.\n          Last Monday was busy.\n          Tuesday was quiet.')
    assert doc.incoming == '     Q    First topic.\n     Last Monday was busy.\nTuesday was quiet.'


def test_unpadded_continuation_does_not_inherit_the_removed_label_spaces():
    doc = continuation_document(('\x16\x02\x00First topic.', '\x16\x02\x00Second topic.'))
    proposal = '     Q    First topic.\nSecond topic.'
    begin_document_review(doc.native, proposal)
    assert doc.incoming == proposal


@pytest.mark.parametrize('source, proposed, expected, symbol', [
    ('A small detail.', 'A small detail.', 'A small detail.', 255),
    ('A small detail.', 'A finer detail.', 'A finer detail.', 255),
    ('A small detail.', 'A A small detail.', '     A    A small detail.', 3),
    ('Small detail.', 'A Small detail.', '     A    Small detail.', 3),
])
def test_unpadded_article_and_shorthand_answer_keep_their_native_roles(source, proposed, expected, symbol):
    doc = continuation_document(('\x16\x02\x00First topic.', '\x16\x02\x00' + source))
    first = '     Q    First topic.\n'
    begin_document_review(doc.native, first + proposed)
    assert doc.incoming == first + expected
    _, accepted = doc.native.edited_job(doc.native.incoming)
    stream = native_stream(accepted)
    assert [raw[1] for _, raw in records(stream, 0, len(stream)) if raw[0] == 0x16] == [2, symbol]


def test_split_uses_the_question_styles_indented_left_margin():
    doc = continuation_document(('\x16\x02\x00First topic.  Another topic.',), left=3600)
    begin_document_review(doc.native, '     Q    First topic.\n          Another topic.')
    assert doc.incoming == '     Q    First topic.\nAnother topic.'


@pytest.mark.parametrize('symbol, speaker, extra', [(4, 'MR. COUNSEL:  ', ''), (2, '', '\x01' * 5)])
def test_removing_a_turn_label_preserves_only_its_authored_spaces(tmp_path, symbol, speaker, extra):
    paragraph = f'\x16{chr(symbol)}\x00{speaker}'
    doc = continuation_document((paragraph + 'First topic.', paragraph + extra + 'Second topic.'))
    first = doc.original.split('\n')[0]
    begin_document_review(doc.native, first + '\n          Second topic.')
    expected = first + '\n' + ' ' * len(extra) + 'Second topic.'
    assert doc.incoming == expected
    doc.native.original = doc.native.incoming
    path = tmp_path / 'continued.zip'
    doc.export_casecat(path)
    reopened = documents.import_casecat(path)
    assert reopened.original == expected
    stream = native_stream(reopened.native.job)
    assert [raw[1] for _, raw in records(stream, 0, len(stream)) if raw[0] == 0x16] == [symbol, 255]
    assert sum(raw == b'\x01' for _, raw in records(stream, 0, len(stream))) == len(extra)


def test_proposal_preserves_existing_literal_and_noncontinuation_indents():
    doc = continuation_document(('\x16\x02\x00First topic.  Another topic.',
                                 '\x16\xff\x00          Deliberate source spacing.',
                                 '\x16\x03\x00Yes.'))
    proposal = doc.original.replace('  Another topic.', '\n          Another topic.').replace(
        'Deliberate source spacing.', 'Deliberate source indentation.')
    proposal += '\n               (Off the record.)\n     MS. COUNSEL:  Back on the record.'
    begin_document_review(doc.native, proposal, exclude_off_record=False)
    assert doc.incoming == proposal.replace('\n          Another topic.', '\nAnother topic.')
