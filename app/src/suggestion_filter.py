"""Automatic rules. Preparation preserves Original; auto_accept edits it natively.

1. Restore deleted trailing spaces/tabs while preparing aligned paragraphs.
   Delete mode removes paragraph-ending whitespace as an undoable native edit.
2. Match SPEAKER N labels using unambiguous aligned bylines/colloquy only.
   A strict majority with at least two votes maps to an existing speaker label.
   Matching labels disappear from review; mismatched attributions stay separate.
3. Never infer speakers from Q/A labels or names inside testimony. Ties, weak
   evidence, and ambiguous native field identities remain unresolved.
4. Speaker overrides affect only unresolved occurrences. Evidence is frozen for
   the AI result; these counts measure agreement, not verified speaker identity.
   When only the AI label disputes an existing label, speaker_votes asks the
   voice and the context. Support for the existing label keeps it; agreement
   with the AI label suggests the change; anything else is "Needs review".
   Overrides never replace a kept label.
5. Examination headings use the native Centered Paragraph Style at export and
   in preview. No padding is stored (test_native_structure covers export).
6. Keep Original's leading indentation and generated Q/A spacing on aligned
   paragraphs, using the existing proposal rule (test_suggestions covers this).

7. Auto-accept wording through these rules:
   - Punctuation: insert/delete/replace , ; : . ? ! or dashes, with adjacent
     ordinary spaces. Accept apostrophe-only edits, but preserve numeric punctuation.
   - Case: unchanged spelling with different capitalization.
   - Contractions: equivalent I am / I'm, pronoun are / 're and have / 've.
     Unambiguous negative contractions also match their expanded forms
     in either direction. Ambiguous forms remain reviewable.
   - Short/common words: replace words only when BOTH are at most two letters;
     insert/delete such words or the closed set {and, the}. Never alter negation.
   - Ordinal suffixes: add or remove st/nd/rd/th on an unchanged number.
     The suggestion must contain only the suffix change.
   - Positive confirmations: equivalent uses of right, true and correct.
   - Number forms: digits and the matching whole number in words.
   Check whole words, not changed character fragments. These rules may combine
   within one card, but every part must qualify. Preserve speaker/Q/A labels,
   native fields/symbols, numbers, hard spaces, indentation and paragraph breaks.
   Other wording and spacing stays pending. test_automatic_suggestions covers
   examples, whole-word guards, native application, idempotence and undo.
8. Original off-record notes authorize discussion suppression only with unique
   approximate departure/return matches and subsequent corroborating testimony.
   Excluded text is audited and restored by Undo. Ambiguous intervals stay pending.
"""
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import re

from app.src import speaker_votes
from app.src.casecat.elements import NativeElement, speaker_number
from app.src.casecat.fields import field_values
from app.src.number_forms import equivalent_integer


_NAME_PATTERN = r'SPEAKER\s+\d+|(?:MS|MR|MRS|DR)\. [^:\n]+|THE [^:\n]+'
_LABEL_PATTERN = r'^(?P<prefix>[ \t]*(?:BY[ \t]+)?)(?P<name>%s):'
LABEL = re.compile(_LABEL_PATTERN % _NAME_PATTERN, re.I)
GENERIC = re.compile(r'SPEAKER\s+(\d+)', re.I)

PUNCTUATION = frozenset(',;:.?!-\u2013\u2014')
DROP_APOSTROPHES = str.maketrans('', '', "'’")
COMMON_WORDS = frozenset({'and', 'the'})
WORD = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)*|\d+|[^\s]")
CONTRACTION = re.compile(r"\b(i)['\u2019]m\b|\b(you|we|they)['\u2019]re\b|\b(i|you|we|they)['\u2019]ve\b", re.I)
NEGATIVE_CONTRACTION = re.compile(
    r"\b(is|are|was|were|do|does|did|has|have|had|could|should|would|must|might|need|dare|ca|wo|sha)n['\u2019]t\b",
    re.I,
)
IRREGULAR_NEGATIVES = {'ca': 'cannot', 'wo': 'will not', 'sha': 'shall not'}
TRAILING_WHITESPACE = re.compile(r'[ \t\u00a0]+$', re.M)
TRAILING_CHARS = ' \t\u00a0'
ORDINAL_NUMBER = re.compile(r'([0-9]+)(?:st|nd|rd|th)', re.I)
FORM_TOKEN = re.compile(r"[A-Za-z]+(?:['’‐‑-][A-Za-z]+)*|[0-9]+(?:,[0-9]+)*|[^\s]")
CONFIRMATION = re.compile(r'\b(?:right|true|correct)\b', re.I)
CONFIRMING_PREFIX = re.compile(r"\b(?:(?:is|was) (?:that|this|it)|(?:that|this|it)(?: (?:is|was)|['’]s))$", re.I)
CONFIRMING_FOLLOWUP = re.compile(r"(?:that|this|it)(?:['’]s| (?:is|was))\b", re.I)
QA_PREFIX = re.compile(r'^[ \t]*[QA][ \t]+')


