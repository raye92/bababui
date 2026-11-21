"""Grade the ASR-to-AI-draft stage against Gemini's transcript.

This stage receives Gemini's speaker-labeled transcript and any supplied case
context. It never receives the reporter's steno rough, so there is no voting
between steno, ASR and AI here. Every edit is tracked against Gemini's original
transcript, and a hand-graded expected draft records the decision the context
supports for every speaker turn, paragraph boundary and term, including the
decision to leave it unchanged.

Four areas are graded separately: wording, speakers, paragraphs, and names,
organizations and special terminology. Each failure is one of:

- missed correction: the expected draft changes Gemini's text, label or
  boundary, and the AI kept Gemini's version (or did not flag a turn that
  needs review);
- incorrect edit: the AI changed something that should stay, or changed it to
  the wrong result;
- unnecessary review flag: the AI flagged a turn the context resolves;
- highlight error: the highlights shown for the AI draft differ from the
  highlights the expected draft produces at that place.

Highlights: restored words and corrected mistranslations get a green
background; changed speaker labels get a yellow background; restored or
corrected names, organizations and special terms also get an orange
underline. Unchanged text, punctuation-only, style-only and paragraph-only
edits get no change highlight. Words removed from Gemini's text are shown
struck through so the deletion stays visible.
"""
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from html import escape
import json
from pathlib import Path
import re
import sys

AREAS = ('wording', 'speakers', 'paragraphs', 'names')
AREA_TITLES = {'wording': 'Wording', 'speakers': 'Speakers', 'paragraphs': 'Paragraphs',
               'names': 'Names, organizations and terms'}
CATEGORIES = ('missed', 'incorrect', 'unnecessary_flag', 'highlight')
CATEGORY_TITLES = {'missed': 'Missed corrections', 'incorrect': 'Incorrect edits',
                   'unnecessary_flag': 'Unnecessary review flags', 'highlight': 'Highlight errors'}

TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*|%|&")
NUMBERS = {w: str(i) for i, w in enumerate(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen '
    'sixteen seventeen eighteen nineteen twenty'.split())}
NUMBERS.update({'thirty': '30', 'forty': '40', 'fifty': '50', 'sixty': '60', 'seventy': '70',
                'eighty': '80', 'ninety': '90', 'hundred': '100'})
STYLE = {'%': 'percent', '&': 'and', 'ok': 'okay'}
# Verbatim cleanup that the drafting prompt allows either way: hesitation fillers,
# immediate repeats (stutters) and an empty lead-in that opens a sentence.
FILLERS = frozenset({'uh', 'um', 'er', 'ah', 'hmm', 'mm'})
LEAD_INS = frozenset({'and', 'so', 'oh', 'well'})
ASR_TURN = re.compile(r'^\s*speaker\s*(\d+)\s*:\s?(.*)$', re.I)
REVIEW_TAG = re.compile(r'\s*\[REVIEW\s+(\d+)\]')
NOTE = re.compile(r'^\s*\[REVIEW\s+(\d+)\]\s*(.*)$')
HEADING = re.compile(r'^\s*(?:FURTHER\s+|CROSS-|REDIRECT\s+|RECROSS-)?EXAMINATION\s*$')
BYLINE = re.compile(r'^\s*BY\s+(?P<name>[^:]+?)\s*:\s*$')
QA = re.compile(r'^\s*(?P<kind>[QA])(?:\s+|$)')
LABEL = re.compile(r'^\s*(?P<name>SPEAKER\s+\d+|THE [A-Z][A-Z .]*|(?:MR|MS|MRS|DR)\. [^:\n]+):\s*')
PARENTHETICAL = re.compile(r'^\s*\(.*\)\s*$')
SPEECH = ('q', 'a', 'colloquy')

KEYWORDS = (('speakers', r'speaker|label|witness|attorney|counsel|who (?:said|is speaking)|voice'),
            ('paragraphs', r'paragraph|boundary|split|join|break|continu'),
            ('names', r'\bname|spell|term|organi[sz]ation|medication|diagnos|company|doctor\'s name'))


def norm(token):
    """Comparison form: case, apostrophes and number style do not count as edits."""
    value = token.casefold().replace("'", '').replace('’', '')
    value = STYLE.get(value, value)
    value = NUMBERS.get(value, value)
    return re.sub(r'^(\d+)(?:st|nd|rd|th)$', r'\1', value)


def speaker_key(name):
    match = re.fullmatch(r'\s*speaker\s*0*(\d+)\s*', name or '', re.I)
    return f'SPEAKER {int(match[1])}' if match else ' '.join((name or '').split()).upper()


LABELED = re.compile(r'^\s*([^:.]{1,30}):')


def note_area(text, default='wording'):
    """A note's area: its leading label if it has one ("Name spelling: ..."), else keywords."""
    text = text or ''
    label = LABELED.match(text)
    if label:
        for area, pattern in KEYWORDS:
            if re.search(pattern, label[1], re.I):
                return area
        if re.search(r'word|gap|audio|inaudible|missing|unclear', label[1], re.I):
            return 'wording'
    for area, pattern in KEYWORDS:
        if re.search(pattern, text, re.I):
            return area
    return default


@dataclass
class Token:
    raw: str
    norm: str
    para: int
    start: int  # character offset inside the paragraph's display line
    end: int
    optional: bool = False  # Gemini words whose removal is verbatim cleanup either way


@dataclass
class Paragraph:
    kind: str           # q, a, colloquy, byline, heading, parenthetical, other
    speaker: str | None
    line: str           # display text without review tags
    label_span: tuple   # character span of the Q/A letter or SPEAKER label
    flags: list = field(default_factory=list)


@dataclass
class Draft:
    paragraphs: list
    tokens: list
    notes: dict

    def flag_area(self, number):
        return note_area(self.notes.get(number, ''))


def parse_asr(text):
    """Return Gemini's turns as (speaker, body) and its tokens with turn indexes."""
    turns, tokens = [], []
    for line in text.replace('\r\n', '\n').split('\n'):
        if not line.strip():
            continue
        match = ASR_TURN.match(line)
        if match:
            turns.append((f'SPEAKER {int(match[1])}', match[2]))
        elif turns:
            turns[-1] = (turns[-1][0], turns[-1][1] + ' ' + line.strip())
        else:
            turns.append((None, line.strip()))
    for index, (speaker, body) in enumerate(turns):
        for match in TOKEN.finditer(body):
            tokens.append(Token(match[0], norm(match[0]), index, match.start(), match.end()))
    for k, token in enumerate(tokens):
        before = turns[token.para][1][:token.start].rstrip()
        opens = not before or before[-1] in '.?!'
        token.optional = token.norm in FILLERS or (opens and token.norm in LEAD_INS)
    return turns, tokens


