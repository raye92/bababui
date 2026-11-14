"""Automatic rules. Preparation preserves Original; auto_accept edits it natively.

1. Restore deleted ordinary trailing spaces/tabs on aligned logical paragraphs.
   Keep newlines, internal spacing, hard spaces, and genuine paragraph changes.
2. Match SPEAKER N labels using unambiguous aligned bylines/colloquy only.
   A strict majority with at least two votes maps to one existing native field.
   Matching labels disappear from review; mismatched attributions stay separate.
3. Never infer speakers from Q/A labels or names inside testimony. Ties, weak
   evidence, and ambiguous native field identities remain unresolved.
4. Speaker overrides affect only unresolved occurrences. Evidence is frozen for
   the AI result; these counts measure agreement, not verified speaker identity.
5. Examination headings use the native Centered Paragraph Style at export and
   in preview. No padding is stored (test_native_structure covers export).
6. Keep Original's leading indentation and generated Q/A spacing on aligned
   paragraphs, using the existing proposal rule (test_suggestions covers this).

7. Auto-accept wording only through these four composable rules:
   - Punctuation: insert/delete/replace , ; : . ? ! or dashes, with adjacent
     ordinary spaces. Never change numeric punctuation or apostrophes this way.
   - Case: unchanged spelling with different capitalization.
   - Contractions: equivalent I am / I'm, pronoun are / 're and have / 've.
     Ambiguous 's and 'd remain reviewable.
   - Short/common words: replace words only when BOTH are at most two letters;
     insert/delete such words or the closed set {and, the}. Never alter negation.
   Check whole words, not changed character fragments. These rules may combine
   within one card, but every part must qualify. Preserve speaker/Q/A labels,
   native fields/symbols, numbers, hard spaces, indentation and paragraph breaks.
   Other wording and spacing stays pending. test_automatic_suggestions covers
   examples, whole-word guards, native application, idempotence and undo.
8. Original off-record notes authorize discussion suppression only with unique
   approximate departure/return matches and subsequent corroborating testimony.
   Excluded text is audited and restored by Undo. Ambiguous intervals stay pending.
"""
from collections import Counter
from dataclasses import replace
from difflib import SequenceMatcher
import re

from app.src.casecat.fields import field_values


LABEL = re.compile(r'^(?P<prefix>[ \t]*(?:BY[ \t]+)?)(?P<name>SPEAKER\s+\d+|(?:MS|MR|MRS|DR)\. [^:\n]+|THE [^:\n]+):', re.I)
GENERIC = re.compile(r'SPEAKER\s+(\d+)', re.I)

PUNCTUATION = frozenset(',;:.?!-\u2013\u2014')
COMMON_WORDS = frozenset({'and', 'the'})
WORD = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)*|\d+|[^\s]")
CONTRACTION = re.compile(r"\b(i)['\u2019]m\b|\b(you|we|they)['\u2019]re\b|\b(i|you|we|they)['\u2019]ve\b", re.I)


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
    return [m[0] for m in WORD.finditer(text)
            if 'punctuation' in disabled_rules or m[0] not in PUNCTUATION]


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
        prefix = LABEL.match(line) or re.match(r'^[ \t]*[QA][ \t]+', line)
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
    before_words, after_words = _words(left[a:b], disabled_rules), _words(right[c:d], disabled_rules)
    aa = [word.casefold() for word in before_words]
    bb = [word.casefold() for word in after_words]
    # Numeric and unsupported punctuation tokens must match exactly, including
    # their punctuation. Do not turn decimal/date changes into cosmetic edits.
    if any(ch.isdigit() for ch in left[a:b]+right[c:d]) and left[a:b] != right[c:d]:
        return None
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


def auto_accept(state, *, disabled_rules=frozenset()):
    """Apply one undoable native batch once per AI result, keeping an audit log."""
    from copy import deepcopy
    from app.src.suggestions import suggestions, resolve
    if (state.review or {}).get('automatic_filter') == 1:
        return []
    review = deepcopy(state.review) if state.review else {
        'version': 1, 'evidence': {'speakers': {}, 'occurrences': []}, 'overrides': {}, 'locations': []}
    original, incoming = state.original, state.incoming
    candidates = [(change, reason) for change in suggestions(original, incoming)
                  if (reason := automatic_reason(change, disabled_rules=disabled_rules))]
    records = list(reversed(review.get('off_record_changes', [])))
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
    review.update(automatic_filter=1, automatic_changes=list(reversed(records)))
    state.original, state.incoming, state.review = original, incoming, review
    return review['automatic_changes']


