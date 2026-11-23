from dataclasses import replace

import pytest

from app.src.audio_pipeline import Word
from app.src.casecat.anchors import AnchoredSpan, Revision


def revision(*pieces):
    return Revision(tuple(AnchoredSpan(str(i), (i,), (), text) for i, text in enumerate(pieces)))


def audio(*entries):
    return tuple(Word(text, 'speaker', seconds, seconds + .1) for text, seconds in entries)


def align(source, strokes, words, duration=30000):
    from app.src.speech_alignment import align_speech
    return align_speech(source, strokes, words, duration, 'f' * 64)


def test_stroke_gaps_follow_relative_spacing_between_speech_matches():
    source = revision('Early ', 'First ', 'clear ', 'phrase ', 'missed ', 'part ',
                      'Second ', 'clear ', 'phrase. ', 'After')
    strokes = (5000, 6000, 6500, 7000, 7300, 8200, 8500, 9000, 9500, 10000)
    words = audio(('first', 4), ('clear', 4.5), ('phrase', 5),
                  ('second', 6), ('clear', 6.5), ('phrase', 7))
    alignment = align(source, strokes, words)
    assert alignment.stroke_ms == (3000, 4000, 4500, 5000, 5200, 5800, 6000, 6500, 7000, 7500)
    ranges = alignment.playback()
    assert ranges.position_ms(source, source.text.index('missed')) == 5200
    assert ranges.position_ms(source, len(source.text)) == 7500


def test_repeated_phrases_need_distinctive_surrounding_words():
    source = revision('Yes I do. ', 'Yes I do. ', 'Purple ', 'eggs ', 'arrived.')
    words = audio(('yes', 1), ('i', 2), ('do', 3), ('yes', 6), ('i', 7), ('do', 8),
                  ('purple', 10), ('eggs', 11), ('arrived', 12))
    alignment = align(source, (2500, 8000, 12000, 13000, 14000), words)
    # The isolated repeated trigram is ambiguous. The words spanning the
    # repetitions and the next sentence support the available matches.
    assert alignment.stroke_ms == (2000, 6000, 10000, 11000, 12000)


def test_phrase_repeated_earlier_in_the_recording_cannot_retime_a_late_passage():
    source = revision('one ', 'two ', 'three ', 'four ', 'five ', 'six ',
                      'stand ', 'and ', 'listen ', 'seven ', 'eight ', 'nine.')
    words = audio(('one', 1), ('two', 2), ('three', 3), ('four', 4), ('five', 5), ('six', 6),
                  ('stand', 7), ('and', 8), ('listen', 9), ('seven', 100), ('eight', 101), ('nine', 102))
    native = (2000, 3000, 4000, 5000, 6000, 7000, 98000, 99000, 100000, 101000, 102000, 103000)
    alignment = align(source, native, words, duration=120000)
    position = source.text.index('stand')
    assert alignment.stroke_ms[6:9] == (97000, 98000, 99000)
    assert alignment.playback().position_ms(source, position) == 97000
    assert alignment.export_strokes(source)[6:9] == (97000, 98000, 99000)


def test_reversed_invalid_and_overlapping_words_do_not_move_playback_backward():
    source = revision('MS. SMITH: ', 'Bring ', 'the ', 'signed ', 'agreement ', 'over ', 'here ',
                      'right ', 'away.')
    words = list(audio(('Bring', 1), ('the', 2), ('signed', 3), ('agreement', 2.5),
                       ('over', 5), ('here', 6), ('right', 7), ('away', 8)))
    words[3] = replace(words[3], speaker='interrupting')
    words[5] = replace(words[5], end=4)
    words[6] = replace(words[6], start=45, end=46)
    playback = align(source, (None, 2000, 3100, 4000, 4200, 6000, 7000, None, 9000), words).playback()
    times = [time for _, _, time in playback.ranges(source)]
    assert times == sorted(times)
    assert min(times) == 1000 and max(times) == 8000
    assert playback.position_ms(source, source.text.index('signed')) < 4000


def test_global_clock_difference_is_learned_from_matching_phrases():
    source = revision('one ', 'two ', 'three ', 'four ', 'five ', 'six.')
    words = audio(('one', 1), ('two', 2), ('three', 3), ('four', 4), ('five', 5), ('six', 6))
    alignment = align(source, (32000, 33000, 34000, 35000, 36000, 37000), words, duration=50000)
    assert alignment.stroke_ms == (1000, 2000, 3000, 4000, 5000, 6000)


