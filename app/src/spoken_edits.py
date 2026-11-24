"""Find retained testimony when a paragraph diff anchors on transcript furniture."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from itertools import groupby
import re

from app.src.off_record import TOKEN, is_off_record_note
from shared.transcript_formatting import TranscriptFormatter


QA = re.compile(r'^[ \t]*[QA](?:[ \t]+|$)')
BYLINE = re.compile(r'^[ \t]*BY[ \t]+[^:\n]+:[ \t]*$', re.I | re.M)


@dataclass(frozen=True)
class Turn:
    start: int
    body: int
    end: int
    kind: str
    words: tuple
    label: str
    section: int


def _turns(text, labels):
    turns, words = [], []
    start = section = 0
    for index, line in enumerate(text.split('\n')):
        named = labels.match(line)
        marker = named or QA.match(line)
        body = len(line) - len(line[marker.end():].lstrip(' \t')) if marker else 0
        kind = 'named' if named else 'qa' if marker else ''
        note = is_off_record_note(line)
        section += int(note)
        structural = (note or BYLINE.fullmatch(line)
                      or TranscriptFormatter.structural_line.fullmatch(line.strip()))
        matches = () if structural else tuple(TOKEN.finditer(line, body))
        tokens = tuple((start + m.start(), start + m.end()) for m in matches)
        label = named['name'] if named else marker[0].strip() if marker else ''
        turns.append(Turn(start, start + body, start + len(line), kind, tokens, label.casefold(), section))
        words.extend((m[0].casefold().replace('’', "'"), index, i) for i, m in enumerate(matches))
        start += len(line) + 1
    return turns, words


def _phrase_anchors(old, new):
    """Find the longest ordered chain of unique three-word phrases."""
    def phrases(words):
        index = {}
        for i, key in enumerate(zip(words, words[1:], words[2:])):
            index[key] = None if key in index else i
        return index

    source, target = phrases(old), phrases(new)
    tails, indices, nodes = [], [], []
    for phrase, a in source.items():
        b = target.get(phrase)
        if a is None or b is None:
            continue
        k = bisect_left(tails, b)
        nodes.append((a, b, indices[k-1] if k else -1))
        if k == len(tails):
            tails.append(b)
            indices.append(len(nodes)-1)
        else:
            tails[k], indices[k] = b, len(nodes)-1
    anchors = []
    k = indices[-1] if indices else -1
    while k >= 0:
        a, b, k = nodes[k]
        anchors.append((a, b))
    return reversed(anchors)


def _word_matches(old, new):
    """Compare the gaps between ordered phrases, including repeated words."""
    a = b = 0
    for x, y in [*_phrase_anchors(old, new), (len(old), len(new))]:
        if x < a or y < b:
            continue
        if x > a and y > b:
            for i, j, size in SequenceMatcher(None, old[a:x], new[b:y], autojunk=False).get_matching_blocks():
                yield from zip(range(a+i, a+i+size), range(b+j, b+j+size))
        if x < len(old):
            yield from zip(range(x, x+3), range(y, y+3))
        a, b = x+3, y+3


def passage_edits(left, right, labels, inner):
    """Bound expensive character comparisons using exact words inside anchored speech."""
    window = 3000
    if max(len(left), len(right)) < 2*window or '\n' not in left or '\n' not in right:
        return inner(left, right)
    old, words_a = _turns(left, labels)
    new, words_b = _turns(right, labels)
    anchors = _phrase_anchors([w[0] for w in words_a], [w[0] for w in words_b])
    cuts = [(0, 0)]
    for i, j in anchors:
        _, row, word = words_a[i+1]
        _, other, token = words_b[j+1]
        if (old[row].section != new[other].section or words_a[i][1] != words_a[i+2][1]
                or words_b[j][1] != words_b[j+2][1]):
            continue
        a, b = old[row].words[word]
        c, d = new[other].words[token]
        if max(a-cuts[-1][0], c-cuts[-1][1]) >= window and left[a:b] == right[c:d]:
            cuts.append((a, c))
    cuts.append((len(left), len(right)))
    result = []
    for (a, c), (b, d) in zip(cuts, cuts[1:]):
        result.extend((a+x, a+y, c+z, c+w) for x, y, z, w in inner(left[a:b], right[c:d]))
    return result


def _pairs(left, right, old_words, new_words):
    """Use monotone word correspondence, including parts of split and joined turns."""
    links = defaultdict(list)
    sections = [{key: list(chunk) for key, chunk in groupby(words, lambda w: rows[w[1]].section)}
                for rows, words in ((left, old_words), (right, new_words))]
    for key, aa in sections[0].items():
        bb = sections[1].get(key, [])
        for a, b in _word_matches([w[0] for w in aa], [w[0] for w in bb]):
            x, y = aa[a], bb[b]
            links[x[1], y[1]].append((x[2], y[2]))
    result = []
    for (i, j), matches in links.items():
        n, m = len(left[i].words), len(right[j].words)
        longest = run = 1
        for (a, b), (c, d) in zip(matches, matches[1:]):
            run = run + 1 if (c, d) == (a+1, b+1) else 1
            longest = max(longest, run)
        # A short reply can survive as part of a longer turn. An isolated
        # article or a common two-word fragment in two long turns cannot anchor one.
        if (longest >= 4 or (longest >= 2 and (len(matches) * 2 >= min(n, m)
                                                or matches[0] == (0, 0)))
                or len(matches) >= 2 and matches[0] == (0, 0) and min(n, m) <= 6
                or n == m == len(matches) == 1):
            result.append((i, j, matches))
    # A single common opening word can anchor a rewritten short reply between
    # strong neighboring turns if neither side has a competing match there.
    strong = {(i, j) for i, j, _ in result}
    for (i, j), matches in links.items():
        if ((i, j) not in strong and matches[0] == (0, 0)
                and min(len(left[i].words), len(right[j].words)) <= 3
                and (i-1, j-1) in strong and not any(x == i or y == j for x, y in strong)):
            result.append((i, j, matches))
    result.sort()
    # An identical repeated reply can have a changed number of occurrences.
    # Prefer its surviving speaker/QA label within the same aligned interval.
    keys = []
    copies = []
    for rows, words in ((left, old_words), (right, new_words)):
        bodies = defaultdict(list)
        for word, row, _ in words:
            bodies[row].append(word)
        keys.append({row: tuple(body) for row, body in bodies.items()})
        lookup = defaultdict(list)
        for row in bodies:
            lookup[rows[row].section, rows[row].label, keys[-1][row]].append(row)
        copies.append(lookup)
    for k, (a, b, matches) in enumerate(result):
        prev = result[k-1][:2] if k else (-1, -1)
        nxt = result[k+1][:2] if k+1 < len(result) else (len(left), len(right))
        if left[a].label == right[b].label or not (prev[0] < a < nxt[0] and prev[1] < b < nxt[1]):
            continue
        old = [i for i in copies[0].get((left[a].section, right[b].label, keys[0][a]), ()) if prev[0] < i < nxt[0]]
        new = [j for j in copies[1].get((right[b].section, left[a].label, keys[1][b]), ()) if prev[1] < j < nxt[1]]
        if len(old) + len(new) == 1:
            result[k] = (old[0] if old else a, new[0] if new else b, matches)

    # A short final reply with a spelling correction may share no complete
    # word. Require the same named/QA prefix and a unique, close spelling.
    words = [{(row, i): value for value, row, i in side} for side in (old_words, new_words)]
    for (i, j), (k, l) in zip([(-1, -1), *[(a, b) for a, b, _ in result]],
                                [*[(a, b) for a, b, _ in result], (len(left), len(right))]):
        if min(k-i, l-j) <= 1:
            continue
        candidates = []
        for a in range(i+1, k):
            if len(left[a].words) != 1 or not left[a].kind:
                continue
            for b in range(j+1, l):
                if (len(right[b].words) != 1 or right[b].label != left[a].label
                        or right[b].section != left[a].section):
                    continue
                x, y = words[0][a, 0], words[1][b, 0]
                if min(len(x), len(y)) >= 3 and SequenceMatcher(None, x, y).ratio() >= .8:
                    candidates.append((a, b))
        if len(candidates) == 1:
            a, b = candidates[0]
            result.append((a, b, [(0, 0)]))
    result.sort()
    return result


def _sentence_end(text, word_end, turn_end):
    punctuation = re.match(r'''[.!?]+["'”’)]*(?=\s|$)''', text[word_end:turn_end])
    return word_end + punctuation.end() if punctuation else word_end


def _local_edits(left, right, a, b, c, d, inner):
    old, new = left[a:b], right[c:d]
    if old == new:
        return []
    # Between two retained turns, keep a shared paragraph separator on the
    # side where the preceding sentence actually ends.
    if old == '\n' or new == '\n':
        long = new if old == '\n' else old
        if long.startswith('\n'):
            a, c = a+1, c+1
        elif long.endswith('\n'):
            b, d = b-1, d-1
    if a == b or c == d:
        return [(a, b, c, d)]
    return [(a+x, a+y, c+z, c+w) for x, y, z, w in inner(left[a:b], right[c:d])]


def refine(left, right, raw, labels, inner, speakers=()):
    """Rediff only passages where structural edits swallow surviving spoken words."""
    if not raw:
        return raw, set()
    if '\n' not in left and '\n' not in right:
        # A single turn can still change from colloquy to Q/A.
        if not ((labels.match(left) and QA.match(right)) or (QA.match(left) and labels.match(right))):
            return raw, set()
    multiline = [s for s in raw if '\n' in left[s[0]:s[1]] or '\n' in right[s[2]:s[3]]]
    if not multiline and ':' not in left and ':' not in right:
        return raw, set()

    # Trim identical surrounding lines before word matching. This also keeps
    # a small change inside a repetitive transcript independent of its length.
    first, last = raw[0], raw[-1]
    a0 = left.rfind('\n', 0, first[0]) + 1
    c0 = right.rfind('\n', 0, first[2]) + 1
    end_a = left.find('\n', last[1])
    end_c = right.find('\n', last[3])
    end_a = len(left) if end_a < 0 else end_a
    end_c = len(right) if end_c < 0 else end_c
    old, w1 = _turns(left[a0:end_a], labels)
    new, w2 = _turns(right[c0:end_c], labels)
    if not any(t.kind for t in (*old, *new)):
        return raw, set()
    pairs = _pairs(old, new, w1, w2)
    if not pairs:
        return raw, set()
    # Each unchanged gap is a safe seam with the existing inner diff. Keep
    # that diff verbatim outside passages identified by lexical evidence.
    ends = [b for _, b, _, _ in raw]
    def seam(a, c):
        k = bisect_right(ends, a)
        for n in range(max(0, bisect_left(ends, a)), k+1):
            x, z = (raw[n-1][1], raw[n-1][3]) if n else (0, 0)
            y = raw[n][0] if n < len(raw) else len(left)
            if x <= a <= y and a-x == c-z:
                return n
        return None

    structural_ends = [[s[side+1] for s in multiline] for side in (0, 2)]
    def swallowed(start, stop, side):
        index = bisect_right(structural_ends[side//2], start)
        return index < len(multiline) and multiline[index][side] < stop

    cuts = {(0, 0), (len(left), len(right))}
    hot, roles, paired_names = [], set(), set()
    for k, (i, j, words) in enumerate(pairs):
        x, y = old[i], new[j]
        first_a, first_c = words[0]
        last_a, last_c = words[-1]
        prev = pairs[k-1][:2] if k else (-1, -1)
        nxt = pairs[k+1][:2] if k+1 < len(pairs) else (len(old), len(new))
        begins = prev[0] != i and prev[1] != j
        ends_here = nxt[0] != i and nxt[1] != j
        if not begins or not ends_here:
            # Two copies of the surviving speech in the same turn do not
            # establish which copy moved. Keep the existing inner comparison.
            xphrase = left[a0+x.words[first_a][0]:a0+x.words[last_a][1]].casefold()
            yphrase = right[c0+y.words[first_c][0]:c0+y.words[last_c][1]].casefold()
            if len(words) >= 4 and (left[a0+x.body:a0+x.end].casefold().count(xphrase) > 1
                                    or right[c0+y.body:c0+y.end].casefold().count(yphrase) > 1):
                continue
        if (begins and {x.kind, y.kind} == {'qa', 'named'} and
                ((i and not old[i-1].words and old[i-1].kind == y.kind and
                  seam(a0+old[i-1].body, c0+y.body) is not None)
                 or (j and not new[j-1].words and new[j-1].kind == x.kind and
                     seam(a0+x.body, c0+new[j-1].body) is not None))):
            continue  # Speech joined an existing empty labelled paragraph.
        start = (a0 + (x.start if begins else x.words[first_a][0]),
                 c0 + (y.start if begins else y.words[first_c][0]))
        if begins:
            cuts.add(start)
            prefix = (a0+x.start, a0+x.body, c0+y.start, c0+y.body)
            if {x.kind, y.kind} == {'qa', 'named'}:
                roles.add(prefix)
                hot.append((prefix[0], prefix[2], prefix[1], prefix[3]))
            elif x.kind == y.kind == 'named':
                paired_names.add(start)
            cuts.add((prefix[1], prefix[3]))
        else:
            cuts.add(start)

        u = _sentence_end(left, a0+x.words[last_a][1], a0+x.end)
        v = _sentence_end(right, c0+y.words[last_c][1], c0+y.end)
        if nxt[1] == j and nxt[0] != i:
            # The end of this old turn has its own sentence on the other
            # side, even if the last spoken word was corrected there.
            next_word = pairs[k+1][2][0][1]
            boundary = re.search(r'[.!?](?=\s|$)', right[v:c0+y.words[next_word][0]])
            if boundary and left[a0+x.end-1:a0+x.end] in ('.', '?', '!'):
                u, v = a0+x.end, v+boundary.end()
        elif nxt[0] == i and nxt[1] != j:
            next_word = pairs[k+1][2][0][0]
            boundary = re.search(r'[.!?](?=\s|$)', left[u:a0+x.words[next_word][0]])
            if boundary and right[c0+y.end-1:c0+y.end] in ('.', '?', '!'):
                u, v = u+boundary.end(), c0+y.end
        if ends_here:
            # Additional sentences followed by wholly new turns form one
            # contiguous addition up to the next surviving turn.
            if (nxt[1] > j+1 and u == a0+x.end and v > c0+y.words[last_c][1] and v < c0+y.end
                    or nxt[0] > i+1 and v == c0+y.end and u > a0+x.words[last_a][1] and u < a0+x.end):
                finish = (u, v)
            else:
                finish = (a0+x.end, c0+y.end)
        else:
            finish = (u, v)
        cuts.add(finish)
        captured = sum(
                swallowed(a0+x.words[s][0], a0+x.words[s][1], 0) or
                swallowed(c0+y.words[t][0], c0+y.words[t][1], 2) for s, t in words)
        swallowed_end = begins and ends_here and (swallowed(a0+x.end, a0+x.end+1, 0)
                                                   or swallowed(c0+y.end, c0+y.end+1, 2))
        if (x.kind or y.kind) and (captured >= 2 or swallowed_end or captured and len(words) == 1 and begins and ends_here):
            hot.append((*start, *finish))

    if not hot:
        return raw, roles
    # Explicit speaker decisions survive when they refer to the same paired
    # prefixes. A name on an unrelated inserted turn must not force an anchor.
    for a, b, c, d in speakers:
        if (left.rfind('\n', 0, a)+1, right.rfind('\n', 0, c)+1) in paired_names:
            cuts.update(((a, c), (b, d)))
    points = sorted(cuts)
    seams = [(i, n) for i, (a, c) in enumerate(points) if (n := seam(a, c)) is not None]
    result = []
    for (i, n), (j, m) in zip(seams, seams[1:]):
        a, c = points[i]
        b, d = points[j]
        if not any((x < b or z < d) and (y > a or w > c) for x, z, y, w in hot):
            result.extend(raw[n:m])
            continue
        for (x, z), (y, w) in zip(points[i:j], points[i+1:j+1]):
            if (x, y, z, w) in roles:
                result.append((x, y, z, w))
            else:
                result.extend(_local_edits(left, right, x, y, z, w, inner))
    return result, roles


def isolate_bylines(left, right, raw):
    """Expose complete headings embedded in an added/deleted run with a counterpart."""
    candidates = defaultdict(list)
    for side, text in enumerate((left, right)):
        offset = 2*side
        ends = [s[offset+1] for s in raw]
        for match in BYLINE.finditer(text):
            start, end = match.span()
            i = bisect_right(ends, start)
            if i >= len(raw):
                break
            span = raw[i]
            a, b = span[offset:offset+2]
            c, d = span[2-offset:4-offset]
            if not a <= start < end <= b:
                continue
            if end < b and text[end] == '\n':
                end += 1
            elif start > a and text[start-1] == '\n':
                start -= 1
            # With wording on both sides, cut only at a known edge of that
            # wording. An interior ambiguous heading remains part of its edit.
            if c == d or not text[a:start].strip():
                caret = c
            elif not text[end:b].strip():
                caret = d
            else:
                continue
            cut = (start, end, caret, caret) if not side else (caret, caret, start, end)
            candidates[' '.join(match[0].split()).casefold()].append((side, i, cut))
    cuts = defaultdict(list)
    for group in candidates.values():
        if len({side for side, _, _ in group}) == 2:
            for side, i, span in group:
                if not any(other != side and n == i for other, n, _ in group):
                    cuts[i].append(span)
    result = []
    for i, span in enumerate(raw):
        a, b, c, d = span
        for x, y, z, w in sorted(cuts[i]):
            if x < a or z < c:
                continue
            if left[a:x] != right[c:z]:
                result.append((a, x, c, z))
            result.append((x, y, z, w))
            a, c = y, w
        if not cuts[i] or left[a:b] != right[c:d]:
            result.append((a, b, c, d))
    return result


def byline_moves(original, incoming, raw):
    """Pair an isolated deletion and insertion between the same intact bylines."""
    sides = (original, incoming)
    candidates = defaultdict(lambda: [[], []])
    fences = [[], []]
    for side, revision in enumerate(sides):
        offset = side * 2
        changed = {}
        for span in raw:
            a, b = span[offset:offset+2]
            c, d = span[2-offset:4-offset]
            if c == d and a < b:
                content = revision.text[a:b]
                line = content.strip('\n')
                if BYLINE.fullmatch(line) and content.count('\n') <= 1:
                    changed[a + int(content.startswith('\n'))] = span
        for match in BYLINE.finditer(revision.text):
            key = ' '.join(match[0].split()).casefold()
            if (span := changed.get(match.start())) is not None:
                candidates[key][side].append((span, match))
            else:
                fences[side].append((match.start(), key))
        fences[side].extend((m.start(), None) for m in re.finditer(r'[^\n]+', revision.text)
                            if is_off_record_note(m[0]))
        fences[side].sort()
    moves = []
    for key, groups in candidates.items():
        slots = defaultdict(lambda: [[], []])
        for side, group in enumerate(groups):
            for span, match in group:
                # Corresponding stationary headings and off-record boundaries
                # distinguish repeated examiner names at different examinations.
                fence = tuple(k for pos, k in fences[side] if pos < match.start())
                slots[fence][side].append((span, match))
        for old, new in slots.values():
            if len(old) != 1 or len(new) != 1:
                continue
            if old[0][1][0].rstrip() != new[0][1][0].rstrip():
                continue
            fields = [tuple(e.name for e in rev.elements if e.kind == 'field'
                            and match.start() <= e.start and e.end <= match.end())
                      for rev, (_, match) in zip(sides, (old[0], new[0]))]
            if all(fields) and fields[0] != fields[1]:
                continue
            move = tuple(sorted((old[0][0], new[0][0])))
            if all(atomic_boundaries(original, incoming, s) for s in move):
                moves.append(move)
    return moves


def atomic_boundaries(original, incoming, span):
    return all(not any(e.start < cut < e.end for e in rev.elements)
               for rev, positions in ((original, span[:2]), (incoming, span[2:])) for cut in positions)


def restore_bylines(original, incoming, moves):
    elements = list(incoming.elements)
    for move in moves:
        deleted = next(s for s in move if s[0] < s[1])
        added = next(s for s in move if s[2] < s[3])
        a, b = deleted[:2]
        c, d = added[2:]
        a += int(original.text[a:b].startswith('\n'))
        c += int(incoming.text[c:d].startswith('\n'))
        line = original.text[a:b].rstrip()
        if incoming.text[c:d].rstrip() != line:
            continue
        for e in original.elements:
            if a <= e.start < e.end <= a + len(line):
                moved = replace(e, start=c+e.start-a, end=c+e.end-a)
                if not any(x.start < moved.end and x.end > moved.start for x in elements):
                    elements.append(moved)
    return replace(incoming, elements=tuple(sorted(elements, key=lambda e: (e.start, e.end))))