def _ordinal_suffix_change(left, right, a, b, c, d):
    ordinal, number = left[a:b], right[c:d]
    following_number = right[d:d+2]
    if len(ordinal) < len(number):
        ordinal, number = number, ordinal
        following_number = left[b:b+2]
    match = ORDINAL_NUMBER.fullmatch(ordinal)
    # A suffix inserted before the decimal point is inside the number.
    return bool(match and match[1] == number and not re.fullmatch(r'\.[0-9]', following_number))


def _expand_negative(match):
    stem = match[1]
    expanded = IRREGULAR_NEGATIVES.get(stem.lower(), f'{stem} not')
    if match[0].isupper():
        return expanded.upper()
    if stem.istitle():
        return expanded.capitalize()
    return expanded


def _words(text, disabled_rules):
    if 'capitalization' not in disabled_rules:
        text = text.casefold()
    if 'punctuation' not in disabled_rules:
        text = text.replace('\u2019', "'")
    if 'contractions' not in disabled_rules:
        def expand(match):
            pronoun = match[1] or match[2] or match[3]
            verb = 'am' if match[1] else 'are' if match[2] else 'have'
            suffix = match[0][len(pronoun)+1:]
            return f'{pronoun} {verb.upper() if suffix.isupper() else verb}'

        text = CONTRACTION.sub(expand, text)
        text = NEGATIVE_CONTRACTION.sub(_expand_negative, text)
    return [m[0] for m in WORD.finditer(text)
            if 'punctuation' in disabled_rules or m[0] not in PUNCTUATION]


def _is_confirmation(text, token):
    if not CONFIRMATION.fullmatch(token[0]):
        return False
    line_start = text.rfind('\n', 0, token.start()) + 1
    before = text[line_start:token.start()]
    label = LABEL.match(before) or QA_PREFIX.match(before)
    before = (before[label.end():] if label else before).strip()
    _, end = token.span()
    after = text[end:end+32].split('\n', 1)[0].lstrip()
    if CONFIRMING_PREFIX.search(before):
        return not after or after[0] in '.!?'
    if before.endswith((',', ';')):
        return after.startswith('?')
    return not before and (not after or after[0] in '.!?'
                           or bool(CONFIRMING_FOLLOWUP.match(after.lstrip(', '))))


def _number_replacement(left, right, old, new):
    first_word = old[0][0]
    if len(old) == 1 and first_word[0].isdigit():
        left, right, old, new = right, left, new, old
    if len(new) != 1:
        return False
    return equivalent_integer(left, old[0].start(), old[-1].end(), right, *new[0].span())