def _paragraphs(text, *, byline_context=True):
    result, offset = [], 0
    parts = text.split('\n')
    for index, line in enumerate(parts):
        label = LABEL.match(line)
        body = line[label.end():].strip() if label else re.sub(r'^[ \t]*[QA](?:[ \t]+|$)', '', line).strip()
        if byline_context and label and not body and 'BY' in label['prefix'].upper():
            body = next((re.sub(r'^\s*[QA]\s+', '', p).strip() for p in parts[index+1:] if p.strip()), '')
        result.append((offset, line, label, body.casefold()))
        offset += len(line) + 1
    return result


def aligned_paragraphs(original, incoming):
    from app.src.suggestions import _paragraph_ops
    old, new = _paragraphs(original), _paragraphs(incoming)
    # Borrowed byline wording is evidence for speaker attribution only. Using
    # it as another content anchor duplicates the following question.
    left = [p[3] for p in _paragraphs(original, byline_context=False)]
    right = [p[3] for p in _paragraphs(incoming, byline_context=False)]
    pairs = []
    for _, a, b, c, d in _paragraph_ops(left, right):
        if b-a == d-c:
            pairs.extend(zip(range(a, b), range(c, d)))
    return old, new, pairs


def _field_names(original):
    candidates = {}
    for name, value in field_values(original).items():
        if value:
            candidates.setdefault(value.strip().casefold(), []).append(name)
    return candidates


def _restore_trailing(original, text):
    from app.src.suggestions import text_edits

    old, new, pairs = aligned_paragraphs(original.text, text)
    edits = []
    for i, j in pairs:
        a, b = old[i][1], new[j][1]
        before = re.search(r'[ \t]*$', a)[0]
        after = re.search(r'[ \t]*$', b)[0]
        if len(before) > len(after) and before.startswith(after) and b.strip():
            edits.append((new[j][0]+len(b)-len(after), new[j][0]+len(b), before))
    for a, b, value in reversed(edits):
        text = text[:a] + value + text[b:]
    # A split or join can leave a shared paragraph ending without a
    # one-to-one paragraph match. Restore deletions at those endings too.
    source = original.text
    for a, b, c, d in reversed(text_edits(source, text)):
        if (c == d and not source[a:b].strip(' \t')
                and source[b:b+1] == text[c:c+1] and text[c:c+1] in ('', '\n')
                and text[text.rfind('\n', 0, c)+1:c].strip()):
            text = text[:c] + source[a:b] + text[c:]
    return text


