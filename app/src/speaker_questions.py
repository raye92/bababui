"""The speaker decisions a reporter still has to make, from a job's review state.

Who spoke is settled before the review wherever the evidence allows: the stitcher
keeps job-wide labels across chunks, the voice check links a voice that a later
chunk numbered afresh, the speaker review reads the exchange, the audio recheck
settles conflicts, and aligned labels in the rough name each label. What is left
is one question per uncertain identity:

- A voice: an unresolved speaker label with several turns. Only turns that the
  voice check linked to its identifying clip are grouped, so one decision can
  assign them all. A shared Gemini number alone never groups turns.
- A turn: one uncertain attribution, such as an "Okay." the audio recheck could
  not attribute, or a turn of an unresolved voice that did not match its clip.

Resolved speakers are listed separately, so they can stay collapsed.
"""
from collections import Counter
from dataclasses import dataclass

from shared.speaker_review import label_key, unit_audio

VOICE, TURN = 'voice', 'turn'
# A voice with more turns than this is established by Gemini's grouping of its
# many turns; a voice with fewer has its turns checked against its clearest clip.
MINOR_TURNS = 24


@dataclass(frozen=True)
class Question:
    key: str                  # stable within one review state
    kind: str                 # VOICE or TURN
    speaker: str              # the draft's label, such as SPEAKER 7
    locations: tuple          # location ids that "Assign all" changes
    current: int | None       # location id of the identifying turn, if it has one
    label: tuple              # (start, end) of the identifying turn's label in the draft
    text: str                 # the identifying clip, or the turn's words
    time: float | None        # where the identifying clip starts in the WAV, in seconds
    end: float | None
    suggestion: str | None    # the participant the evidence points to, if any
    why: str = ''

    @property
    def turns(self):
        return max(1, len(self.locations))


def _mappings(review):
    summaries = review.get('evidence', {}).get('speakers', {})
    overrides = review.get('overrides', {})
    return {speaker: overrides.get(speaker, summary.get('mapped')) for speaker, summary in summaries.items()}


def _units(review, text):
    record = review.get('speaker_review')
    return {u[0]: u for u in unit_audio(record, text)} if record else {}


def _paragraph(text, start):
    end = text.find('\n', start)
    line = text[start:end if end >= 0 else len(text)]
    return line.split(':', 1)[1].strip() if ':' in line else line.strip()


def _suggest(review, speaker, mappings):
    summary = review.get('evidence', {}).get('speakers', {}).get(speaker, {})
    leader = summary.get('leader')
    return leader if leader and summary.get('counts', {}).get(leader) else mappings.get(speaker)