def _equivalent_wording(left, right, span, disabled_rules):
    a, b, c, d = span
    before, after = left[a:b], right[c:d]
    number = ('number_forms' not in disabled_rules
              and any(ch.isdigit() for ch in before + after))
    confirmation = ('positive_confirmations' not in disabled_rules
                    and CONFIRMATION.search(before) and CONFIRMATION.search(after))
    if not number and not confirmation:
        return None
    # Preserve dashes that could be a sign or range, even in spaced notation.
    punctuation = PUNCTUATION - set('-–—') if 'punctuation' not in disabled_rules else ()
    old = [token for token in FORM_TOKEN.finditer(left, a, b) if token[0] not in punctuation]
    new = [token for token in FORM_TOKEN.finditer(right, c, d) if token[0] not in punctuation]
    old_keys = [token[0].casefold() for token in old]
    new_keys = [token[0].casefold() for token in new]
    reasons = set()
    for tag, i, j, k, l in SequenceMatcher(None, old_keys, new_keys, autojunk=False).get_opcodes():
        if tag == 'equal':
            # Leave other numeric notation alone even if dropping punctuation
            # would make its tokens look the same.
            if any(ch.isdigit() for word in old_keys[i:j] for ch in word):
                return None
            if ('capitalization' in disabled_rules
                    and [token[0] for token in old[i:j]] != [token[0] for token in new[k:l]]):
                return None
        elif tag != 'replace':
            return None
        elif (confirmation and j-i == l-k == 1
              and _is_confirmation(left, old[i]) and _is_confirmation(right, new[k])):
            reasons.add('positive confirmation')
        elif number and _number_replacement(left, right, old[i:j], new[k:l]):
            reasons.add('number form')
        else:
            return None
    return ' / '.join(sorted(reasons)) or None


def automatic_reason(change, *, disabled_rules=frozenset()):
    """Classify whole review decisions; never hide an unqualified part of a card."""
    if change.kind != 'text' or change.field or len(change.ranges) != 1:
        return None
    a, b, c, d = change.ranges[0]
    original, incoming = change.original, change.incoming
    left, right = original.text, incoming.text
    before, after = left[a:b], right[c:d]
    if any(ch in before+after for ch in '\n\r\t\u00a0') or before.strip() == after.strip():
        return None
    if (any(ch in before+after for ch in '.-:\u2013\u2014')
            and (left[b:b+1].isdigit() or right[d:d+1].isdigit())):
        return None
    for text, start, end in ((left, a, b), (right, c, d)):
        line_start = text.rfind('\n', 0, start)+1
        line = text[line_start:text.find('\n', start) if '\n' in text[start:] else len(text)]
        prefix = LABEL.match(line) or QA_PREFIX.match(line)
        if prefix and start < line_start+prefix.end():
            return None
    # Token diffs may start inside contractions or words. Extend BOTH ranges by
    # the shared unchanged context so a small substring cannot bypass the limit.
    word_char = lambda ch: ch.isalnum() or ch in "'\u2019"
    def context(text, start, end):
        x, y = start, end
        if start < len(text) and word_char(text[start]):
            while x and word_char(text[x-1]):
                x -= 1
        if end and word_char(text[end-1]):
            while y < len(text) and word_char(text[y]):
                y += 1
        return start-x, y-end
    front_a, back_a = context(left, a, b)
    front_b, back_b = context(right, c, d)
    front, back = max(front_a, front_b), max(back_a, back_b)
    a, b, c, d = max(0, a-front), min(len(left), b+back), max(0, c-front), min(len(right), d+back)
    for revision, start, end in ((original, a, b), (incoming, c, d)):
        if any(start < e.end and end > e.start or start == end and e.start < start < e.end for e in revision.elements):
            return None
    if 'date_ordinals' not in disabled_rules and _ordinal_suffix_change(left, right, a, b, c, d):
        return 'ordinal suffix'
    if reason := _equivalent_wording(left, right, (a, b, c, d), disabled_rules):
        return reason
    # Numeric and unsupported punctuation tokens must match exactly, including
    # their punctuation. Do not turn decimal/date changes into cosmetic edits.
    if any(ch.isdigit() for ch in left[a:b]+right[c:d]) and left[a:b] != right[c:d]:
        return None
    if ('punctuation' not in disabled_rules and before != after
            and before.translate(DROP_APOSTROPHES) == after.translate(DROP_APOSTROPHES)):
        return 'punctuation'
    before_words, after_words = _words(left[a:b], disabled_rules), _words(right[c:d], disabled_rules)
    aa = [word.casefold() for word in before_words]
    bb = [word.casefold() for word in after_words]
    short = lambda word: word.isascii() and word.isalpha() and len(word) <= 2 and word != 'no'
    common = lambda word: short(word) or word in COMMON_WORDS
    for tag, i, j, k, l in SequenceMatcher(None, aa, bb, autojunk=False).get_opcodes():
        old, new = aa[i:j], bb[k:l]
        if tag == 'equal':
            if 'capitalization' in disabled_rules and before_words[i:j] != after_words[k:l]:
                return None
            continue
        if 'short_common_words' in disabled_rules:
            return None
        if tag == 'replace' and not (len(old) == len(new) and all(short(w) for w in old+new)):
            return None
        if tag in ('insert', 'delete') and not all(common(w) for w in old+new):
            return None
    return 'punctuation/case/contraction' if aa == bb else 'short/common words'


