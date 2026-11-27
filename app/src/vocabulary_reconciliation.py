"""Reconcile confirmed notice spellings with recorded and formatted testimony."""
from collections import defaultdict
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import re
import unicodedata


_LEXEME = re.compile(r"[^\W_]+(?:['’.\-‐‑][^\W_]+)*|&")
_FIRM_WORDS = {'and', 'associates', 'attorneys', 'company', 'corporation', 'counsel', 'firm',
               'group', 'law', 'lawyers', 'legal', 'limited', 'offices', 'partners', 'professional'}
_TITLES = {'mr', 'mrs', 'ms', 'miss', 'dr', 'doctor', 'prof', 'professor'}


def normalized_vocabulary(terms):
    """Use the same vocabulary and cache key regardless of input order or extra spaces."""
    terms = {' '.join(term.split()) for term in terms if any(c.isalnum() for c in term)}
    return tuple(sorted(terms, key=lambda term: (term.casefold(), term)))


def _lexemes(text):
    for match in _LEXEME.finditer(text):
        spelling = match.group()
        # A possessive belongs to the surrounding testimony.
        if len(spelling) > 2 and spelling.casefold().endswith(("'s", '’s')):
            spelling = spelling[:-2]
        yield match.start(), match.start() + len(spelling), spelling


def _key(surface):
    if surface == '&':
        return 'and'
    return unicodedata.normalize('NFC', surface.casefold()).replace('’', "'").replace('‑', '-').replace('‐', '-')


def _term_index(terms):
    phrases, components = {}, {}
    for term in terms:
        forms = tuple(form for _, _, form in _lexemes(term))
        keys = tuple(map(_key, forms))
        if not keys:
            continue
        phrases[keys] = forms
        for key, form in zip(keys, forms):
            if len(key) >= 4 and form[0].isupper() and key not in _FIRM_WORDS:
                components[(key,)] = (form,)
    index = defaultdict(list)
    for keys, forms in (components | phrases).items():
        index[keys[0]].append((keys, forms, keys not in phrases))
    for options in index.values():
        options.sort(key=lambda option: len(option[0]), reverse=True)
    return index


@dataclass(frozen=True)
class _Token:
    word: int
    start: int
    end: int
    key: str


def _source_bounds(words, ranges):
    """An untimed word is bounded by its source chunk and neighboring measured words."""
    bounds = list(ranges)
    following = None
    for i in reversed(range(len(words))):
        low, high = ranges[i]
        if words[i].start is not None:
            following = words[i].start
            bounds[i] = (following, words[i].end)
        elif following is not None:
            bounds[i] = low, min(high, max(low, following))
    previous = None
    for i, word in enumerate(words):
        if word.start is not None:
            previous = word.end
        elif previous is not None:
            low, high = bounds[i]
            previous_bound = min(ranges[i][1], max(low, previous))
            bounds[i] = min(previous_bound, high), max(previous_bound, high)
    return bounds


def _alignment(base, heard):
    """Only project boundaries supported by the alignment. Unequal gaps have no internal map."""
    starts, ends, anchors = {}, {}, set()
    for tag, i, stop, j, end in SequenceMatcher(None, base, heard).get_opcodes():
        if i == stop or j == end:
            continue
        if stop - i == end - j:
            for offset in range(end - j):
                starts[j + offset] = i + offset
                ends[j + offset] = i + offset + 1
        else:
            starts[j], ends[end - 1] = i, stop
        if tag == 'equal':
            anchors.update(range(j, end))
    return starts, ends, anchors


