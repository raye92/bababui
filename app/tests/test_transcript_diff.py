from app.src.transcript_diff import parse_transcript, align_blocks, word_spans, render_blocks
from transcript_formatting import TranscriptFormatter


def formatted(text):
    return TranscriptFormatter().apply_formatting(text)[0]


def texts(text):
    return [b.text for b in parse_transcript(text)]


def test_heading_and_changed_labels_pair_independently_of_numbering():
    old = formatted('BY MR. BRAULT:\n     Q    Good morning, Dr. Goebel. My name is Patrick Brault, and I am an attorney for Niagara Bottling.\n     A    Yes.')
    new = formatted('EXAMINATION\nBY SPEAKER 2:\n     Q    Good morning, Dr. Hill Bell. My name is Patrick Brault, and I am an attorney for Niagara Bottling.\n     A    Yes.')
    assert align_blocks(parse_transcript(old), parse_transcript(new)) == [
        ('insert', 0, 0, 0, 1), ('replace', 0, 1, 1, 2),
        ('replace', 1, 2, 2, 3), ('equal', 2, 3, 3, 4)]


def test_layout_and_continuations_are_not_changes():
    plain = 'EXAMINATION\nBY MR. BRAULT:\nQ Please describe the records you reviewed before the examination.\nA 25.'
    wrapped = formatted(plain)
    assert texts(wrapped) == texts(plain)
    assert texts('Q Please describe the records\nyou reviewed before the examination.\nA 25.') == texts(plain)[2:]
    assert all(op[0] == 'equal' for op in align_blocks(parse_transcript(plain), parse_transcript(wrapped)))


def test_numbers_punctuation_and_case_are_content():
    assert texts('25\n2026\nQ How many?\nA 100,000.') == ['25', '2026', 'Q How many?', 'A 100,000.']
    assert texts(formatted('Q How many?\nA\n25')) == ['Q How many?', 'A', '25']
    assert align_blocks(parse_transcript('A Yes.'), parse_transcript('A yes?'))[0][0] == 'replace'


def test_repeated_answers_follow_their_questions():
    old = parse_transcript('Q Did you drive?\nA Yes.\nQ Did you stop?\nA Yes.')
    new = parse_transcript('Q Did you drive there?\nA Yes.\nQ Were you alone?\nA Yes.\nQ Did you stop here?\nA Yes.')
    ops = align_blocks(old, new)
    assert ('replace', 0, 1, 0, 1) in ops
    assert ('replace', 2, 3, 4, 5) in ops
    assert all(old[i].kind == new[j].kind for tag, i, end, j, stop in ops if tag == 'replace')


def test_split_plain_paragraph_is_equal_and_round_trip_keeps_content():
    left = parse_transcript('The witness reviewed the report.')
    right = parse_transcript('The witness reviewed\nthe report.')
    assert align_blocks(left, right) == [('equal', 0, 1, 0, 2)]
    assert texts(render_blocks(parse_transcript(formatted('Q How many?\nA 25.')), True)) == ['Q How many?', 'A 25.']


def test_word_highlights_identify_only_changed_words():
    old = 'Q Good morning, Dr. Goebel. My name is'
    new = 'Q Good morning, Dr. Hill Bell. My name is'
    a, b = word_spans(old, new)
    assert [old[s:e] for s, e in a] == ['Goebel']
    assert [new[s:e] for s, e in b] == ['Hill Bell']


def test_source_locations_survive_page_breaks_and_generated_padding():
    text = formatted('\n'.join('Q Question number %d?' % i for i in range(24)) + '\nEXAMINATION\nBY MR. BRAULT:\nQ Hello?')
    blocks = parse_transcript(text)
    assert len(blocks) == 27
    assert '///' not in [b.text for b in blocks]
    assert text.split('\n')[blocks[-1].source_start].strip().endswith('Q Hello?')


def test_long_unlabeled_paragraph_ignores_rewrapping():
    paragraph = 'The witness reviewed the report and described the records. ' * 8
    left, right = parse_transcript(paragraph), parse_transcript(formatted(paragraph))
    assert all(op[0] == 'equal' for op in align_blocks(left, right))


def test_plain_paragraph_can_split_across_many_short_lines():
    left = parse_transcript('one two three four five six')
    right = parse_transcript('one\ntwo\nthree\nfour\nfive\nsix')
    assert align_blocks(left, right) == [('equal', 0, 1, 0, 6)]


def test_wrapped_numbers_and_article_a_stay_in_the_question():
    for text in ('Q ' + 'word ' * 10 + 'xx 25',
                 'Q ' + 'word ' * 10 + 'xxxx A small detail.'):
        assert all(op[0] == 'equal' for op in align_blocks(parse_transcript(text), parse_transcript(formatted(text))))


def test_unique_short_answer_cannot_anchor_to_an_inserted_question():
    old = parse_transcript('Q First?\nA Yes.\nQ Second?\nA No.')
    new = parse_transcript('Q First changed?\nA No.\nQ New?\nA Yes.\nQ Second changed?\nA No.')
    ops = align_blocks(old, new)
    assert ('replace', 0, 1, 0, 1) in ops
    assert ('replace', 1, 2, 1, 2) in ops
    assert ('replace', 2, 3, 4, 5) in ops


def test_full_width_question_does_not_swallow_next_answer():
    text = 'Q ' + 'word ' * 10 + 'xxxx\nA Yes.'
    assert texts(formatted(text)) == texts(text)


def test_large_changed_transcript_keeps_each_question_with_its_answer():
    old = parse_transcript('\n'.join(f'Q Please describe item {i} before today.\nA Yes.' for i in range(1000)))
    new = parse_transcript('\n'.join(f'Q Please describe item {i} after today.\nA Yes.' for i in range(1000)))
    ops = align_blocks(old, new)
    assert len(ops) == 2000
    assert all(op == ('replace' if i % 2 == 0 else 'equal', i, i+1, i, i+1)
               for i, op in enumerate(ops))


def test_delete_question_preserves_surviving_answer():
    old = parse_transcript('Q First?\nA First.\nQ Removed?\nA Yes, I am.\nQ Good?')
    new = parse_transcript('Q First?\nA First.\nA Yes, I am.\nQ Good?')
    ops = align_blocks(old, new)
    assert [op for op in ops if op[0] != 'equal'] == [('delete', 2, 3, 2, 2)]


def test_unlabeled_indentation_round_trip_and_structural_diff():
    source = 'Q First question.\n          Have you been deposed before?\nA Yes.'
    for numbered in (False, True):
        blocks = parse_transcript(source)
        result = render_blocks(blocks, numbered)
        restored = parse_transcript(result)
        assert len(restored) == 3
        assert restored[1].indent == '          '
    joined = parse_transcript('Q First question. Have you been deposed before?\nA Yes.')
    assert any(op[0] != 'equal' for op in align_blocks(blocks, joined))


def test_question_only_deletion_with_repeated_answers():
    old = parse_transcript('Q First?\nA Yes.\nQ Removed?\nA Yes.\nQ Good?')
    new = parse_transcript('Q First?\nA Yes.\nA Yes.\nQ Good?')
    assert [op for op in align_blocks(old,new) if op[0] != 'equal'] == [('delete',2,3,2,2)]