def _delete_trailing(revision, side, review, records):
    text = revision.text
    edits = []
    for match in TRAILING_WHITESPACE.finditer(text):
        start, end = match.span()
        last_element = bisect_left(revision.elements, end, key=lambda element: element.start) - 1
        if last_element >= 0:
            start = max(start, revision.elements[last_element].end)
        if start < end:
            edits.append((start, end))
            records.append({'side': side, 'range': [start, end], 'before': text[start:end],
                            'after': '', 'rule': 'trailing whitespace'})
    for start, end in reversed(edits):
        revision = revision._replace(start, end, '')
    if side == 'incoming' and edits:
        track_decisions(review, [(start, start, start, end) for start, end in edits], incoming_changed=True)
    return revision


def auto_accept(state, *, disabled_rules=frozenset()):
    """Apply one undoable native batch once per AI result, keeping an audit log."""
    from copy import deepcopy
    from app.src.suggestions import suggestions, resolve
    if (state.review or {}).get('automatic_filter') == 1:
        return []
    review = deepcopy(state.review) if state.review else {
        'version': 1, 'evidence': {'speakers': {}, 'occurrences': []}, 'overrides': {}, 'locations': []}
    original, incoming = state.original, state.incoming
    whitespace_records = []
    if 'trailing_whitespace' not in disabled_rules:
        original = _delete_trailing(original, 'original', review, whitespace_records)
        incoming = _delete_trailing(incoming, 'incoming', review, whitespace_records)
        if (whitespace_records and original.text == incoming.text and original.elements == incoming.elements
                and original.definitions == incoming.definitions):
            incoming = original
    candidates = [(change, reason) for change in suggestions(original, incoming)
                  if (reason := automatic_reason(change, disabled_rules=disabled_rules))]
    records = []
    # Descending positions preserve all earlier offsets. Resolve uses the same
    # anchored operations as an individual Accept, retaining destination audio.
    for change, reason in reversed(candidates):
        change = replace(change, original=original, incoming=incoming)
        a, b, c, d = change.ranges[0]
        records.append({'ranges': [list(span) for span in change.ranges], 'before': original.text[a:b],
                        'after': incoming.text[c:d], 'rule': reason})
        old_text = incoming.text
        original, incoming = resolve(original, incoming, change, True)
        track_decision(review, change, old_text, incoming.text)
    review.update(automatic_filter=1, automatic_changes=[
        *review.get('off_record_changes', []), *whitespace_records, *reversed(records)])
    state.original, state.incoming, state.review = original, incoming, review
    return review['automatic_changes']


def _paragraphs(text, *, byline_context=True, labels=LABEL):
    result, offset = [], 0
    parts = text.split('\n')
    for index, line in enumerate(parts):
        label = labels.match(line)
        body = line[label.end():].strip() if label else re.sub(r'^[ \t]*[QA](?:[ \t]+|$)', '', line).strip()
        if byline_context and label and not body and 'BY' in label['prefix'].upper():
            body = next((re.sub(r'^\s*[QA]\s+', '', p).strip() for p in parts[index+1:] if p.strip()), '')
        result.append((offset, line, label, body.casefold()))
        offset += len(line) + 1
    return result


def aligned_paragraphs(original, incoming, *, labels=LABEL):
    from app.src.suggestions import _paragraph_ops
    old, new = _paragraphs(original, labels=labels), _paragraphs(incoming, labels=labels)
    # Borrowed byline wording is evidence for speaker attribution only. Using
    # it as another content anchor duplicates the following question.
    left = [p[3] for p in _paragraphs(original, byline_context=False, labels=labels)]
    right = [p[3] for p in _paragraphs(incoming, byline_context=False, labels=labels)]
    pairs = []
    for _, a, b, c, d in _paragraph_ops(left, right):
        if b-a == d-c:
            pairs.extend(zip(range(a, b), range(c, d)))
    return old, new, pairs