def parse_draft(text, witness):
    """Split a deposition-format draft into paragraphs, tokens and review notes."""
    paragraphs, tokens, notes = [], [], {}
    examiner, in_notes = None, False
    for raw in text.replace('\r\n', '\n').split('\n'):
        if re.match(r'^\s*REVIEW NOTES\s*:?\s*$', raw):
            in_notes = True
            continue
        if in_notes:
            if match := NOTE.match(raw):
                notes[int(match[1])] = match[2].strip()
            continue
        if not raw.strip():
            continue
        flags = [int(n) for n in REVIEW_TAG.findall(raw)]
        line = REVIEW_TAG.sub('', raw).rstrip()
        body_start, label_span, speaker = 0, (0, 0), None
        if HEADING.match(line):
            kind = 'heading'
        elif match := BYLINE.match(line):
            kind, examiner = 'byline', speaker_key(match['name'])
            speaker, label_span = examiner, match.span('name')
        elif PARENTHETICAL.match(line):
            kind = 'parenthetical'
        elif match := QA.match(line):
            kind = 'q' if match['kind'] == 'Q' else 'a'
            speaker = examiner if kind == 'q' else witness
            label_span, body_start = match.span('kind'), match.end()
        elif match := LABEL.match(line):
            kind, speaker = 'colloquy', speaker_key(match['name'])
            label_span, body_start = match.span('name'), match.end()
        elif paragraphs and paragraphs[-1].kind in SPEECH and line[:1] in ' \t':
            # An indented line without a label starts a new paragraph by the same speaker.
            previous = paragraphs[-1]
            kind, speaker = previous.kind, previous.speaker
            body_start = len(line) - len(line.lstrip())
        elif paragraphs and paragraphs[-1].kind in SPEECH + ('other',):
            # A flush-left line is a wrapped continuation of the paragraph above it.
            previous = paragraphs[-1]
            offset = len(previous.line) + 1
            previous.line += ' ' + line.strip()
            previous.flags += flags
            stripped = line.strip()
            for match in TOKEN.finditer(stripped):
                tokens.append(Token(match[0], norm(match[0]), len(paragraphs) - 1,
                                    offset + match.start(), offset + match.end()))
            continue
        else:
            kind = 'other'
        paragraphs.append(Paragraph(kind, speaker, line, label_span, flags))
        if kind in SPEECH + ('other',):
            for match in TOKEN.finditer(line, body_start):
                tokens.append(Token(match[0], norm(match[0]), len(paragraphs) - 1, match.start(), match.end()))
    return Draft(paragraphs, tokens, notes)


@dataclass(frozen=True)
class Edit:
    a: int  # Gemini token span [a, b)
    b: int
    c: int  # draft token span [c, d)
    d: int


def track_edits(asr_tokens, tokens):
    """Word edits against Gemini's text. Punctuation, case and style changes are not edits."""
    left, right = [t.norm for t in asr_tokens], [t.norm for t in tokens]
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    edits, mapping = [], [None] * len(left)
    for op, a, b, c, d in matcher.get_opcodes():
        if op == 'equal':
            for i, j in zip(range(a, b), range(c, d)):
                mapping[i] = j
            continue
        if op == 'replace':
            for i in range(a, b):
                mapping[i] = c + (i - a) * (d - c) // (b - a)
        if ''.join(left[a:b]) != ''.join(right[c:d]):
            edits.append(Edit(a, b, c, d))
    return edits, mapping


@dataclass
class Version:
    """One draft (expected or actual) tracked against Gemini's text."""
    draft: Draft
    edits: list
    mapping: list  # Gemini token index -> draft token index or None

    def paragraph_of(self, i):
        j = self.mapping[i]
        return None if j is None else self.draft.tokens[j].para

    def speaker_of(self, i):
        p = self.paragraph_of(i)
        return None if p is None else self.draft.paragraphs[p].speaker

    def tokens_between(self, a, b):
        """Positions covering Gemini's tokens [a, b): draft token indexes for this version's
        edits inside the region, and ('asr', i) for Gemini words it kept."""
        out, pos = [], a
        for edit in sorted((e for e in self.edits if a <= e.a and e.b <= b), key=lambda e: (e.a, e.b)):
            out.extend(('asr', k) for k in range(pos, edit.a))
            out.extend(range(edit.c, edit.d))
            pos = max(pos, edit.b)
        out.extend(('asr', k) for k in range(pos, b))
        return out

    def starts(self, speech_only=True):
        """Gemini token positions where this version starts a speech paragraph."""
        first = {}
        for i in range(len(self.mapping)):
            p = self.paragraph_of(i)
            if p is not None and p not in first:
                first[p] = i
        return {i for p, i in first.items()
                if not speech_only or self.draft.paragraphs[p].kind in SPEECH}


def overlaps(a, b, c, d):
    return a < d and c < b or a == b and c <= a <= d or c == d and a <= c <= b


@dataclass
class Failure:
    area: str
    category: str
    span: tuple          # Gemini token span
    expected: str
    actual: str
    detail: str = ''
    clue: str = ''
    excerpt: str = ''


DEFAULT_CLUES = {
    ('wording', 'missed'): 'The surrounding question and answer establish the intended words.',
    ('wording', 'incorrect'): "Gemini's words fit the complete thought; nothing in context supports a change.",
    ('names', 'missed'): 'An introduction, spelling, repeated reference or supplied document fixes this name or term.',
    ('names', 'incorrect'): "Gemini's form is supported; the change is not established by the dialogue or a document.",
    ('speakers', 'missed'): 'Who is addressed, who has firsthand knowledge, or how the next person responds identifies this speaker.',
    ('speakers', 'incorrect'): "Gemini's label fits who is addressed and who answers.",
    ('paragraphs', 'missed'): 'The speaker and the progression of the thought set this boundary.',
    ('paragraphs', 'incorrect'): "Gemini's boundary follows a real change of speaker or subject.",
}


