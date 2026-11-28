"""Transfer recording-wide Flash speaker IDs onto Transcribe's own words."""
from collections import Counter, defaultdict
from dataclasses import replace
from itertools import groupby, pairwise
from operator import itemgetter
import re

from rapidfuzz.distance import Levenshtein

from app.src.speech_alignment import WORD


TURN = re.compile(r'^\s*(?:[-*]\s+)?(?:\*\*)?\[?Speaker\s+([1-9]\d*)\]?(?:\*\*)?\s*[:：](?:\*\*)?\s*',
                  re.IGNORECASE)
SENTENCE_END = re.compile(r'''[.!?…][)"'”’\]]*$''')


def _keys(text):
    return [m[0].casefold().replace("'", '').replace('’', '') for m in WORD.finditer(text)]


def _flash_tokens(text):
    tokens, labels = [], []
    speaker = None
    for line in text.splitlines():
        match = TURN.match(line)
        if match:
            speaker = 'Speaker ' + match[1]
            line = line[match.end():]
        if speaker:
            keys = _keys(line)
            tokens.extend(keys)
            labels.extend([speaker] * len(keys))
    if not tokens:
        raise ValueError('Flash returned no labelled speaker turns.')
    return tokens, labels


def _majority(votes):
    if votes:
        speaker, count = votes.most_common(1)[0]
        if count * 2 > votes.total():
            return speaker
    return None


def _fill_gap(words, local, labels, backup, left, right):
    before = labels[left] if left >= 0 else None
    after = labels[right] if right < len(labels) else None
    left_key = local[left] if before else None
    right_key = local[right] if after else None
    hints = []
    for key in local[left + 1:right]:
        # An ID that straddles a known Flash switch cannot locate that switch.
        if key and key == left_key == right_key:
            hints.append(before if before == after else None)
        elif key and key == left_key:
            hints.append(before)
        elif key and key == right_key:
            hints.append(after)
        else:
            hints.append(backup.get(key))
    if before is None or after is None or before == after:
        labels[left + 1:right] = [hint or before or after for hint in hints]
        return

    # Compare every possible word boundary. Native speaker evidence comes first,
    # then a sentence ending, then a measured pause. Ties favor the incoming turn.
    agreements = hints.count(after)
    best, split = None, left + 1
    for i in range(left + 1, right + 1):
        prev, following = words[i - 1], words[i]
        pause = (max(0, following.start - prev.end)
                 if following.start is not None and prev.end is not None else 0)
        score = (agreements, bool(SENTENCE_END.search(prev.text)), pause)
        if best is None or score > best:
            best, split = score, i
        if i < right:
            hint = hints[i - left - 1]
            agreements += (hint == before) - (hint == after)
    for i, hint in enumerate(hints, left + 1):
        labels[i] = hint if hint and hint not in (before, after) else (before if i < split else after)


def _word_labels(words, local, flash_text):
    flash, flash_labels = _flash_tokens(flash_text)
    tokens, owners = [], []
    for i, word in enumerate(words):
        keys = _keys(word.text)
        owners.extend([i] * len(keys))
        tokens.extend(keys)

    votes = defaultdict(Counter)
    substitutions = defaultdict(Counter)
    speaker_votes = defaultdict(Counter)
    matched_tokens = 0
    for tag, a, b, x, y in Levenshtein.opcodes(tokens, flash):
        if tag == 'equal':
            matched_tokens += b - a
            for owner, speaker in zip(owners[a:b], flash_labels[x:y]):
                votes[owner][speaker] += 1
                if local[owner] is not None:
                    speaker_votes[local[owner]][speaker] += 1
        elif tag == 'replace' and x < y and len(set(flash_labels[x:y])) == 1:
            for owner in owners[a:b]:
                substitutions[owner][flash_labels[x]] += 1
    # A stray common word cannot establish a roster for an unrelated or truncated response.
    if matched_tokens * 4 < max(len(tokens), len(flash)):
        raise ValueError('Flash speaker turns could not be matched to the Transcribe wording.')

    labels = [None] * len(words)
    for owner in votes.keys() | substitutions.keys():
        evidence = votes.get(owner) or substitutions[owner]
        labels[owner] = evidence.most_common(1)[0][0]
    backup = {key: _majority(evidence) for key, evidence in speaker_votes.items()}
    anchors = [-1, *(i for i, label in enumerate(labels) if label), len(words)]
    for left, right in pairwise(anchors):
        if right > left + 1:
            _fill_gap(words, local, labels, backup, left, right)
    return labels


def apply_flash_speakers(chunks, flash_text):
    """Use matched speech anywhere in each chunk to map its local labels to Flash IDs."""
    words, local, legacy_spans = [], [], {}
    for ci, chunk in enumerate(chunks):
        for wi, word in enumerate(chunk):
            units = [word]
            if word.start is None and word.end is None:
                # Older caches sometimes have a whole turn in one untimed record.
                spans = list(re.finditer(r'\S+', word.text))
                if len(spans) > 1:
                    legacy_spans[ci, wi] = spans
                    units = [replace(word, text=span[0]) for span in spans]
            words.extend(units)
            key = (ci, word.speaker) if word.speaker is not None else None
            local.extend([key] * len(units))
    labels = iter(_word_labels(words, local, flash_text))
    result = []
    for ci, chunk in enumerate(chunks):
        labelled = []
        for wi, word in enumerate(chunk):
            spans = legacy_spans.get((ci, wi))
            if not spans:
                labelled.append(replace(word, speaker=next(labels)))
                continue
            groups = groupby(((next(labels), span) for span in spans), itemgetter(0))
            for label, members in groups:
                positions = [span for _, span in members]
                surface = word.text[positions[0].start():positions[-1].end()]
                labelled.append(replace(word, speaker=label, text=surface))
        result.append(labelled)
    return result
