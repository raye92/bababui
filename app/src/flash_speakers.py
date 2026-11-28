"""Attach measured Transcribe times to the full-recording Flash transcript."""
from dataclasses import replace
from itertools import chain
import re

from rapidfuzz.distance import Levenshtein

from app.src.speech_alignment import WORD, Word


TURN = re.compile(r'^\s*(?:[-*]\s+)?(?:\*\*)?\[?Speaker\s+([1-9]\d*)\]?(?:\*\*)?\s*[:：](?:\*\*)?\s*',
                  re.IGNORECASE)


def _keys(text):
    return [m[0].casefold().replace("'", '').replace('’', '') for m in WORD.finditer(text)]


def _flash_words(text):
    words = []
    speaker = None
    starts_turn = False
    for line in text.splitlines():
        match = TURN.match(line)
        if match:
            speaker = 'Speaker ' + match[1]
            starts_turn = True
            line = line[match.end():]
        if speaker:
            for surface in line.split():
                words.append(Word(surface, speaker, None, None, starts_turn))
                starts_turn = False
    return words


def _native_tokens(chunks):
    keys, times = [], []
    for chunk_index, chunk in enumerate(chunks):
        for word in chunk:
            parts = _keys(word.text)
            keys.extend(parts)
            # A compound or legacy turn can span several tokens but has only
            # one measured start and end. Never invent its internal word times.
            for i in range(len(parts)):
                times.append((chunk_index, word.start if i == 0 else None,
                              word.end if i == len(parts) - 1 else None))
    return keys, times


def align_flash_words(chunks, flash_text):
    """Keep Flash turns intact and time only complete, contiguous word matches."""
    words = _flash_words(flash_text)
    parts = [_keys(w.text) for w in words]
    flash = list(chain.from_iterable(parts))
    if not flash:
        raise ValueError('Flash returned no labelled speaker turns.')

    native, times = _native_tokens(chunks)
    matches = [None] * len(flash)
    matched = 0
    for tag, a, b, x, y in Levenshtein.opcodes(native, flash):
        if tag == 'equal':
            matches[x:y] = range(a, b)
            matched += b - a
    if matched * 4 < max(len(native), len(flash)):
        raise ValueError('Flash speaker turns could not be matched to the Transcribe wording.')

    # Retain the source chunk for notice vocabulary windows, including words
    # with no time of their own. It never determines the displayed speaker.
    result = [[] for _ in chunks]
    chunk_index = offset = 0
    for word, keys in zip(words, parts):
        aligned = [i for i in matches[offset:offset + len(keys)] if i is not None]
        offset += len(keys)
        if aligned:
            first, last = aligned[0], aligned[-1]
            chunk_index, start, _ = times[first]
            end = times[last][2]
            contiguous = len(aligned) == len(keys) == last - first + 1
            if contiguous and start is not None and end is not None and start <= end:
                word = replace(word, start=start, end=end)
        result[chunk_index].append(word)
    return result