def test_incoming_inserted_word_uses_speech_when_the_stroke_places_it_later():
    source = revision('Bring ', 'the ', 'papers ', 'here ', 'after ', 'lunch.')
    words = audio(('bring', 4), ('the', 4.5), ('signed', 4.8), ('papers', 5),
                  ('here', 5.5), ('after', 6), ('lunch', 6.5))
    alignment = align(source, (5000, 5500, 6000, 6500, 7000, 7500), words)
    playback = alignment.playback()
    incoming = source.replace(source.text.index('papers'), source.text.index('papers'), 'signed ')
    assert playback.position_ms(incoming, incoming.text.index('signed')) == 4800
    assert playback.position_ms(incoming, incoming.text.index('papers')) == 5000
    assert playback.range_at(incoming, 4900) == (10, 17)
    assert playback.position_ms(source, source.text.index('papers')) == 5000


@pytest.mark.parametrize(('old_words', 'old_clocks'), [(('Original ', 'passage. '), (10000, 49000)), ((), ())],
                         ids=['replacement', 'insertion'])
def test_long_incoming_passage_uses_measured_words_across_a_shared_stroke(old_words, old_clocks):
    source = revision('Opening ', 'remarks ', 'conclude. ', *old_words, 'Back ', 'on ', 'record.')
    incoming = source.revise('Opening remarks conclude. Bring the large blue binder and read this page. Back on record.')
    seconds = (1, 2, 3, 8, 10, 20, 24, 33, 37, 40, 44, 48, 50, 52, 54)
    words = audio(*zip(incoming.text.split(), seconds, strict=True))
    strokes = (3000, 4000, 5000, *old_clocks, 52000, 54000, 56000)
    playback = align(source, strokes, words, duration=60000).playback()

    for word, time in [('Bring', 8000), ('large', 20000), ('blue', 24000), ('page', 48000)]:
        start = incoming.text.index(word)
        assert playback.position_ms(incoming, start) == time
        assert playback.range_at(incoming, time)[0] == start


@pytest.mark.parametrize('opening', [70, 1])
def test_incoming_replacement_keeps_context_when_words_match_far_earlier(opening):
    source = revision('We ', 'can ', 'adjourn. ', 'Thanks ', 'folks.')
    entries = [('Thank', 20), ('you', 21), ('very', 22), ('much', 23),
               ('We', opening), ('can', opening + 1), ('adjourn', opening + 2), ('Thanks', 100), ('folks', 101)]
    words = audio(*sorted(entries, key=lambda entry: entry[1]))
    strokes = (opening * 1000, (opening + 1) * 1000, (opening + 2) * 1000, 100000, 101000)
    playback = align(source, strokes, words, duration=120000).playback()
    incoming = source.replace(source.text.index('Thanks'), len(source.text), 'Thank you very much.')
    assert playback.position_ms(incoming, 0) == opening * 1000
    assert playback.position_ms(incoming, incoming.text.index('Thank')) == 101000


def test_unmatched_replacement_inherits_corrected_passage_range():
    source = revision('We ', 'can ', 'adjourn. ', 'Thanks ', 'folks.')
    words = audio(('We', 4), ('can', 5), ('adjourn', 6), ('Thanks', 7), ('folks', 8))
    playback = align(source, (6000, 7000, 8000, 9000, 10000), words).playback()
    changed = source.replace(0, len(source.text), 'A completely different sentence.')
    assert playback.position_ms(changed, 5) == 8000


def test_punctuation_only_passage_can_still_seek_to_its_source():
    source = revision('One ', 'two ', 'three.')
    words = audio(('one', 4), ('two', 5), ('three', 6))
    playback = align(source, (6000, 7000, 8000), words).playback()
    changed = source.replace(0, len(source.text), '...')
    assert playback.position_ms(changed, 1) == 6000
    assert playback.range_at(changed, 6000) == (0, 3)


@pytest.mark.parametrize('text', ['one two three', 'unrelated words and wrong testimony'])
def test_too_little_matching_speech_leaves_native_playback(text):
    source = revision('one ', 'two ', 'three ', *(f'word{i} ' for i in range(50)))
    words = tuple(Word(word, 'speaker', i, i + .1) for i, word in enumerate(text.split()))
    assert align(source, tuple(range(len(source.spans))), words) is None