def speaker_name_key(name):
    return ' '.join(name.split()).casefold()


def _label_range(paragraph):
    offset, _, label, _ = paragraph
    return offset+label.start('name'), offset+label.end('name')


@dataclass(frozen=True)
class SpeakerChoice:
    name: str
    references: tuple[NativeElement, ...]

    @property
    def selectable(self):
        return len(self.references) <= 1


def index_speaker_fields(revision):
    """Keep examiner references for reuse even before that lawyer speaks in the body."""
    start = revision.text.find('I N D E X')
    end = revision.text.find('E X H I B I T S', start) if start >= 0 else -1
    return tuple(e for e in revision.elements if start <= e.start < end
                 and e.kind == 'field' and speaker_number(e.name) and e.value)


def _label_pattern(index_fields):
    names = [re.escape(e.value) for e in index_fields or () if not LABEL.fullmatch(e.value + ':')]
    return re.compile(_LABEL_PATTERN % '|'.join((_NAME_PATTERN, *names)), re.I) if names else LABEL


def _speaker_choices(paragraphs, fields, index_fields=()):
    labels = {}
    for paragraph in paragraphs:
        label = paragraph[2]
        if not label or GENERIC.fullmatch(label['name']):
            continue
        name = label['name'].strip()
        _, references = labels.setdefault(speaker_name_key(name), (name, {}))
        if field := fields.get(_label_range(paragraph)):
            references.setdefault(field.name, field)
    for field in index_fields or ():
        _, references = labels.setdefault(speaker_name_key(field.value), (field.value, {}))
        references.setdefault(field.name, field)
    return {key: SpeakerChoice(name, tuple(references.values()))
            for key, (name, references) in labels.items()}


def _field_ranges(revision):
    return {(e.start, e.end): e for e in revision.elements if e.kind == 'field'}


def speaker_choices(original):
    """Offer labels used in testimony and the confirmed examiner index."""
    indexed = index_speaker_fields(original)
    paragraphs = _paragraphs(original.text, labels=_label_pattern(indexed))
    return {key: choice for key, choice in
            _speaker_choices(paragraphs, _field_ranges(original), indexed).items()
            if choice.selectable}


def _replace_speaker(revision, start, end, name, reference, values):
    if reference is None:
        return revision._replace(start, end, name)
    result = revision._replace(start, end, '').insert_field(start, reference.name, values[reference.name])
    return replace(result, elements=tuple(
        replace(e, raw=reference.raw, source=reference.source)
        if e.kind == 'field' and e.start == start else e for e in result.elements))


def _restore_trailing(original, text, *, labels=LABEL):
    from app.src.suggestions import text_edits

    old, new, pairs = aligned_paragraphs(original.text, text, labels=labels)
    edits = []
    for i, j in pairs:
        a, b = old[i][1], new[j][1]
        before = a[len(a.rstrip(TRAILING_CHARS)):]
        after = b[len(b.rstrip(TRAILING_CHARS)):]
        if len(before) > len(after) and before.startswith(after) and b.strip():
            edits.append((new[j][0]+len(b)-len(after), new[j][0]+len(b), before))
    for a, b, value in reversed(edits):
        text = text[:a] + value + text[b:]
    # A split or join can leave a shared paragraph ending without a
    # one-to-one paragraph match. Restore deletions at those endings too.
    source = original.text
    for a, b, c, d in reversed(text_edits(source, text)):
        if (c == d and not source[a:b].strip(TRAILING_CHARS)
                and source[b:b+1] == text[c:c+1] and text[c:c+1] in ('', '\n')
                and text[text.rfind('\n', 0, c)+1:c].strip()):
            text = text[:c] + source[a:b] + text[c:]
    return text


