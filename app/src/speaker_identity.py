"""Job-wide speaker identities, settled before the speaker review.

The stitcher gives every voice a job-wide label (Speaker 1, Speaker 2, ...). A voice
that did not speak in the minute a chunk shares with the previous chunk gets a new,
provisional label. It may be a participant returning from an earlier chunk, such
as an attorney who was silent during the overlap, or a new one. Gemini numbers the
voices afresh in every chunk, so its number alone says nothing.

link_voices compares the clearest clips of each provisional voice with the clearest
clip of every voice heard before it, in one Gemini audio request. When both of its
clips match the same earlier voice, its words take that label. Otherwise the label
stays and is unresolved: the review shows it once, as one voice. A voice is never
given a label because that label is the only one not heard again.

verify_members checks which turns of an unresolved voice are really that voice. A
shared Gemini number is not enough to group turns: Gemini can give an unrelated
voice, such as the reporter's, the same number. Turns that match the identifying
clip are linked and can be assigned together; any other turn is asked separately.
"""
from dataclasses import replace
import re

from app.src.audio_pipeline import FIRST, PROVISIONAL

LINKED, UNRESOLVED = 'linked', 'unresolved'
SAME, DIFFERENT, UNCERTAIN, UNCHECKED = 'same', 'different', 'uncertain', 'unchecked'
VERIFY_LIMIT = 96   # turns of one voice checked against its identifying clip
VERIFY_BATCH = 12   # candidate excerpts per Gemini request
LONG_TURN = 12      # words: an unchecked turn this long keeps Gemini's grouping
_SENTENCE_END = re.compile(r'[.?!]["”’)]*$')


def turns(words):
    """(label, first word index, end index) for each run of one speaker label."""
    found = []
    for i, word in enumerate(words):
        if found and found[-1][0] == word.speaker:
            found[-1][2] = i + 1
        else:
            found.append([word.speaker, i, i + 1])
    return [tuple(t) for t in found]


def _timed(words, first, end):
    return words[first].start is not None and words[end - 1].end is not None


def _text(words, first, end):
    return ' '.join(w.text for w in words[first:end])


def _excerpt(words, first, end, **extra):
    return {'start': words[first].start, 'end': words[end - 1].end, 'text': _text(words, first, end),
            'first': first, 'last': end, **extra}


def _clips(words, label):
    """Scored clips of one voice: up to three whole sentences of one turn, clear of other voices."""
    spans = turns(words)
    for k, (owner, first, end) in enumerate(spans):
        if owner != label:
            continue
        before = words[spans[k - 1][2] - 1].end if k and words[spans[k - 1][2] - 1].end is not None else None
        after = words[spans[k + 1][1]].start if k + 1 < len(spans) else None
        bounds, start = [], first
        for i in range(first, end):
            if _SENTENCE_END.search(words[i].text) or i == end - 1:
                bounds.append((start, i + 1))
                start = i + 1
        for a in range(len(bounds)):
            for b in range(a, min(a + 3, len(bounds))):
                s, e = bounds[a][0], bounds[b][1]
                if e - s < 3 or not _timed(words, s, e):
                    continue
                t0, t1 = words[s].start, words[e - 1].end
                if not 0 < t1 - t0 <= 15:
                    continue
                full = bool(_SENTENCE_END.search(words[e - 1].text))
                clear = (before is None or before <= t0 - .3) and (after is None or after >= t1 + .3)
                yield (clear, full, min(e - s, 25), -abs(t1 - t0 - 6)), s, e


def identifying_clips(words, label, count=1):
    """The clearest clips of a voice, preferably full sentences from different turns."""
    chosen = []
    for _, first, end in sorted(_clips(words, label), key=lambda c: c[0], reverse=True):
        if any(abs(words[first].start - words[c[0]].start) < 30 for c in chosen):
            continue
        chosen.append((first, end))
        if len(chosen) == count:
            break
    return [_excerpt(words, first, end, label=label) for first, end in chosen]