def _similar(old, new):
    def letters(key):
        return ''.join(c for c in unicodedata.normalize('NFKD', key) if c.isalnum())

    left, right = list(map(letters, old)), list(map(letters, new))
    a, b = ''.join(left), ''.join(right)
    match = SequenceMatcher(None, a, b)
    ratio = match.ratio()
    if len(old) != len(new):
        if ratio < .8:
            return False
        # Each word must contribute letters to the other spelling, including a standalone initial.
        blocks = match.get_matching_blocks()
        for parts, offsets in ((left, {p.a + k for p in blocks for k in range(p.size)}),
                               (right, {p.b + k for p in blocks for k in range(p.size)})):
            offset = 0
            for part in parts:
                if offsets.isdisjoint(range(offset, offset + len(part))):
                    return False
                offset += len(part)
        return True
    return ratio >= .65 or (min(len(a), len(b)) >= 4 and a[0] == b[0] and a[-1] == b[-1] and ratio >= .5)


def _testimony_lexemes(text):
    from app.src.suggestion_filter import LABEL, QA_PREFIX

    offset = 0
    for line in text.splitlines(keepends=True):
        marker = LABEL.match(line) or QA_PREFIX.match(line)
        label, colon, _ = line.partition(':')
        custom_label = colon and (label.isupper() or label.lstrip().upper().startswith('BY '))
        start = len(label) + 1 if custom_label else 0
        if marker:
            start = marker.end()
        for a, b, word in _lexemes(line[start:]):
            yield offset + start + a, offset + start + b, word
        offset += len(line)


def _name_context(text, tokens, keys, i, adjacent):
    start, end, spelling = tokens[i]
    if i:
        gap = text[tokens[i - 1][1]:start]
        if keys[i - 1] in _TITLES and gap.strip() in ('', '.'):
            return True
        if (keys[i - 1], keys[i]) in adjacent and gap.isspace():
            return True
        if not spelling.isupper() and not re.search(r'[.!?:\r\n]', gap):
            return True  # Distinctive capitalization inside a sentence.
    return (i + 1 < len(tokens) and (keys[i], keys[i + 1]) in adjacent
            and text[end:tokens[i + 1][0]].isspace())


def preserve_notice_spellings(original, formatted, vocabulary):
    """Keep a notice spelling when the same spoken name occurs in the original testimony."""
    confirmed, adjacent = set(), set()
    for term in vocabulary:
        keys = [_key(word) for _, _, word in _lexemes(term)]
        confirmed.update(key for key in keys if len(key) > 1 and key not in _FIRM_WORDS)
        adjacent.update(zip(keys, keys[1:]))
    if not confirmed or original == formatted:
        return formatted
    source = list(_testimony_lexemes(original))
    proposal = list(_testimony_lexemes(formatted))
    old = [_key(word) for _, _, word in source]
    new = [_key(word) for _, _, word in proposal]
    # A different name already used in the notice or testimony stays available for review.
    other_names = confirmed | {key for key, (_, _, word) in zip(old, source) if word[0].isupper()}
    starts, ends, matches = _alignment(new, old)
    edits = []
    for i, (_, _, spelling) in enumerate(source):
        j = starts.get(i)
        if j is None or ends.get(i) != j + 1 or old[i] not in confirmed or not spelling[0].isupper():
            continue
        a, b, candidate = proposal[j]
        if not candidate[0].isupper() or new[j] in other_names or not _similar([old[i]], [new[j]]):
            continue
        # Require surviving words next to this occurrence, even across a split or joined turn.
        anchors = sum(i + step in matches and starts[i + step] == j + step for step in (-2, -1, 1, 2))
        if anchors >= 2 and _name_context(original, source, old, i, adjacent):
            edits.append((a, b, spelling))
    for a, b, spelling in reversed(edits):
        formatted = formatted[:a] + spelling + formatted[b:]
    return formatted


def _spellings(old, new, forms):
    """Keep matching words separate and the measured extent of a resegmented name."""
    edits = []
    for tag, i, stop, j, end in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ('insert', 'delete'):
            return []  # Spelling evidence cannot add or remove spoken words.
        if stop - i == end - j:
            for a, b in zip(range(i, stop), range(j, end)):
                if old[a] != new[b] and not _similar([old[a]], [new[b]]):
                    return []
                edits.append((a, a + 1, forms[b]))
        elif _similar(old[i:stop], new[j:end]):
            edits.append((i, stop, ' '.join(forms[j:end])))
        else:
            return []
    return edits