class Case:
    """A hand-graded case: Gemini's text, the expected draft, terms and clues."""

    def __init__(self, record):
        self.id = record['id']
        self.title = record.get('title', self.id)
        self.witness = speaker_key(record['witness'])
        self.context = record.get('context', '')
        self.turns, self.asr = parse_asr(record['asr'])
        # Gemini words the draft may keep or remove, such as an abandoned start or a
        # redundant restart that the reporter's rules allow either way.
        # In "asr", brackets mark the optional words inside a longer phrase that
        # locates them: "had not [had] developed".
        self.optional = []
        for x in record.get('optional', []):
            if 'span' in x:
                spans = [tuple(x['span'])]
            else:
                phrase = x['asr']
                start, _ = self.locate(phrase.replace('[', ' ').replace(']', ' '), x.get('nth', 1))
                spans, k = [], start
                for part in re.split(r'(\[[^\]]*\])', phrase if '[' in phrase else f'[{phrase}]'):
                    n = len(TOKEN.findall(part))
                    if part.startswith('['):
                        spans.append((k, k + n))
                    k += n
            for span in spans:
                for i in range(*span):
                    self.asr[i].optional = True
                self.optional.append((span, x.get('reason', '')))
        self.expected = self.version(record['expected'])
        self.terms = [self._term(t) for t in record.get('terms', [])]
        self.checkpoints = [self._checkpoint(c) for c in record.get('checkpoints', [])]
        # Spans not graded, such as saved-draft words that review may have restored.
        # Restorations change words, so by default they affect wording and names only.
        self.excluded = [(tuple(x['span']) if 'span' in x else self.locate(x['asr'], x.get('nth', 1)), x.get('reason', ''),
                          tuple(x.get('areas', ('wording', 'names'))))
                         for x in record.get('exclude', [])]
        self.drafts = record.get('drafts', {})
        self.draft_excluded = {}  # extra spans for one saved draft, keyed by draft name
        self.flags_hidden = set()  # saved drafts that cannot show review flags

    def version(self, text):
        draft = parse_draft(text, self.witness)
        edits, mapping = track_edits(self.asr, draft.tokens)
        return Version(draft, edits, mapping)

    def locate(self, phrase, nth=1):
        """Gemini token span of the nth occurrence of a phrase in Gemini's text."""
        wanted = [norm(m[0]) for m in TOKEN.finditer(phrase)]
        found = 0
        for i in range(len(self.asr) - len(wanted) + 1):
            if [t.norm for t in self.asr[i:i + len(wanted)]] == wanted:
                found += 1
                if found == nth:
                    return (i, i + len(wanted))
        raise ValueError(f'{self.id}: "{phrase}" (occurrence {nth}) is not in the Gemini transcript.')

    def _term(self, record):
        record = {'term': record} if isinstance(record, str) else record
        return {'term': record['term'], 'tokens': [norm(m[0]) for m in TOKEN.finditer(record['term'])],
                'heard': [[norm(m[0]) for m in TOKEN.finditer(h)] for h in record.get('heard', [])]}

    def _checkpoint(self, record):
        span = self.locate(record['asr'], record.get('nth', 1))
        return {**record, 'span': span}

    def term_units(self):
        """Distinct names and terms to evaluate: expected term occurrences, plus names
        checkpoints (such as left versus right) that no term covers."""
        units = []
        for span, _, term in self.term_spans(self.expected):
            if span not in [u[0] for u in units]:
                units.append((span, term))
        for checkpoint in self.checkpoints:
            if checkpoint['area'] == 'names' and not any(overlaps(*u[0], *checkpoint['span']) for u in units):
                units.append((checkpoint['span'], checkpoint['asr']))
        return units

    def term_spans(self, version):
        """Gemini spans of each term occurrence in a version, with that version's token span."""
        tokens = [t.norm for t in version.draft.tokens]
        spans = []
        for term in self.terms:
            n = len(term['tokens'])
            for j in range(len(tokens) - n + 1):
                if tokens[j:j + n] == term['tokens']:
                    hits = [i for i, m in enumerate(version.mapping) if m is not None and j <= m < j + n]
                    if hits:
                        spans.append(((min(hits), max(hits) + 1), (j, j + n), term['term']))
                    else:
                        # The whole term was inserted; anchor it where its tokens were inserted.
                        edit = next((e for e in version.edits if e.c <= j < e.d), None)
                        if edit:
                            spans.append(((edit.a, edit.b), (j, j + n), term['term']))
            for heard in term['heard']:
                n = len(heard)
                for i in range(len(self.asr) - n + 1):
                    if [t.norm for t in self.asr[i:i + n]] == heard:
                        spans.append(((i, i + n), None, term['term']))
        return spans

    def clue(self, area, category, span):
        for checkpoint in self.checkpoints:
            a, b = checkpoint['span']
            if checkpoint['area'] == area and overlaps(a, b, *span):
                return checkpoint['clue']
        for checkpoint in self.checkpoints:
            a, b = checkpoint['span']
            if overlaps(a, b, *span):
                return checkpoint['clue']
        return DEFAULT_CLUES.get((area, 'missed' if category == 'missed' else 'incorrect'), '')

    def excerpt(self, span):
        """Gemini's turns around a span, with the span marked."""
        a, b = span
        if not self.asr:
            return ''
        first = self.asr[min(a, len(self.asr) - 1)].para
        last = self.asr[max(min(b, len(self.asr)) - 1, min(a, len(self.asr) - 1))].para
        lines = []
        for t in range(max(0, first - 1), min(len(self.turns), last + 2)):
            speaker, body = self.turns[t]
            marks = [(k, tok) for k, tok in enumerate(self.asr) if tok.para == t and a <= k < max(b, a + 1)]
            if marks and a < b:
                s, e = marks[0][1].start, marks[-1][1].end
                body = body[:s] + '«' + body[s:e] + '»' + body[e:]
            elif a == b and t == first:
                pos = next((tok.start for k, tok in enumerate(self.asr) if k == a and tok.para == t), None)
                if pos is not None:
                    body = body[:pos] + '«»' + body[pos:]
            lines.append(f'{(speaker or "").title()}: {_shorten(body, t - first)}')
        return '\n'.join(lines)

    def is_excluded(self, span, area='wording'):
        return any(area in areas and overlaps(*x, *span) for x, _, areas in self.excluded)