def link_voices(words, identities, compare, *, progress=lambda message: None, log=None):
    """Link provisional voices to earlier ones by their voice. Returns (words, identities, notes).

    `compare(question)` is a speaker_audio.VoiceComparison or None. Every provisional
    voice that does not match an earlier one clearly becomes unresolved.
    """
    words, notes = list(words), []
    identities = {label: dict(info) for label, info in (identities or {}).items()}
    first_seen = {}
    for i, word in enumerate(words):
        first_seen.setdefault(word.speaker, i)
    pending = sorted((label for label, info in identities.items()
                      if info.get('status') == PROVISIONAL and label in first_seen), key=first_seen.get)
    if pending and compare is not None:
        progress('Comparing voices that a later chunk numbered afresh...')
    for label in pending:
        info = identities[label]
        targets = identifying_clips(words, label, 2)
        references = []
        for other in sorted(first_seen, key=first_seen.get):
            if other is None or other == label or first_seen[other] >= first_seen[label]:
                continue
            if identities.get(other, {}).get('status') == LINKED:
                continue
            references.extend(identifying_clips(words, other, 1))
        answer, error = None, None
        if compare is not None and targets and references:
            question = {'references': [{k: r[k] for k in ('label', 'start', 'end', 'text')} for r in references],
                        'candidates': [{'id': f'C{n}', 'start': t['start'], 'end': t['end'], 'text': t['text']}
                                       for n, t in enumerate(targets, 1)]}
            try:
                answer = compare(question)
            except Exception as exc:  # noqa: BLE001 - the voice stays unresolved
                error = str(exc) or type(exc).__name__
            if log is not None:
                log({'kind': 'voices', 'label': label, 'question': question, 'answer': answer, 'error': error})
        heard = {(answer or {}).get('matches', {}).get(f'C{n}', UNCERTAIN) for n in range(1, len(targets) + 1)}
        match = heard.pop() if len(heard) == 1 else None
        if match in {r['label'] for r in references}:
            words = [replace(w, speaker=match) if w.speaker == label else w for w in words]
            why = (answer or {}).get('why', '')
            info.update(status=LINKED, to=match,
                        evidence=f'its voice matched {match}' + (f' ({why.rstrip(".")})' if why else ''))
            notes.append(f'{label} was chunk {info.get("chunk")}\'s number for {match}: the voice check matched '
                         'them, so its turns now carry that label.')
            continue
        info.update(status=UNRESOLVED, heard='none' if match == 'none' else UNCERTAIN,
                    clip=({k: targets[0][k] for k in ('start', 'end', 'text')} if targets else None))
        reason = ('the voice check could not run' if compare is None or error else
                  'it had no clear clip to compare' if not targets or not references else
                  'its voice matched no earlier speaker' if match == 'none' else
                  'the voice check was uncertain')
        info['evidence'] = (info.get('evidence') or '') + ('; ' if info.get('evidence') else '') + reason
        notes.append(f'{label} is a voice first heard in chunk {info.get("chunk")} that was not matched to an '
                     f'earlier speaker ({reason}). Do not give its turns to a participant only because that '
                     'participant has not spoken in that part of the deposition.')
    return tuple(words), identities, notes


def verify_members(words, label, clip, compare, *, limit=VERIFY_LIMIT, batch=VERIFY_BATCH,
                   progress=lambda message: None, log=None):
    """{first word index of each turn of `label`: same, different, uncertain or unchecked}.

    The turn holding the identifying clip is the voice itself. Short turns are the
    most likely to be someone else's, so they are checked first.
    """
    spans = [(first, end) for owner, first, end in turns(words) if owner == label]
    verdicts = {}
    own = next((first for first, end in spans if clip and first <= clip['first'] < end), None)
    if own is not None:
        verdicts[own] = SAME
    others = sorted((s for s in spans if s[0] != own), key=lambda s: (s[1] - s[0], s[0]))
    checked = [s for s in others if _timed(words, *s)][:limit]
    for first, end in others:
        verdicts.setdefault(first, UNCHECKED if (first, end) not in checked else UNCERTAIN)
    if compare is None or clip is None or not checked:
        return verdicts
    progress(f'Checking which turns of {label} share one voice...')
    reference = {'label': label, 'start': clip['start'], 'end': clip['end'], 'text': clip['text']}
    for n in range(0, len(checked), batch):
        part = checked[n:n + batch]
        question = {'references': [reference],
                    'candidates': [{'id': str(first), 'start': words[first].start, 'end': words[end - 1].end,
                                    'text': _text(words, first, end)} for first, end in part]}
        try:
            answer = compare(question)
        except Exception:  # noqa: BLE001 - unchecked turns stay separate
            answer = None
        if log is not None:
            log({'kind': 'members', 'label': label, 'question': question, 'answer': answer})
        matches = (answer or {}).get('matches', {})
        for first, _ in part:
            found = matches.get(str(first), UNCERTAIN)
            verdicts[first] = SAME if found == label else DIFFERENT if found == 'none' else UNCERTAIN
    return verdicts


def linked(verdict, size):
    """Whether a turn joins its voice's group: it matched, or it is long and was not checked."""
    return verdict == SAME or (verdict == UNCHECKED and size >= LONG_TURN)


__all__ = ['FIRST', 'LINKED', 'PROVISIONAL', 'UNRESOLVED', 'identifying_clips', 'link_voices', 'linked',
           'turns', 'verify_members']