def _unplaced_repeat(base, i, stop, heard, j, end, locations, mapped):
    """A dropped repetition can make the same observation fit more than one speaker or turn."""
    before = after = 0
    while before < min(4, i, j) and base[i - before - 1] == heard[j - before - 1]:
        before += 1
    while after < min(4, len(base) - stop, len(heard) - end) and base[stop + after] == heard[end + after]:
        after += 1
    context = base[i - before:stop + after]
    return any(other not in mapped and other >= before
               and base[other - before:other + stop - i + after] == context for other in locations[base[i]])


def _window_edits(words, tokens, selected, text, terms):
    base = [tokens[i].key for i in selected]
    heard = [form for _, _, form in _lexemes(text)]
    keys = list(map(_key, heard))
    starts, ends, anchors = _alignment(base, keys)
    mapped = set(starts.values())
    locations = defaultdict(list)
    for index, key in enumerate(base):
        locations[key].append(index)
    j = 0
    while j < len(keys):
        for phrase, forms, component in terms.get(keys[j], ()):
            end = j + len(phrase)
            if tuple(keys[j:end]) == phrase and (not component or heard[j][0].isupper()):
                break
        else:
            j += 1
            continue
        begin = j
        i, stop = starts.get(begin), ends.get(end - 1)
        local_context = any(k in anchors for k in range(max(0, j - 2), min(len(keys), end + 2)))
        whole_window = i == 0 and stop == len(base) and j == 0 and end == len(keys)
        j = end
        if i is None or stop is None or i >= stop or not (local_context or whole_window):
            continue
        if _unplaced_repeat(base, i, stop, keys, begin, end, locations, mapped):
            continue
        first, last = selected[i], selected[stop - 1]
        if last - first + 1 != stop - i:
            continue
        span = words[tokens[first].word:tokens[last].word + 1]
        if any(w.speaker != span[0].speaker for w in span):
            continue
        forms = tuple(spoken if form.isupper() and spoken[0].isupper() else form
                      for form, spoken in zip(forms, heard[begin:end]))
        for offset, finish, spelling in _spellings(base[i:stop], phrase, forms):
            yield first + offset, first + finish, spelling


def reconcile_vocabulary(words, source_ranges, windows, vocabulary):
    """Locate each vocabulary observation in its own time window on the original stitched words."""
    terms = _term_index(vocabulary)
    tokens = [_Token(i, start, end, _key(form)) for i, w in enumerate(words)
              for start, end, form in _lexemes(w.text)]
    bounds = _source_bounds(words, source_ranges)
    proposals = set()
    for start, end, text in windows:
        selected = [i for i, t in enumerate(tokens) if bounds[t.word][0] < end and bounds[t.word][1] >= start]
        proposals.update(_window_edits(words, tokens, selected, text, terms))

    # Identical edits from the overlapping minute count once. Disagreeing edits leave the base spelling.
    groups = []
    limit = 0
    for proposal in sorted(proposals):
        if not groups or proposal[0] >= limit:
            groups.append([])
        groups[-1].append(proposal)
        limit = max(limit, proposal[1])

    result = list(words)
    for group in reversed(groups):
        if len(group) != 1:
            continue
        start, end, spelling = group[0]
        a, b = tokens[start], tokens[end - 1]
        first, last = result[a.word], result[b.word]
        if a.word == b.word and first.text[a.start:b.end] == spelling:
            continue
        if a.word != b.word:
            timed = [w.start is not None for w in result[a.word:b.word + 1]]
            if any(timed) and (not all(timed) or first.start > last.end):
                continue
        text = first.text[:a.start] + spelling + last.text[b.end:]
        if first.start is None or last.end is None or first.start > last.end:
            merged = replace(first, text=text, start=None, end=None)
        else:
            merged = replace(first, text=text, end=last.end)
        result[a.word:b.word + 1] = [merged]
    return tuple(result)