def prepare(original, text, *, evidence=None, overrides=None):
    """Return a structured proposal and JSON-safe, frozen speaker evidence."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    old, new, pairs = aligned_paragraphs(original.text, text)
    fields = _field_names(original)
    if evidence is None:
        counts, occurrences = {}, []
        old_counts = Counter(p[3] for p in old if p[2])
        new_counts = Counter(p[3] for p in new if p[2])
        paired = {j: i for i, j in pairs}
        for j, (offset, line, label, body) in enumerate(new):
            if not label or not GENERIC.fullmatch(label['name']):
                continue
            speaker = 'SPEAKER ' + str(int(GENERIC.fullmatch(label['name'])[1]))
            counts.setdefault(speaker, Counter())
            source = old[paired[j]] if j in paired else None
            name = None
            if (source and source[2] and body and source[3]
                    and old_counts[source[3]] == new_counts[body] == 1
                    and SequenceMatcher(None, source[3], body, autojunk=False).ratio() >= .5):
                name = source[2]['name'].strip()
                counts[speaker][name] += 1
            occurrences.append({'id': len(occurrences), 'speaker': speaker,
                                'original_name': name, 'start': offset+label.start('name'),
                                'end': offset+label.end('name')})
        summaries = {}
        for speaker, votes in counts.items():
            ranked = sorted(votes, key=lambda name: (-votes[name], name))
            leader = ranked[0] if ranked else None
            winner = leader if leader and votes[leader] >= 2 and votes[leader] > sum(votes.values())/2 else None
            if winner and len(fields.get(winner.casefold(), [])) != 1:
                winner = None
            summaries[speaker] = {'counts': dict(votes), 'mapped': winner, 'leader': leader,
                                  'unresolved': sum(o['speaker'] == speaker and o['original_name'] is None for o in occurrences)}
        evidence = {'speakers': summaries, 'occurrences': occurrences}
    mappings = {key: value['mapped'] for key, value in evidence['speakers'].items()}
    mappings.update(overrides or {})
    edits = []
    for offset, line, label, body in new:
        if label and GENERIC.fullmatch(label['name']):
            speaker = 'SPEAKER ' + str(int(GENERIC.fullmatch(label['name'])[1]))
            name = mappings.get(speaker)
            if name:
                if len(fields.get(name.casefold(), [])) != 1:
                    raise ValueError('Choose a name with one existing native field.')
                edits.append((offset+label.start('name'), offset+label.end('name'), name))
    for a, b, name in reversed(edits):
        text = text[:a] + name + text[b:]
    text = _restore_trailing(original, text)
    # Do not let whole-text revision treat attribution changes as global renames.
    attribution_paragraphs = [old[i] for i, j in pairs if new[j][2] and (
        GENERIC.fullmatch(new[j][2]['name']) or (new[j][2]['name'].strip().casefold() in fields
        and old[i][2] and old[i][2]['name'] != new[j][2]['name']))]
    if evidence['occurrences']:
        # Unpaired paragraphs can move across token alignment blocks too.
        # No speaker occurrence may be interpreted as a global definition edit
        # while resolving generic AI labels.
        attribution_paragraphs = old
    speaker_elements = {e for e in original.elements if e.kind == 'field' and any(
        p[2] and p[0]+p[2].start('name') == e.start and p[0]+p[2].end('name') == e.end for p in attribution_paragraphs)}
    base = replace(original, elements=tuple(e for e in original.elements if e not in speaker_elements))
    from app.src.suggestions import propose
    revision = propose(base, text)
    _, projected, projected_pairs = aligned_paragraphs(original.text, revision.text)
    aligned_sources = {j: old[i] for i,j in projected_pairs}
    for paragraph_index in reversed(range(len(projected))):
        offset, line, label, body = projected[paragraph_index]
        if label and not GENERIC.fullmatch(label['name']):
            names = fields.get(label['name'].strip().casefold(), [])
            if len(names) == 1:
                a, b = offset+label.start('name'), offset+label.end('name')
                if any(e.kind == 'field' and e.start == a and e.end == b for e in revision.elements):
                    continue
                revision = revision._replace(a, b, '').insert_field(a, names[0], field_values(original)[names[0]])
                candidates = [e for e in original.elements if e.kind == 'field' and e.name == names[0]]
                source = aligned_sources.get(paragraph_index)
                exact = next((e for e in candidates if source and source[2] and e.start == source[0]+source[2].start('name')), None)
                template = exact or (candidates[0] if candidates else None)
                if template:
                    revision = replace(revision, elements=tuple(
                        replace(e, raw=template.raw, source=template.source) if e.kind == 'field' and e.start == a else e
                        for e in revision.elements))
    return revision, evidence


def begin_review(state, text, *, exclude_off_record=True):
    """Freeze evidence and return an optional pre-exclusion undo snapshot."""
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
            begin_review(raw, text, exclude_off_record=False)
            raw.review.update(automatic_filter=1, automatic_changes=[])
            undo = (state.original, raw.incoming, raw.review)
            text = filtered
    incoming, evidence = prepare(state.original, text)
    if (incoming.text == state.original.text and incoming.elements == state.original.elements
            and incoming.definitions == state.original.definitions):
        incoming = state.original
    # Normalization changes label lengths, not paragraph order.
    raw_paragraphs = _paragraphs(text)
    new_paragraphs = _paragraphs(incoming.text)
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
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError('Invalid speaker review evidence.') from exc


def track_decision(review, change, before_text, after_text):
    if review is None:
        return
    edits = sorted((c, d, b-a) for a,b,c,d in change.ranges) if before_text != after_text else []

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
        if any(c < b and d > a for _, _, c, d in change.ranges):
            location['resolved'] = True
        location.update(start=mapped(a), end=mapped(b, end=True))


def override_speaker(state, speaker, name):
    """Change pending attributions without replaying completed decisions."""
    if state.review is None or speaker not in state.review['evidence']['speakers']:
        raise ValueError('This speaker result is no longer available.')
    fields = _field_names(state.original)
    if name is not None and len(fields.get(name.casefold(), [])) != 1:
        raise ValueError('Choose a name with one existing native field.')
    revision = state.incoming
    locations = state.review['locations']
    for loc in sorted((p for p in locations if p['speaker'] == speaker and not p['resolved']), key=lambda p:p['start'], reverse=True):
        a, b = loc['start'], loc['end']
        value = name or speaker
        revised = revision._replace(a, b, '')
        if name:
            field = fields[name.casefold()][0]
            revised = revised.insert_field(a, field, field_values(state.original)[field])
        else:
            revised = revised._replace(a, a, value)
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