def _shorten(body, where, room=260):
    """Keep a long turn readable: the text around the mark, the end of the turn
    before it, or the start of the turn after it."""
    if len(body) <= 2 * room:
        return body
    if '«' in body:
        start, end = body.index('«'), body.index('»') + 1
        lo, hi = max(0, start - room), min(len(body), end + room)
        return ('…' if lo else '') + body[lo:hi] + ('…' if hi < len(body) else '')
    return '…' + body[-room:] if where < 0 else body[:room] + '…'


def _region_ok(version, a, b):
    """True when no edit of this version crosses the span's edges."""
    return all(e.b <= a or e.a >= b or (a <= e.a and e.b <= b) for e in version.edits if not (e.a == e.b and e.a in (a, b)))


def _text(version, positions, asr):
    out = []
    for item in positions:
        out.append(asr[item[1]].raw if isinstance(item, tuple) else version.draft.tokens[item].raw)
    return ' '.join(out) or '(nothing)'


def _norms(version, positions, asr, *, cleanup=False):
    """Comparison text for a region. With cleanup, optional verbatim cleanup does not count
    either way: Gemini's fillers and empty lead-ins are ignored, and an immediate repeat
    (a stutter) counts once."""
    words = [asr[p[1]].norm if isinstance(p, tuple) else version.draft.tokens[p].norm for p in positions
             if not (cleanup and isinstance(p, tuple) and asr[p[1]].optional)]
    if cleanup:
        words = [w for k, w in enumerate(words) if not k or words[k - 1] != w]
    return ''.join(words)


def cleanup_deletion(asr, a, b):
    """True when removing Gemini's words [a, b) is optional cleanup: fillers, empty
    lead-ins, repeats, or words equal to an optional span next to them (removing
    either copy of "I have I have" gives the same text)."""
    def repeat(i):
        return asr[i].norm in (asr[i - 1].norm if i else None, asr[i + 1].norm if i + 1 < len(asr) else None)
    if all(asr[i].optional or repeat(i) for i in range(a, b)):
        return True
    n = b - a
    for x in range(max(0, a - n - 2), min(len(asr) - n, a + n + 2) + 1):
        if x != a and all(asr[i].optional for i in range(x, x + n)):
            lo, hi = min(a, x), max(b, x + n)
            left = [asr[i].norm for i in range(lo, hi) if not a <= i < b]
            right = [asr[i].norm for i in range(lo, hi) if not x <= i < x + n]
            if left == right:
                return True
    return False


def _lattice(version, a, b, asr):
    """The region's words in this version, each marked optional or not, plus the
    optional Gemini words this version removed, as (norm, optional) in order."""
    items, pos = [], a
    for edit in sorted((e for e in version.edits if a <= e.a and e.b <= b), key=lambda e: (e.a, e.b)):
        items.extend((asr[k].norm, asr[k].optional) for k in range(pos, edit.a))
        items.extend((asr[k].norm, True) for k in range(edit.a, edit.b) if asr[k].optional)
        items.extend((version.draft.tokens[j].norm, False) for j in range(edit.c, edit.d))
        pos = max(pos, edit.b)
    items.extend((asr[k].norm, asr[k].optional) for k in range(pos, b))
    return items


def _cleanup_match(actual, expected, a, b, asr):
    """True when the actual region is the expected region with optional words kept or
    dropped in any combination. An immediate repeat counts once in both."""
    words = [w for w in (asr[p[1]].norm if isinstance(p, tuple) else actual.draft.tokens[p].norm
                         for p in actual.tokens_between(a, b))]
    words = [w for k, w in enumerate(words) if not k or words[k - 1] != w]
    items = []
    for norm_, optional in _lattice(expected, a, b, asr):
        if items and items[-1][0] == norm_:
            items[-1] = (norm_, items[-1][1] and optional)
        else:
            items.append((norm_, optional))
    n, m = len(words), len(items)
    can = [[False] * (m + 1) for _ in range(n + 1)]
    for j in range(m, -1, -1):
        can[n][j] = all(o for _, o in items[j:])
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            can[i][j] = (words[i] == items[j][0] and can[i + 1][j + 1]) or (items[j][1] and can[i][j + 1])
    return can[0][0]


def _majority(values):
    values = [v for v in values if v is not None]
    return max(set(values), key=values.count) if values else None


def _describe(paragraph):
    if paragraph is None:
        return '(no paragraph)'
    form = {'q': 'Q', 'a': 'A', 'colloquy': 'colloquy', 'byline': 'BY line'}.get(paragraph.kind, paragraph.kind)
    return f'{paragraph.speaker or "unlabeled"} ({form})'


def grade(case, text, excluded=(), flags_visible=True):
    """Grade one AI draft for a case. Returns counts, failures and both tracked versions.

    `excluded` adds spans that are not graded for this draft only, in the same
    (span, reason, areas) form as Case.excluded. With `flags_visible` false, the
    draft cannot show review flags, so flags are counted as not graded.
    """
    saved = case.excluded
    case.excluded = saved + list(excluded)
    try:
        result = _grade(case, text, flags_visible)
        result['excluded'] = list(case.excluded)
        result['flags_visible'] = flags_visible
        return result
    finally:
        case.excluded = saved