def prepare(original, text, *, evidence=None, overrides=None, index_fields=None, voice=None):
    """Return a structured proposal and JSON-safe, frozen speaker evidence."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    labels = _label_pattern(index_fields)
    old, new, pairs = aligned_paragraphs(original.text, text, labels=labels)
    fields = _field_ranges(original)
    choices = _speaker_choices(old, fields, index_fields)
    paired = {j: i for i, j in pairs}
    fresh = evidence is None
    if evidence is None:
        counts, occurrences = {}, []
        unaligned = Counter()
        old_counts = Counter(p[3] for p in old if p[2])
        new_counts = Counter(p[3] for p in new if p[2])
        for j, paragraph in enumerate(new):
            _, _, label, body = paragraph
            if not label or not (tag := GENERIC.fullmatch(label['name'])):
                continue
            speaker = f'SPEAKER {int(tag[1])}'
            votes = counts.setdefault(speaker, Counter())
            source = old[paired[j]] if j in paired else None
            name = None
            if (source and source[2] and (choice := choices.get(speaker_name_key(source[2]['name'])))
                    and body and source[3]
                    and old_counts[source[3]] == new_counts[body] == 1
                    and SequenceMatcher(None, source[3], body, autojunk=False).ratio() >= .5):
                name = choice.name
                votes[name] += 1
            else:
                unaligned[speaker] += 1
            start, end = _label_range(paragraph)
            occurrences.append({'id': len(occurrences), 'speaker': speaker,
                                'original_name': name, 'start': start, 'end': end})
        summaries = {}
        for speaker, votes in counts.items():
            leader, support = votes.most_common(1)[0] if votes else (None, 0)
            winner = leader if (support >= 2 and support * 2 > sum(votes.values())
                                and choices[speaker_name_key(leader)].selectable) else None
            summaries[speaker] = {'counts': dict(votes), 'mapped': winner, 'leader': leader,
                                  'unresolved': unaligned[speaker]}
        evidence = {'speakers': summaries, 'occurrences': occurrences}
    mappings = {key: value['mapped'] for key, value in evidence['speakers'].items()}
    mappings.update(overrides or {})
    occurrences = {(o['start'], o['end']): o for o in evidence['occurrences']}
    edits = []
    for j, paragraph in enumerate(new):
        label = paragraph[2]
        if label and (tag := GENERIC.fullmatch(label['name'])) and (name := mappings.get(f'SPEAKER {int(tag[1])}')):
            key = speaker_name_key(name)
            choice = choices.get(key)
            if not choice or not choice.selectable:
                raise ValueError('Choose an existing speaker label.')
            prior = old[paired[j]][2] if j in paired else None
            display = prior['name'] if prior and speaker_name_key(prior['name']) == key else choice.name
            occurrence = occurrences.get(_label_range(paragraph))
            if (occurrence is not None and prior and speaker_name_key(prior['name']) != key
                    and speaker_name_key(prior['name']) in choices):
                # Gemini alone disputes an existing label. Ask the voice and context.
                if fresh:
                    decision, votes = speaker_votes.checks(old, paired[j], prior['name'].strip(),
                                                           choice.name, voice=voice)
                    occurrence.update(decision=decision, votes=votes)
                if occurrence.get('decision') == speaker_votes.KEEP:
                    display = prior['name']
            edits.append((*_label_range(paragraph), display))
    for a, b, name in reversed(edits):
        text = text[:a] + name + text[b:]
    text = _restore_trailing(original, text, labels=labels)
    # Do not let whole-text revision treat attribution changes as global renames.
    if evidence['occurrences']:
        # Unpaired paragraphs can move across token alignment blocks too.
        # No speaker occurrence may be interpreted as a global definition edit
        # while resolving generic AI labels.
        attribution_paragraphs = old
    elif index_fields is not None:
        # A changed or unpaired speaker is an attribution to review at this
        # occurrence. The shared native definition also names a cover examiner.
        unchanged = {i for i, j in pairs if old[i][2] and new[j][2] and old[i][2]['name'] == new[j][2]['name']}
        attribution_paragraphs = [paragraph for i, paragraph in enumerate(old) if i not in unchanged]
    else:
        attribution_paragraphs = [old[i] for i, j in pairs if new[j][2] and (
            GENERIC.fullmatch(new[j][2]['name']) or (speaker_name_key(new[j][2]['name']) in choices
            and old[i][2] and old[i][2]['name'] != new[j][2]['name']))]
    speaker_elements = {fields[_label_range(p)] for p in attribution_paragraphs
                        if p[2] and _label_range(p) in fields}
    base = replace(original, elements=tuple(e for e in original.elements if e not in speaker_elements))
    from app.src.suggestions import propose
    revision = propose(base, text)
    _, projected, projected_pairs = aligned_paragraphs(original.text, revision.text, labels=labels)
    aligned_sources = {j: old[i] for i,j in projected_pairs}
    values = field_values(original)
    projected_fields = _field_ranges(revision)
    for paragraph_index in reversed(range(len(projected))):
        paragraph = projected[paragraph_index]
        label = paragraph[2]
        if not label:
            continue
        key = speaker_name_key(label['name'])
        if not (choice := choices.get(key)):
            continue
        a, b = _label_range(paragraph)
        if (a, b) in projected_fields:
            continue
        source = aligned_sources.get(paragraph_index)
        if source and source[2] and speaker_name_key(source[2]['name']) == key:
            reference = fields.get(_label_range(source))
        else:
            reference = choice.references[0] if len(choice.references) == 1 else None
        if reference:
            revision = _replace_speaker(revision, a, b, label['name'], reference, values)
    return revision, evidence


def begin_review(state, text, *, exclude_off_record=True, index_fields=None, voice=None):
    """Freeze evidence and return an optional pre-exclusion undo snapshot.

    `voice` is an optional speaker_votes.VoiceCheck for state.original.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    undo, excluded = None, []
    if exclude_off_record:
        from types import SimpleNamespace
        from app.src.off_record import exclude_discussions
        filtered, excluded = exclude_discussions(state.original.text, text)
        if excluded:
            # Build raw speaker evidence only for Undo, never use it to vote in
            # the filtered proposal. It has different paragraph offsets.
            raw = SimpleNamespace(original=state.original)
            begin_review(raw, text, exclude_off_record=False, index_fields=index_fields, voice=voice)
            raw.review.update(automatic_filter=1, automatic_changes=[])
            undo = (state.original, raw.incoming, raw.review)
            text = filtered
    incoming, evidence = prepare(state.original, text, index_fields=index_fields, voice=voice)
    if (incoming.text == state.original.text and incoming.elements == state.original.elements
            and incoming.definitions == state.original.definitions):
        incoming = state.original
    # Normalization changes label lengths, not paragraph order.
    labels = _label_pattern(index_fields)
    raw_paragraphs = _paragraphs(text, labels=labels)
    new_paragraphs = _paragraphs(incoming.text, labels=labels)
    locations = []
    for occurrence in evidence['occurrences']:
        index = next(i for i, p in enumerate(raw_paragraphs) if p[2] and p[0]+p[2].start('name') == occurrence['start'])
        if index < len(new_paragraphs) and new_paragraphs[index][2]:
            offset, _, label, _ = new_paragraphs[index]
            locations.append({**occurrence, 'start': offset+label.start('name'),
                              'end': offset+label.end('name'), 'resolved': False})
    state.incoming = incoming
    state.review = {'version': 1, 'evidence': evidence, 'overrides': {}, 'locations': locations}
    if excluded:
        state.review['off_record_changes'] = excluded
    return undo


