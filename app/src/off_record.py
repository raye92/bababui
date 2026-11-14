"""Conservative, offset-preserving matching around original off-record notes.

Comparison tokens never replace testimony. Only a unique pair of boundaries,
with a following substantive match, authorizes suppressing captured discussion.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re


NOTE = re.compile(r'^\s*\(a discussion was held off the record\s*\.?\)\s*$', re.I)
TOKEN = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*", re.UNICODE)


@dataclass(frozen=True)
class Token:
    word: str
    start: int
    end: int
    paragraph: int


def _tokens(text):
    from app.src.suggestion_filter import LABEL
    result, offset = [], 0
    for line in text.splitlines(keepends=True):
        label = LABEL.match(line) or re.match(r'^[ \t]*[QA][ \t]+', line)
        body = label.end() if label else 0
        if not NOTE.fullmatch(line):
            for match in TOKEN.finditer(line, body):
                word = match[0].casefold().replace('\u2019', "'")
                # Keep negation visible even when its apostrophe is omitted.
                words = ['can', 'not'] if word == 'cannot' else [word.replace("'", '')]
                if word.endswith(("n't", 'nt')) and words[0] in {
                        'dont', 'doesnt', 'didnt', 'isnt', 'wasnt', 'werent',
                        'arent', 'cant', 'couldnt', 'wouldnt', 'shouldnt',
                        'wont', 'hasnt', 'havent', 'hadnt', 'mustnt'}:
                    words = [words[0][:-2], 'not']
                for value in words:
                    result.append(Token(value, offset+match.start(), offset+match.end(), offset))
        offset += len(line)
    return result


def _protected(words):
    return [w for w in words if any(c.isdigit() for c in w) or w in {'no', 'not', 'never', 'neither', 'nor'}]


def _matches(query, tokens, *, boundary=False):
    """Find distinct near-matches, grouping overlapping windows at one location."""
    words = [t.word for t in query]
    if len(words) < 6 or len(set(words)) < 4:
        return []
    candidates = []
    slack = max(2, len(words)//4)
    paragraph_start = 0
    for i, token in enumerate(tokens):
        if i == 0 or token.paragraph != tokens[i-1].paragraph:
            paragraph_start = i
        if token.word not in words[:3]:
            continue
        if boundary and (i-paragraph_start > 3 or _protected([t.word for t in tokens[paragraph_start:i]])):
            continue
        for size in range(max(6, len(words)-slack), len(words)+slack+1):
            window = tokens[i:i+size]
            if len(window) != size:
                continue
            values = [t.word for t in window]
            if _protected(words) != _protected(values):
                continue
            matcher = SequenceMatcher(None, words, values, autojunk=False)
            score = matcher.ratio()
            if score >= .8 and sum(b.size for b in matcher.get_matching_blocks()) >= 6:
                candidates.append((score, i, i+size))
    # Sliding windows around one passage are one candidate, not ambiguity.
    result = []
    for candidate in sorted(candidates, reverse=True):
        _, a, b = candidate
        if not any(a < d and b > c for _, c, d in result):
            result.append(candidate)
    return result


def _unique(matches):
    # A later verbatim repetition must not outrank an earlier contracted return
    # and authorize deleting all the testimony between them.
    return matches[0] if len(matches) == 1 else None


def exclude_discussions(original, incoming):
    """Return filtered text and JSON-safe audit records; ambiguous spans stay put."""
    from app.src.suggestion_filter import LABEL
    lines = original.splitlines(keepends=True)
    if not any(NOTE.fullmatch(line) for line in lines):
        return incoming, []
    offsets, position = [], 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    source, target = _tokens(original), _tokens(incoming)
    edits, last_end = [], 0
    for index, line in enumerate(lines):
        if not NOTE.fullmatch(line):
            continue
        # The departure is the preceding substantive turn plus its short reply.
        before = index-1
        while before >= 0 and not lines[before].strip():
            before -= 1
        if before < 0:
            continue
        preceding = [t for t in source if t.paragraph == offsets[before]]
        if len(preceding) < 6 and before:
            before -= 1
        start = offsets[before]
        departure = [t for t in source if start <= t.start < offsets[index]][-24:]
        after = index+1
        while after < len(lines):
            label = LABEL.match(lines[after])
            if lines[after].strip() and not (label and not lines[after][label.end():].strip()):
                break
            after += 1
        if after == len(lines):
            continue
        end = offsets[after]
        following = [t for t in source if t.start >= end]
        # Prefer the first sentence, not the whole combined question paragraph.
        sentence = re.search(r'[.?!](?:\s|$)', lines[after])
        sentence_end = end+sentence.end() if sentence else end+len(lines[after])
        resume = [t for t in following if t.start < sentence_end][:24]
        rest = [t for t in following if t.start >= sentence_end]
        # Next long sentence/turn supplies independent corroboration.
        support = []
        for paragraph in dict.fromkeys(t.paragraph for t in rest):
            group = [t for t in rest if t.paragraph == paragraph]
            if len(group) >= 8:
                support = group[:16]
                break
        left = _unique(_matches(departure, target, boundary=True))
        right = _unique(_matches(resume, target, boundary=True))
        if not left or not right or not support or left[2] > right[1]:
            continue
        corroboration = _matches(support, target[right[2]:right[2]+64])
        if not _unique(corroboration):
            continue
        a, b = target[left[1]].paragraph, target[right[1]].paragraph
        # Never consume earlier testimony in the same paragraph as a match.
        # A few leading conversational words are allowed at either boundary.
        if any(sum(t.paragraph == target[i].paragraph for t in target[:i]) > 3
               for i in (left[1], right[1])):
            continue
        # Normalizing punctuation must not let us swallow an earlier complete
        # sentence in the same turn. Ignore the speaker label's abbreviation.
        separate_sentence = False
        for match_index in (left[1], right[1]):
            token = target[match_index]
            prefix = incoming[token.paragraph:token.start]
            label = LABEL.match(prefix) or re.match(r'^[ \t]*[QA][ \t]+', prefix)
            if re.search(r'[.?!]', prefix[label.end() if label else 0:]):
                separate_sentence = True
        if separate_sentence:
            continue
        if a < last_end or a >= b:
            continue
        retained = original[start:end]
        if incoming[a:b] == retained:
            last_end = b
            continue
        edits.append({'original_range': [start, end], 'incoming_range': [a, b],
                      'before': incoming[a:b], 'after': retained, 'rule': 'off-record discussion',
                      'evidence': {'departure': ' '.join(t.word for t in departure),
                                   'return': ' '.join(t.word for t in resume),
                                   'departure_score': left[0], 'return_score': right[0]}})
        last_end = b
    for edit in reversed(edits):
        a, b = edit['incoming_range']
        incoming = incoming[:a] + edit['after'] + incoming[b:]
    return incoming, edits