def _grade(case, text, flags_visible=True):
    actual = case.version(text)
    expected = case.expected
    asr = case.asr
    failures, evaluated, skipped = [], {a: 0 for a in AREAS}, {a: 0 for a in AREAS}

    def add(area, category, span, expected_text, actual_text, detail=''):
        failures.append(Failure(area, category, span, expected_text, actual_text, detail,
                                case.clue(area, category, span), case.excerpt(span)))

    expected_terms = case.term_spans(expected)
    actual_terms = case.term_spans(actual)
    units = case.term_units()
    review_spans = _flag_spans(case, expected)
    actual_flags = _flag_spans(case, actual)

    # Wording and names: every Gemini word is either kept or edited in each version.
    regions = sorted([(e.a, e.b) for e in expected.edits] + [(e.a, e.b) for e in actual.edits])
    merged = []
    for a, b in regions:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    for a, b in merged:
        span = (a, b)
        area = 'names' if any(overlaps(*s, a, b) for s, _, _ in expected_terms + actual_terms) or any(
            c['area'] == 'names' and overlaps(*c['span'], a, b) for c in case.checkpoints) else 'wording'
        if case.is_excluded(span, area):
            continue  # counted below, with the names and paragraphs it falls in
        e_pos, x_pos = expected.tokens_between(a, b), actual.tokens_between(a, b)
        g, x = _norms(expected, e_pos, asr), _norms(actual, x_pos, asr)
        s = ''.join(t.norm for t in asr[a:b])
        lo, hi = max(0, a - 1), min(len(asr), b + 1)
        if (_norms(expected, expected.tokens_between(lo, hi), asr, cleanup=True)
                == _norms(actual, actual.tokens_between(lo, hi), asr, cleanup=True)
                or _cleanup_match(actual, expected, lo, hi, asr)):
            # The versions differ only in optional cleanup, judged with one neighboring
            # word on each side so a stutter is seen whole. Neither is a failure.
            continue
        # Show a whole name or term when the edit touches only part of it.
        shown = [s_ for s_, _ in units if overlaps(*s_, a, b)]
        lo, hi = min([a] + [s_[0] for s_ in shown]), max([b] + [s_[1] for s_ in shown])
        e_text = _text(expected, expected.tokens_between(lo, hi) if _region_ok(expected, lo, hi) else e_pos, asr)
        x_text = _text(actual, actual.tokens_between(lo, hi) if _region_ok(actual, lo, hi) else x_pos, asr)
        if g == x:
            pass
        elif g != s and x == s:
            add(area, 'missed', span, e_text, x_text)
        else:
            wrote = any(not isinstance(item, tuple) for item in x_pos)
            if not wrote:
                detail = 'removed words that should stay'
            elif g == s and any(overlaps(*r, a, b) and ar in ('wording', 'names') for r, ar in review_spans):
                detail = 'guessed at words that need audio review instead of flagging them'
            else:
                detail = 'changed text that should stay as Gemini heard it' if g == s else 'changed to the wrong words'
            add(area, 'incorrect', span, e_text, x_text, detail)
        expected_marks = _marks(e_pos, g != s, area == 'names')
        actual_marks = _marks(x_pos, x != s, area == 'names')
        if expected_marks != actual_marks:
            add('names' if 'orange' in expected_marks | actual_marks else area, 'highlight', span,
                _mark_text(expected_marks), _mark_text(actual_marks))

    # Every name and term is evaluated, including those correctly left unchanged, and
    # every speech paragraph's wording is checked in full.
    for s, _ in units:
        if case.is_excluded(s, 'names'):
            skipped['names'] += 1
        else:
            evaluated['names'] += 1
    wording_units = {}
    for i in range(len(asr)):
        p = expected.paragraph_of(i)
        if p is not None and expected.draft.paragraphs[p].kind in SPEECH:
            wording_units.setdefault(p, []).append(i)
    for words in wording_units.values():
        if all(case.is_excluded((i, i + 1)) for i in words):
            skipped['wording'] += 1
        else:
            evaluated['wording'] += 1

    # Speakers: identity of every expected speech paragraph, then its Q/A or colloquy form.
    expected_units = {}
    for i in range(len(asr)):
        p = expected.paragraph_of(i)
        if p is not None and expected.draft.paragraphs[p].kind in SPEECH:
            expected_units.setdefault(p, []).append(i)
    for p, words in expected_units.items():
        span = (min(words), max(words) + 1)
        paragraph = expected.draft.paragraphs[p]
        if case.is_excluded(span, 'speakers'):
            skipped['speakers'] += 1
            continue
        evaluated['speakers'] += 1
        gemini = _majority([asr_speaker(case, i) for i in words])
        if any(overlaps(*r, *span) and area == 'speakers' for r, area in review_spans):
            continue  # Either label is acceptable; the review flag is graded below.
        # Words the AI dropped are wording failures, not speaker failures.
        wrong = [i for i in words if actual.mapping[i] is not None and actual.speaker_of(i) != paragraph.speaker]
        actual_p = _majority([actual.paragraph_of(i) for i in words])
        actual_paragraph = actual.draft.paragraphs[actual_p] if actual_p is not None else None
        if wrong:
            kept_gemini = all(actual.speaker_of(i) == asr_speaker(case, i) for i in wrong)
            changed = any(asr_speaker(case, i) != paragraph.speaker for i in words)
            category = 'missed' if kept_gemini and changed else 'incorrect'
            detail = ('kept Gemini\'s label' if category == 'missed'
                      else 'relabeled a speaker that Gemini had right' if not changed else 'relabeled to the wrong speaker')
            labels = sorted({actual.speaker_of(i) or 'none' for i in wrong})
            add('speakers', category, span, _describe(paragraph),
                f'{", ".join(labels)} for {len(wrong)} of {len(words)} words; {_describe(actual_paragraph)}', detail)
        elif actual_paragraph and actual_paragraph.kind != paragraph.kind:
            add('speakers', 'incorrect', span, _describe(paragraph), _describe(actual_paragraph),
                'right speaker, wrong Q/A or colloquy form')
        expected_yellow = paragraph.speaker != gemini
        actual_yellow = bool(actual_paragraph) and actual_paragraph.speaker != gemini
        if expected_yellow != actual_yellow:
            add('speakers', 'highlight', span, 'yellow label' if expected_yellow else 'no label highlight',
                'yellow label' if actual_yellow else 'no label highlight')

    # Paragraphs: every boundary Gemini, the expected draft or the AI draft has.
    # A boundary at a word one version removed moves to the next word both versions keep.
    shared = [i for i in range(len(asr)) if expected.mapping[i] is not None and actual.mapping[i] is not None]

    def canonical(positions):
        out = set()
        for i in positions:
            k = next((s for s in shared if s >= i), None)
            if k is not None:
                out.add(k)
        return out

    gemini_starts = canonical(i for i in range(1, len(asr)) if asr[i].para != asr[i - 1].para)
    expected_starts, actual_starts = canonical(expected.starts()), canonical(actual.starts())
    first = shared[0] if shared else 0
    for i in sorted((gemini_starts | expected_starts | actual_starts) - {first}):
        span = (max(0, i - 1), i + 1)
        if case.is_excluded(span, 'paragraphs'):
            skipped['paragraphs'] += 1
            continue
        evaluated['paragraphs'] += 1
        want, got, had = i in expected_starts, i in actual_starts, i in gemini_starts
        if want == got:
            continue
        where = f'before “{asr[i].raw}”'
        e_text = f'paragraph break {where}' if want else f'no break {where}'
        x_text = f'paragraph break {where}' if got else f'no break {where}'
        if got == had:
            add('paragraphs', 'missed', span, e_text, x_text,
                'kept an artificial Gemini break' if had else 'kept two turns in one paragraph')
        else:
            add('paragraphs', 'incorrect', span, e_text, x_text,
                'joined across a real boundary' if had else 'split a continuous paragraph')

    # Review flags. A saved draft that went through review may have lost its flags,
    # because review can drop inserted text; then flags are not graded.
    for span, area in review_spans:
        if case.is_excluded(span, area):
            continue
        if not flags_visible:
            skipped[area] += 1
            continue
        if not any(overlaps(*span, *other) for other, _ in actual_flags):
            add(area, 'missed', span, 'flagged for review', 'not flagged', 'missed a needed review flag')
    for span, area in actual_flags:
        if case.is_excluded(span, area) or not flags_visible:
            continue
        if not any(overlaps(*span, *other) for other, _ in review_spans):
            add(area, 'unnecessary_flag', span, 'no review flag', 'flagged for review')

    _moved_text(failures)
    worded = {(f.area, tuple(f.span)) for f in failures if f.category in ('missed', 'incorrect')}
    for f in failures:
        if f.category == 'highlight' and not f.detail and any(tuple(f.span) == span for _, span in worded):
            f.detail = 'follows from the word error above'
    counts = {area: {c: sum(f.area == area and f.category == c for f in failures) for c in CATEGORIES}
              for area in AREAS}
    for area in AREAS:
        counts[area].update(evaluated=evaluated[area], not_graded=skipped[area])
    return {'case': case.id, 'counts': counts, 'failures': failures, 'actual': actual, 'expected': expected}