def validate_review(review, text):
    """Reject malformed persisted evidence before it reaches review controls."""
    try:
        if not isinstance(review, dict) or review['version'] != 1:
            raise ValueError()
        speakers = review['evidence']['speakers']
        if not isinstance(speakers, dict) or not isinstance(review['evidence']['occurrences'], list):
            raise ValueError()
        for speaker, summary in speakers.items():
            if not isinstance(speaker, str) or not GENERIC.fullmatch(speaker):
                raise ValueError()
            if not isinstance(summary['counts'], dict) or any(not isinstance(n, str) or type(v) is not int or v < 1 for n,v in summary['counts'].items()):
                raise ValueError()
            if any(summary[k] is not None and not isinstance(summary[k], str) for k in ('mapped','leader')):
                raise ValueError()
            if type(summary['unresolved']) is not int or summary['unresolved'] < 0:
                raise ValueError()
        if not isinstance(review['overrides'], dict) or any(k not in speakers or (v is not None and not isinstance(v,str)) for k,v in review['overrides'].items()):
            raise ValueError()
        if not isinstance(review['locations'], list):
            raise ValueError()
        for location in review['locations']:
            if (location['speaker'] not in speakers or type(location['start']) is not int
                    or type(location['end']) is not int or type(location['resolved']) is not bool
                    or not 0 <= location['start'] <= location['end'] <= len(text)):
                raise ValueError()
            if 'decision' in location and location['decision'] not in speaker_votes.DECISIONS:
                raise ValueError()
            votes = location.get('votes', {})
            if not isinstance(votes, dict) or any(not isinstance(k, str) or (v is not None and not isinstance(v, str))
                                                  for k, v in votes.items()):
                raise ValueError()
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError('Invalid speaker review evidence.') from exc