def questions(review, text):
    """(questions, resolved speakers) for a review state and the draft text it describes."""
    review = review or {}
    mappings = _mappings(review)
    record = review.get('speaker_review') or {}
    units = _units(review, text)
    pending = [p for p in review.get('locations', ()) if not p['resolved'] and p['start'] < p['end']]
    by_speaker = {}
    for location in pending:
        by_speaker.setdefault(location['speaker'], []).append(location)
    voices = {label_key(v['label']): v for v in record.get('voices', ())}
    asked, claimed = [], set()
    for speaker, locations in by_speaker.items():
        if mappings.get(speaker):
            continue
        suggestion = _suggest(review, speaker, mappings)
        voice = voices.get(speaker)
        info = record.get('labels', {}).get(speaker)
        linked, loose = [], []
        established = info and info.get('status') == 'first chunk' and info.get('turns', 0) > MINOR_TURNS
        legacy = bool(record) and 'labels' not in record or not record
        if not voice and (established or legacy):
            # One voice throughout the job, or a review saved before voices were checked.
            voice = {'clip': None, 'evidence': (
                f'Gemini grouped {info["turns"]} turns of this voice.' if established else
                "Grouped by Gemini's speaker number only. Process the job again to check the voice.")}
            linked = list(locations)
        elif voice:
            mine = Counter()
            for turn in voice.get('turns', ()):
                for i in range(*turn['tokens']):
                    mine[i] = 1 if turn['linked'] else -1
            for location in locations:
                unit = units.get(location['start'])
                if unit is None:
                    # A BY line names the examiner; it has no words of its own to check.
                    linked.append(location)
                    continue
                score = sum(mine.get(i, 0) for i in unit[3])
                (linked if score > 0 else loose).append(location)
        else:
            loose = list(locations)
        if len(linked) > 1 or (linked and voice and voice.get('clip')):
            clip = voice.get('clip') or {}
            tokens = set(range(*clip['tokens'])) if clip.get('tokens') else set()
            current = next((p for p in linked if tokens & set(units.get(p['start'], (0, 0, '', ()))[3])),
                           next((p for p in linked if p['start'] in units), linked[0]))
            unit = units.get(current['start'])
            asked.append(Question(
                f'voice:{speaker}', VOICE, speaker, tuple(p['id'] for p in linked), current['id'],
                (current['start'], current['end']), clip.get('text') or _paragraph(text, current['start']),
                clip.get('start', unit[4] if unit else None), clip.get('end', unit[5] if unit else None),
                suggestion, voice.get('evidence', '')))
        else:
            loose.extend(linked)
        for location in sorted(loose, key=lambda p: p['start']):
            unit = units.get(location['start'])
            asked.append(Question(f'turn:{location["id"]}', TURN, speaker, (location['id'],), location['id'],
                                  (location['start'], location['end']), _paragraph(text, location['start']),
                                  unit[4] if unit else None, unit[5] if unit else None, suggestion,
                                  'Not linked to the voice of the other turns.' if voice else ''))
        claimed.update(p['start'] for p in locations)
    # Turns the speaker review could not attribute after the audio recheck.
    answered = set(review.get('answered', ()))
    for flag in record.get('flags', ()):
        if 'tokens' not in flag or f'flag:{flag["tokens"][0]}' in answered:
            continue
        tokens = set(range(*flag['tokens']))
        unit = max(units.values(), key=lambda u: len(tokens & set(u[3])), default=None)
        if unit is None or not tokens & set(unit[3]) or unit[0] in claimed:
            continue
        claimed.add(unit[0])
        location = next((p for p in pending if p['start'] == unit[0]), None)
        options = [label_key(flag.get('proposed') or ''), label_key(flag.get('speaker') or ''),
                   *map(label_key, flag.get('candidates', ()))]
        suggestion = next((mappings.get(o) for o in options if o and mappings.get(o)), None)
        asked.append(Question(f'flag:{flag["tokens"][0]}', TURN, location['speaker'] if location else '',
                              (location['id'],) if location else (), location['id'] if location else None,
                              (unit[0], unit[1]), flag.get('text', ''), flag.get('time'), flag.get('end'),
                              suggestion, flag.get('note', '')))
    asked.sort(key=lambda q: (q.label[0], q.kind != VOICE))
    resolved = {speaker: name for speaker, name in mappings.items() if name}
    return asked, resolved


def location_times(review, text, location_ids=(), label=None):
    """(start, end) in the WAV of the turns at these speaker label locations, or at one
    label span, from the speaker review record. Turns without times are skipped."""
    units = _units(review or {}, text)
    starts = [p['start'] for p in (review or {}).get('locations', ()) if p.get('id') in set(location_ids)]
    if label is not None and not starts:
        starts = [label[0]]
    return [(units[s][4], units[s][5] + .5) for s in starts if s in units and units[s][4] is not None]


def reapply(state, assignments, assign):
    """Apply the reporter's earlier speaker assignments to a new review of the same job.

    Each assignment is kept with the WAV times of the turns it covered. A turn of
    the new review takes that name only when its audio overlaps those times and no
    other assignment claims it, so a changed Gemini number can never carry a name
    to a different person. `assign(name, location ids, spans, answered keys)` applies one name.
    Returns how many turns were assigned again.
    """
    if not assignments or not state.review:
        return 0
    text = state.incoming.text
    asked, _ = questions(state.review, text)
    units = _units(state.review, text)
    starts = {p['id']: p['start'] for p in state.review.get('locations', ())}
    plan = {}
    for question in asked:
        targets = [(i, units.get(starts.get(i))) for i in question.locations] or [(None, units.get(question.label[0]))]
        for location, unit in targets:
            if unit is None or unit[4] is None:
                continue
            t0, t1 = unit[4], unit[5] + .5
            names = {a['name'] for a in assignments for s, e in a.get('times', ())
                     if min(t1, e) - max(t0, s) > .5 * min(t1 - t0 or .5, e - s or .5)}
            if len(names) == 1:
                ids, spans, keys = plan.setdefault(names.pop(), ([], [], []))
                if location is not None:
                    ids.append(location)
                else:
                    spans.append(question.label)
                    keys.append(question.key)
    for name, (ids, spans, keys) in plan.items():
        assign(name, ids, spans, keys)
    return sum(len(ids) + len(spans) for ids, spans, _ in plan.values())