def _moved_text(failures):
    """Text removed in one place and inserted unchanged in another changes the order of
    testimony. Report both places under paragraphs."""
    key = lambda text: re.sub(r'[\W_]+', '', text.casefold())
    removed = [f for f in failures if f.category == 'incorrect' and f.actual == '(nothing)']
    inserted = [f for f in failures if f.category == 'incorrect' and f.expected == '(nothing)']
    for gone in removed:
        twin = next((f for f in inserted if key(f.actual) == key(gone.expected) and key(f.actual)), None)
        if twin is None:
            continue
        inserted.remove(twin)
        for f in failures:
            if f is gone or f is twin or (f.category == 'highlight' and f.span in (gone.span, twin.span)):
                f.area = 'paragraphs'
                if f.category == 'incorrect':
                    f.detail = 'moved out of testimony order'


RESTORED = ("The saved draft has the reporter's steno wording here, not Gemini's. Review may have "
            "restored it, so it cannot be credited to the AI.")
OUTSIDE = ("The reporter's text does not reach this part, so the saved draft's missing words may be "
           "a rejected edit rather than the AI's deletion.")
DROPPED = ("The saved draft and the reporter's text both leave out these Gemini words. Review may have "
           "restored the reporter's version, so the deletion cannot be credited or charged to the AI.")


def restoration_spans(case, draft_text, reporter_text):
    """Spans of a saved draft that review may have restored from the reporter's text.

    A saved BABABUI draft shows the steno wording wherever an edit was rejected.
    The drafting step never sees the steno, so a draft word that differs from
    Gemini's and matches the reporter's word at the same place cannot be credited
    to the AI. Rejected edits back to Gemini's own words stay invisible.
    """
    draft = case.version(draft_text)
    reporter = case.version(reporter_text)
    # The part of Gemini's text the reporter's text covers: from the first to the last
    # run of three words both share.
    same = [j is not None and reporter.draft.tokens[j].norm == case.asr[i].norm for i, j in enumerate(reporter.mapping)]
    runs = [i for i in range(len(same) - 2) if all(same[i:i + 3])]
    covered = (runs[0], runs[-1] + 3) if runs else (0, 0)
    spans = []
    for edit in draft.edits:
        heard = {t.norm for t in case.asr[edit.a:edit.b]}
        written = {draft.draft.tokens[j].norm for j in range(edit.c, edit.d)} - heard
        steno = {reporter.draft.tokens[j].norm for other in reporter.edits if overlaps(other.a, other.b, edit.a, edit.b)
                 for j in range(other.c, other.d)}
        gone = range(edit.a, edit.b)
        if edit.c == edit.d and cleanup_deletion(case.asr, edit.a, edit.b):
            continue  # optional cleanup, which is never graded anyway
        if edit.c == edit.d and (edit.b <= covered[0] or edit.a >= covered[1]):
            spans.append({'span': [edit.a, edit.b], 'reason': OUTSIDE})
        elif edit.c == edit.d and all(reporter.mapping[i] is None for i in gone):
            spans.append({'span': [edit.a, edit.b], 'reason': DROPPED})
        elif written & steno:
            spans.append({'span': [edit.a, edit.b], 'reason': RESTORED})
    return spans


def asr_speaker(case, i):
    return case.turns[case.asr[i].para][0]


def _flag_spans(case, version):
    """Gemini spans of each flagged paragraph, with the flag's area."""
    spans = []
    for p, paragraph in enumerate(version.draft.paragraphs):
        if not paragraph.flags:
            continue
        hits = [i for i in range(len(case.asr)) if version.paragraph_of(i) == p]
        if not hits:
            continue
        for number in paragraph.flags:
            spans.append(((min(hits), max(hits) + 1), version.draft.flag_area(number)))
    return spans


def _marks(positions, changed, is_term):
    """Highlights a version shows in a region: green for restored or corrected words,
    an orange underline too at a name or term, and a strikethrough when words were
    only removed."""
    if not changed:
        return frozenset()
    if not any(not isinstance(p, tuple) for p in positions):
        return frozenset({'removed'})
    return frozenset({'green', 'orange'} if is_term else {'green'})


def _mark_text(marks):
    if not marks:
        return 'no highlight'
    if marks == {'removed'}:
        return 'struck-through removal'
    return ' + '.join(['green background'] + (['orange underline'] if 'orange' in marks else []))


# Rendering -----------------------------------------------------------------

GREEN, YELLOW, ORANGE, DELETED = '#ccffd8', '#fff3a3', '#f08c00', '#9a9a9a'