def test_alignment_can_use_speech_when_native_timing_is_missing():
    source = revision('One ', 'two ', 'three ', 'gap ', 'four ', 'five ', 'six.')
    words = audio(('one', 3), ('two', 4), ('three', 5), ('four', 7), ('five', 8), ('six', 9))
    alignment = align(source, (None,) * 7, words)
    assert alignment.stroke_ms == (3000, 4000, 5000, 6000, 7000, 8000, 9000)


def test_untimed_transcript_leaves_native_stroke_timing():
    source = revision('One ', 'two ', 'three ', 'four ', 'five ', 'six.')
    words = tuple(Word(word, 'speaker', None, None) for word in source.text.split())
    assert align(source, (1000, 2000, 3000, 4000, 5000, 6000), words) is None


@pytest.mark.parametrize('refs', [(), (0,)])
def test_speech_playback_survives_reopen_without_distinct_stroke_anchors(refs):
    from app.src.speech_alignment import SpeechAlignment

    source = Revision((AnchoredSpan('source', refs, (), 'Read the first page. Then sign here.'),))
    words = audio(*zip(source.text.split(), (2, 3, 4, 5, 60, 61, 62)))
    alignment = align(source, (None,) * len(refs), words, duration=70000)

    assert alignment is not None
    playback = SpeechAlignment.restore(vars(alignment), len(refs)).playback()
    assert playback.position_ms(source, 0) == 2000
    assert playback.position_ms(source, source.text.index('sign')) == 61000


def test_typing_reuses_measured_speech_for_changed_and_untouched_passages(monkeypatch):
    from app.src import speech_alignment as speech
    source = revision('Please bring the papers.\n', 'Then sign each page.')
    entries = [('please', 1), ('bring', 2), ('the', 3), ('signed', 9), ('papers', 12),
               ('then', 17), ('sign', 18), ('each', 19), ('page', 21)]
    playback = align(source, (2000, 17000), audio(*entries)).playback()
    assert playback.position_ms(source, source.text.index('papers')) == 12000

    def full_scan(*args):
        raise AssertionError('A local edit realigned the entire transcript.')
    monkeypatch.setattr(speech, '_passages', full_scan)
    pos = source.text.index('papers')
    old = source
    for text in ('s', 'i', 'g', 'n', 'e', 'd', ' '):
        new = old.replace(pos, pos, text)
        playback.track_edit(old, new, pos, pos, text)
        assert playback.position_ms(new, new.text.index('sign each')) == 18000
        old, pos = new, pos+1
    assert playback.position_ms(new, new.text.index('signed')) == 9000
    assert playback.position_ms(new, new.text.index('papers')) == 12000
    assert playback.range_at(new, 9000) == (new.text.index('signed'), new.text.index('papers'))
    assert playback.position_ms(source, source.text.index('papers')) == 12000


def test_edit_tracking_leaves_a_cold_speech_index_lazy(monkeypatch):
    from app.src import speech_alignment as speech
    source = revision('One two three.')
    playback = align(source, (0,), audio(('one', 1), ('two', 2), ('three', 3))).playback()
    monkeypatch.setattr(speech, '_passages', lambda *a: pytest.fail('cold cache rebuilt during typing'))
    changed = source.replace(2, 2, 'x')
    playback.track_edit(source, changed, 2, 2, 'x')


def test_paragraph_join_keeps_later_word_time_and_drops_deleted_speech():
    source = revision('Opening remarks here.\n', 'Read the last page.\n', 'Then sign here.')
    entries = list(zip(source.text.split(), (1, 2, 3, 6, 7, 8, 9, 12, 13, 14)))
    playback = align(source, (1000, 6000, 12000), audio(*entries)).playback()
    playback.ranges(source)
    start, end = source.text.index('\n'), source.text.index('Then')
    updated = source.replace(start, end, ' ')
    playback.track_edit(source, updated, start, end, ' ')
    assert playback.position_ms(updated, updated.text.index('Then')) == 12000
    assert playback.position_ms(updated, updated.text.index('sign')) == 13000
    assert playback.range_at(updated, 7000)[0] == updated.text.index('here')


def test_typo_in_measured_word_keeps_its_audio_passage_until_new_word_matches():
    source = revision('Bring the result after lunch.')
    words = audio(('Bring', 1), ('the', 2), ('result', 12), ('after', 16), ('lunch', 19))
    playback = align(source, (0,), words).playback()
    word = source.text.index('result')
    assert playback.position_ms(source, word) == 12000
    changed = source.replace(word+3, word+3, 'x')
    playback.track_edit(source, changed, word+3, word+3, 'x')
    assert playback.position_ms(changed, word) == 12000
    assert playback.range_at(changed, 12000)[0] == word