def track_decision(review, change, before_text, after_text):
    track_decisions(review, change.ranges, incoming_changed=before_text != after_text)


def track_decisions(review, ranges, *, incoming_changed):
    if review is None:
        return
    edits = sorted((c, d, b-a) for a,b,c,d in ranges) if incoming_changed else []

    def mapped(position, end=False):
        delta = 0
        for a,b,size in edits:
            if position < a or (position == a == b and end):
                break
            if a != b and position <= b:
                return a+delta+(size if end or position == b else 0)
            delta += size-(b-a)
        return position+delta

    for location in review['locations']:
        a, b = location['start'], location['end']
        if any(c < b and d > a for _, _, c, d in ranges):
            location['resolved'] = True
        start = mapped(a)
        location.update(start=start, end=max(start, mapped(b, end=True)))


def questionable_speaker_defaults(review, ranges):
    """Find unsupported or shared automatic names affected by this review."""
    if not review:
        return []
    summaries = review['evidence']['speakers']
    overrides = review['overrides']
    names = {speaker: overrides.get(speaker, summary['mapped'])
             for speaker, summary in summaries.items()}
    uses = Counter(name.casefold() for name in names.values() if name)
    pending = {location['speaker'] for location in review['locations'] if not location['resolved']
               and any(c < location['end'] and d > location['start'] for _, _, c, d in ranges)}
    return [(speaker, name) for speaker, name in names.items()
            if name and speaker in pending and speaker not in overrides
            and (not summaries[speaker]['counts'].get(name) or uses[name.casefold()] > 1)]


def flagged_attributions(review, ranges):
    """Count pending label changes that only the AI label supports."""
    if not review:
        return 0
    return sum(1 for location in review['locations']
               if not location['resolved'] and location.get('decision') == speaker_votes.FLAG
               and any(c < location['end'] and d > location['start'] for _, _, c, d in ranges))


def override_speaker(state, speaker, name):
    """Change pending attributions without replaying completed decisions."""
    if state.review is None or speaker not in state.review['evidence']['speakers']:
        raise ValueError('This speaker result is no longer available.')
    choice = None
    if name is not None:
        choice = speaker_choices(state.original).get(speaker_name_key(name))
        if choice is None:
            raise ValueError('Choose an existing speaker label.')
        name = choice.name
    reference = choice.references[0] if choice and choice.references else None
    values = field_values(state.original) if reference else {}
    revision = state.incoming
    locations = state.review['locations']
    # A kept label had voice or context support for this paragraph, whatever
    # name the AI speaker tag maps to.
    for loc in sorted((p for p in locations if p['speaker'] == speaker and not p['resolved']
                       and p.get('decision') != speaker_votes.KEEP), key=lambda p:p['start'], reverse=True):
        a, b = loc['start'], loc['end']
        value = name or speaker
        if revision.text[a:b] == value:
            continue
        revised = _replace_speaker(revision, a, b, value, reference, values)
        delta = len(revised.text) - len(revision.text)
        for other in locations:
            if other is loc:
                other['end'] = b + delta
            elif other['start'] >= b:
                other['start'] += delta
                other['end'] += delta
        revision = revised
    state.incoming = revision
    state.review['overrides'][speaker] = name