def render(case, version):
    """HTML lines of a draft with change highlights against Gemini's text."""
    draft = version.draft
    green = set()
    deletions, trailing = {}, {}
    asr = case.asr
    for edit in version.edits:
        green.update(range(edit.c, edit.d))
        # Keep a removed phrase visible only when nothing replaced it and it was more
        # than optional cleanup (fillers, empty lead-ins, repeats, marked restarts).
        if edit.b > edit.a and edit.c == edit.d and not cleanup_deletion(asr, edit.a, edit.b):
            removed = ' '.join(t.raw for t in asr[edit.a:edit.b])
            before = edit.c - 1
            # Words cut from the end of a turn show at the end of that turn's paragraph.
            if (before >= 0 and edit.a and asr[edit.a - 1].para == asr[edit.a].para
                    and (edit.c >= len(draft.tokens) or draft.tokens[edit.c].para != draft.tokens[before].para)):
                trailing.setdefault(before, []).append(removed)
            else:
                deletions.setdefault(edit.c, []).append(removed)
    term_locations = [s for s, _ in case.term_units()] + [s for s, _, _ in case.term_spans(version)]
    orange = set()
    for edit in version.edits:
        if any(overlaps(edit.a, edit.b, *s) for s in term_locations):
            orange.update(range(edit.c, edit.d))
    yellow = set()
    by_para = {}
    for i in range(len(case.asr)):
        p = version.paragraph_of(i)
        if p is not None:
            by_para.setdefault(p, []).append(asr_speaker(case, i))
    for p, speakers in by_para.items():
        paragraph = draft.paragraphs[p]
        if paragraph.kind in SPEECH and paragraph.speaker != _majority(speakers):
            yellow.add(p)
    tokens_by_para = {}
    for j, token in enumerate(draft.tokens):
        tokens_by_para.setdefault(token.para, []).append((j, token))
    lines = []
    for p, paragraph in enumerate(draft.paragraphs):
        line, out, pos = paragraph.line, [], 0
        cuts = []
        if p in yellow and paragraph.label_span[1] > paragraph.label_span[0]:
            cuts.append((*paragraph.label_span, f'<span style="background:{YELLOW}">', '</span>'))
        for j, token in tokens_by_para.get(p, ()):
            if j in deletions:
                cuts.append((token.start, token.start, _deleted(deletions[j]), ''))
            if j in green:
                style = f'background:{GREEN}'
                if j in orange:
                    style += f'; text-decoration: underline {ORANGE} 2px; text-underline-offset: 3px'
                cuts.append((token.start, token.end, f'<span style="{style}">', '</span>'))
            if j in trailing:
                end = len(line) if j == tokens_by_para[p][-1][0] else token.end
                cuts.append((end, end, ' ' + _deleted(trailing[j]), ''))
        if tokens_by_para.get(p) and tokens_by_para[p][-1][0] == len(draft.tokens) - 1 and len(draft.tokens) in deletions:
            # Words removed after the draft's last word.
            cuts.append((len(line), len(line), ' ' + _deleted(deletions[len(draft.tokens)]), ''))
        for start, end, open_tag, close_tag in sorted(cuts, key=lambda c: (c[0], c[1])):
            if start < pos:
                continue
            out.append(escape(line[pos:start]))
            out.append(open_tag + escape(line[start:end]) + close_tag)
            pos = end
        out.append(escape(line[pos:]))
        if paragraph.flags:
            out.append(' <b style="color:#9a6700">[REVIEW ' + ', '.join(map(str, paragraph.flags)) + ']</b>')
        lines.append(''.join(out))
    return lines


def _deleted(phrases):
    return ''.join(f'<del style="color:{DELETED}">{escape(p)}</del> ' for p in phrases)


# Report --------------------------------------------------------------------

def load_cases(folder):
    """Load *.json cases from a folder and case.json files from its subfolders.

    A draft entry may name a `reporter_file`, the reporter's text from the same
    job. Spans where the saved draft matches the reporter instead of Gemini are
    then left ungraded for that draft, because review may have restored them.
    """
    folder = Path(folder)
    paths = [folder] if folder.is_file() else sorted({*folder.glob('*.json'), *folder.glob('*/case.json')})
    cases = []
    for path in paths:
        record = json.loads(path.read_text(encoding='utf-8'))
        for key in ('asr', 'expected'):
            if f'{key}_file' in record:
                record[key] = (path.parent / record.pop(f'{key}_file')).read_text(encoding='utf-8')
        drafts, reporters, hidden = record.get('drafts', {}), {}, set()
        for name, value in list(drafts.items()):
            if isinstance(value, dict):
                if value.get('flags_visible') is False:
                    hidden.add(name)
                if 'reporter_file' in value:
                    reporters[name] = (path.parent / value['reporter_file']).read_text(encoding='utf-8')
                drafts[name] = (value['text'] if 'text' in value
                                else (path.parent / value['file']).read_text(encoding='utf-8'))
        case = Case(record)
        case.flags_hidden = hidden
        for name, reporter in reporters.items():
            case.draft_excluded[name] = [(tuple(x['span']), x['reason'], ('wording', 'names'))
                                         for x in restoration_spans(case, drafts[name], reporter)]
        cases.append(case)
    return cases


def run(cases):
    results = []
    for case in cases:
        for name, text in case.drafts.items():
            result = grade(case, text, case.draft_excluded.get(name, ()), name not in case.flags_hidden)
            result['draft'] = name
            results.append(result)
    return results


def totals(results):
    out = {area: {key: 0 for key in (*CATEGORIES, 'evaluated', 'not_graded')} for area in AREAS}
    for result in results:
        for area in AREAS:
            for key, value in result['counts'][area].items():
                out[area][key] += value
    return out


def _excerpt_line(case, span):
    """The excerpt line that holds the marked span."""
    lines = case.excerpt(span).splitlines()
    line = next((line for line in lines if '«' in line), lines[0] if lines else '')
    if '«' in line and len(line) > 160:
        start, end = line.index('«'), line.index('»') if '»' in line else line.index('«')
        line = ('…' if start > 60 else '') + line[max(0, start - 60):end + 60] + ('…' if end + 60 < len(line) else '')
    return line


HIDDEN_FLAGS = ("Review flags are not graded for this draft. It went through review, which can drop inserted "
                "text such as [REVIEW n] tags, so a missing flag may not be the AI's.")


def report_html(cases, results, *, title='ASR-to-AI-draft grading', notes=()):
    by_id = {case.id: case for case in cases}
    sum_rows = []
    total = totals(results)
    for area in AREAS:
        row = total[area]
        sum_rows.append(f'<tr><th>{AREA_TITLES[area]}</th><td>{row["evaluated"]}</td>'
                        + ''.join(f'<td>{row[c] or ""}</td>' for c in CATEGORIES)
                        + f'<td>{row["not_graded"] or ""}</td></tr>')
    sections = []
    for result in results:
        case = by_id[result['case']]
        head = (f'<h2>{escape(case.title)} · draft “{escape(result["draft"])}”</h2>'
                + (f'<p class="context">{escape(case.context)}</p>' if case.context else '')
                + ('' if result.get('flags_visible', True) else f'<p class="context">{escape(HIDDEN_FLAGS)}</p>'))
        table = ['<table><tr><th>Area</th><th>Evaluated</th>' + ''.join(f'<th>{CATEGORY_TITLES[c]}</th>' for c in CATEGORIES)
                 + '<th>Not graded</th></tr>']
        for area in AREAS:
            row = result['counts'][area]
            table.append(f'<tr><th>{AREA_TITLES[area]}</th><td>{row["evaluated"]}</td>'
                         + ''.join(f'<td>{row[c] or ""}</td>' for c in CATEGORIES)
                         + f'<td>{row["not_graded"] or ""}</td></tr>')
        table.append('</table>')
        body = []
        for area in AREAS:
            for category in CATEGORIES:
                items = [f for f in result['failures'] if f.area == area and f.category == category]
                if not items:
                    continue
                body.append(f'<h3>{AREA_TITLES[area]} · {CATEGORY_TITLES[category]} ({len(items)})</h3>')
                for f in items:
                    body.append('<div class="failure">'
                                 f'<div class="label">Gemini excerpt</div><pre>{escape(f.excerpt)}</pre>'
                                 f'<div class="label">Contextual clue</div><p>{escape(f.clue)}</p>'
                                 f'<div class="grid"><div><div class="label">Expected</div><p>{escape(f.expected)}</p></div>'
                                 f'<div><div class="label">Actual</div><p>{escape(f.actual)}'
                                 + (f' <span class="detail">({escape(f.detail)})</span>' if f.detail else '')
                                 + '</p></div></div></div>')
        excluded = ''
        if result['excluded']:
            excluded = (f'<details><summary>Not graded ({len(result["excluded"])})</summary><ul>'
                        + ''.join(f'<li><pre>{escape(_excerpt_line(case, span))}</pre>'
                                  f'{escape(", ".join(areas))}: {escape(reason)}</li>'
                                  for span, reason, areas in result['excluded']) + '</ul></details>')
        drafts = ('<details><summary>Highlighted drafts (expected and actual)</summary><div class="grid">'
                  '<div><div class="label">Expected</div><pre>' + '\n'.join(render(case, result['expected']))
                  + '</pre></div><div><div class="label">Actual</div><pre>' + '\n'.join(render(case, result['actual']))
                  + '</pre></div></div></details>')
        sections.append(head + ''.join(table) + ''.join(body or ['<p>No failures.</p>']) + excluded + drafts)
    legend = (f'<p class="legend"><span style="background:{GREEN}">restored or corrected words</span> '
              f'<span style="background:{YELLOW}">changed speaker label</span> '
              f'<span style="background:{GREEN}; text-decoration: underline {ORANGE} 2px">corrected name, organization or term</span> '
              f'<del style="color:{DELETED}">removed from Gemini\'s text</del></p>')
    notes_html = ('<ul class="notes">' + ''.join(f'<li>{escape(n)}</li>' for n in notes) + '</ul>') if notes else ''
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>
<style>
body {{ font: 15px/1.5 system-ui, sans-serif; margin: 24px auto; max-width: 1200px; color: #1f2328; padding: 0 16px; }}
table {{ border-collapse: collapse; margin: 8px 0 16px; }} th, td {{ border: 1px solid #d0d7de; padding: 4px 10px; text-align: left; }}
td {{ text-align: right; min-width: 3em; }} pre {{ white-space: pre-wrap; font: 13px/1.6 ui-monospace, monospace; background: #f6f8fa; padding: 8px; margin: 4px 0; }}
.failure {{ border-left: 3px solid #d0d7de; padding: 4px 12px; margin: 10px 0 18px; }}
.label {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #59636e; margin-top: 6px; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }} p {{ margin: 4px 0; }} .detail {{ color: #59636e; }}
.context {{ color: #59636e; }} .notes li {{ margin: 4px 0; }}
.legend span, .legend del {{ margin-right: 12px; padding: 1px 4px; }} h2 {{ margin-top: 40px; border-top: 1px solid #d0d7de; padding-top: 16px; }}
</style></head><body><h1>{escape(title)}</h1>{legend}{notes_html}
<table><tr><th>Area</th><th>Evaluated</th>{''.join(f'<th>{CATEGORY_TITLES[c]}</th>' for c in CATEGORIES)}<th>Not graded</th></tr>{''.join(sum_rows)}</table>
{''.join(sections)}</body></html>"""


def results_json(results):
    return [{'case': r['case'], 'draft': r['draft'], 'counts': r['counts'],
             'failures': [f.__dict__ for f in r['failures']]} for r in results]


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Grade saved AI drafts against hand-graded ASR cases.')
    parser.add_argument('cases', help='Folder of case JSON files.')
    parser.add_argument('--html', help='Write an HTML report here.')
    parser.add_argument('--json', help='Write failures and counts as JSON here.')
    parser.add_argument('--notes', help='A text file of notes for the top of the HTML report, one per paragraph.')
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    results = run(cases)
    if args.html:
        notes = ([n.strip() for n in Path(args.notes).read_text(encoding='utf-8').split('\n\n') if n.strip()]
                 if args.notes else ())
        Path(args.html).write_text(report_html(cases, results, notes=notes), encoding='utf-8')
    if args.json:
        Path(args.json).write_text(json.dumps(results_json(results), indent=2, ensure_ascii=False), encoding='utf-8')
    total = totals(results)
    for area in AREAS:
        row = total[area]
        print(f'{AREA_TITLES[area]}: evaluated {row["evaluated"]}, '
              + ', '.join(f'{CATEGORY_TITLES[c].lower()} {row[c]}' for c in CATEGORIES)
              + f', not graded {row["not_graded"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
