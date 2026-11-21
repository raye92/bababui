"""Grade the speaker attribution and turn-boundary review against hand-graded cases.

The review runs on Gemini's stitched transcript before Q/A and colloquy
formatting, using shared/speaker_review.py, the same code the editor runs. It
sees Gemini's words and any case context, never the reporter's steno rough, so
every decision is measured against Gemini's original labels.

Four results are graded separately for every case:

- Speaker identity: who speaks each part of every turn, including parts that
  must keep Gemini's label.
- Split points: the exact word where a turn changes speaker, checked for every
  turn, including turns that need no split.
- Review status: whether each turn is unchanged, corrected, or flagged for
  review, and that each flag carries its audio time.
- Highlight placement: which speaker labels in the draft are yellow. Only a
  corrected label is yellow, and only on the part that was reassigned. Q/A
  conversion of a correctly attributed label gets no highlight.

A case gives Gemini's turns, the case context, the expected formatted draft
and the phrases that must be flagged. The expected speaker of every word comes
from the expected draft: Q is the examiner on the BY line in effect, A is the
witness, and colloquy is its label.
"""
import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from shared.speaker_review import (CORRECTED, FLAGGED, UNREVIEWED, align, clock, gemini_turns, label_highlights,
                                   label_key, label_units, review_speakers, word_tokens, SpeakerReview)

AREAS = ('identity', 'splits', 'status', 'highlights')
AREA_TITLES = {'identity': 'Speaker identity', 'splits': 'Split points', 'status': 'Review status',
               'highlights': 'Highlight placement'}
STATUS_TITLES = {'unchanged': 'unchanged', CORRECTED: 'corrected', FLAGGED: 'flagged for review',
                 UNREVIEWED: 'not reviewed'}
SECONDS_PER_WORD = 0.4
LINE = re.compile(r'^\s*(?:\[(?P<time>\d+:\d{2}(?::\d{2})?(?:\.\d+)?)\]\s*)?(?P<label>speaker\s*\d+|unknown speaker)\s*:\s?(?P<body>.*)$', re.I)


def seconds(text):
    value = 0.0
    for part in text.split(':'):
        value = value * 60 + float(part)
    return value


def parse_words(asr):
    """Gemini's stitched words from `Speaker N: text` lines. A line may start with its
    audio time, such as `[0:29:10]`; other words are timed 0.4 seconds apart."""
    words, clock_ = [], 0.0
    for line in asr.replace('\r\n', '\n').split('\n'):
        if not line.strip():
            continue
        match = LINE.match(line)
        if not match:
            raise ValueError(f'Expected a "Speaker N: text" line, not: {line.strip()[:60]}')
        if match['time']:
            clock_ = seconds(match['time'])
        label = None if match['label'].casefold() == 'unknown speaker' else f'Speaker {int(re.sub(r"\D", "", match["label"]))}'
        for text in match['body'].split():
            words.append(SimpleNamespace(text=text, speaker=label, start=round(clock_, 2),
                                         end=round(clock_ + SECONDS_PER_WORD - .1, 2)))
            clock_ += SECONDS_PER_WORD
    return tuple(words)


@dataclass
class Failure:
    area: str
    kind: str
    turn: int
    where: str
    expected: str
    actual: str
    detail: str = ''
    clue: str = ''


@dataclass
class Case:
    id: str
    title: str
    context: str
    notes: list
    witness: str
    words: tuple
    expected_text: str
    flags: list = field(default_factory=list)       # expected flagged word spans
    clues: list = field(default_factory=list)       # (word span, clue)

    @classmethod
    def load(cls, record):
        words = parse_words(record['asr'])
        case = cls(record['id'], record.get('title', record['id']), record.get('context', ''),
                   list(record.get('notes', [])), label_key(record['witness']), words, record['expected'])
        case.flags = [case.locate(f['asr'], f.get('nth', 1)) for f in record.get('flags', [])]
        case.clues = [(case.locate(c['asr'], c.get('nth', 1)), c['clue']) for c in record.get('clues', [])]
        case._expect()
        return case

    def locate(self, phrase, nth=1):
        """Word span of the nth occurrence of a phrase in Gemini's words."""
        wanted = word_tokens(phrase)
        tokens = [(t, i, k == 0) for i, w in enumerate(self.words) for k, t in enumerate(word_tokens(w.text))]
        found = 0
        for j in range(len(tokens) - len(wanted) + 1):
            if tokens[j][2] and [t for t, _, _ in tokens[j:j + len(wanted)]] == wanted:
                found += 1
                if found == nth:
                    return tokens[j][1], tokens[j + len(wanted) - 1][1] + 1
        raise ValueError(f'{self.id}: "{phrase}" (occurrence {nth}) is not in the Gemini transcript.')

    def gemini(self, i):
        return label_key(self.words[i].speaker)

    # Expected decisions, derived from the expected draft and the flagged phrases.
    def _expect(self):
        self.turns = gemini_turns(self.words)
        self.tokens, self.owner = [], []
        for i, word in enumerate(self.words):
            found = word_tokens(word.text)
            self.tokens.extend(found)
            self.owner.extend([i] * len(found))
        speakers = draft_speakers(self, self.expected_text)
        flagged = {i for a, b in self.flags for i in range(a, b)}
        for i in flagged:
            if speakers[i] not in (None, self.gemini(i)):
                raise ValueError(f'{self.id}: a flagged turn keeps Gemini\'s label in the expected draft, '
                                 f'but "{self.words[i].text}" is under {speakers[i]}.')
        self.expected_speaker = speakers
        self.expected_flagged = flagged
        self.expected_segments = {t.id: _runs(t, speakers, self.flags) for t in self.turns}

    def expected_status(self, turn):
        words = range(turn.start, turn.end)
        if any(i in self.expected_flagged for i in words):
            return FLAGGED
        if any(self.expected_speaker[i] not in (None, self.gemini(i)) for i in words):
            return CORRECTED
        return 'unchanged'

    def expected_record(self):
        """The highlight record a correct review would produce."""
        corrected, start = [], None
        for k, i in enumerate(self.owner):
            changed = (i not in self.expected_flagged and self.expected_speaker[i] is not None
                       and self.expected_speaker[i] != self.gemini(i))
            if changed and start is None:
                start = k
            elif not changed and start is not None:
                corrected.append([start, k])
                start = None
        if start is not None:
            corrected.append([start, len(self.owner)])
        return {'version': 1, 'tokens': self.tokens, 'corrected': corrected}

    def where(self, i):
        i = min(i, len(self.words) - 1)
        word = self.words[i]
        end = next(t.end for t in self.turns if t.start <= i < t.end)
        text = ' '.join(w.text for w in self.words[i:min(end, i + 6)]) + (' ...' if end > i + 6 else '')
        return (f'[{clock(word.start)}] ' if word.start is not None else '') + f'“{text}”'

    def clue(self, a, b):
        return next((c for (x, y), c in self.clues if x < b and a < y), '')


def draft_units(case, text):
    """Label units of a draft and, for each Gemini word, the unit holding most of its words."""
    units = label_units(text)
    flat, owners = [], []
    for k, unit in enumerate(units):
        flat.extend(unit.tokens)
        owners.extend([k] * len(unit.tokens))
    votes = [dict() for _ in case.words]
    for t, j in enumerate(align(case.tokens, flat)):
        if j is not None:
            votes[case.owner[t]][owners[j]] = votes[case.owner[t]].get(owners[j], 0) + 1
    return units, [max(v, key=v.get) if v else None for v in votes]


def unit_speaker(case, unit):
    if unit.kind == 'q':
        return unit.examiner
    if unit.kind == 'a':
        return case.witness
    return label_key(unit.label)


def draft_speakers(case, text):
    units, word_units = draft_units(case, text)
    return [None if k is None else unit_speaker(case, units[k]) for k in word_units]


def _runs(turn, speakers, flags):
    """Word positions where the turn changes speaker, or where a flagged part begins or ends."""
    def key(i):
        flag = next((n for n, (a, b) in enumerate(flags) if a <= i < b), None)
        return ('flag', flag) if flag is not None else (speakers[i], None) if speakers[i] else None
    keys, previous = [], None
    for i in range(turn.start, turn.end):
        k = key(i)
        if k is None:
            k = previous  # a word the draft dropped belongs with the words before it
        keys.append(k)
        previous = k
    if keys and keys[0] is None:
        first = next((k for k in keys if k is not None), None)
        keys = [first if k is None else k for k in keys]
    return {turn.start + n for n in range(1, len(keys)) if keys[n] != keys[n - 1]}


def actual_status(review, turn):
    statuses = {s.status for s in review.segments if s.turn == turn.id}
    for status in (FLAGGED, CORRECTED, UNREVIEWED):
        if status in statuses:
            return status
    return 'unchanged'


def grade(case, review, draft=None):
    """Grade one speaker review. `draft` is the formatted draft for highlight placement;
    without it, the resolved turns sent to the formatter are graded."""
    draft = review.text if draft is None else draft
    failures, evaluated = [], dict.fromkeys(AREAS, 0)

    def add(area, kind, a, b, expected, actual, detail=''):
        turn = next(t.id for t in case.turns if t.start <= a < t.end)
        failures.append(Failure(area, kind, turn, case.where(a), expected, actual, detail, case.clue(a, b)))

    # Speaker identity: each expected part of each turn, including unchanged parts.
    for turn in case.turns:
        bounds = sorted({turn.start, *case.expected_segments[turn.id], turn.end})
        for a, b in zip(bounds, bounds[1:]):
            words = [i for i in range(a, b) if case.expected_speaker[i] is not None]
            if not words:
                continue
            evaluated['identity'] += 1
            want = _majority([case.expected_speaker[i] for i in words])
            wrong = [i for i in words if review.speaker_of(i) != case.expected_speaker[i]]
            if not wrong:
                continue
            got = _majority([review.speaker_of(i) for i in wrong])
            gemini = case.gemini(wrong[0])
            if want != gemini and got == gemini:
                kind, detail = 'missed', "kept Gemini's label"
            elif wrong[0] in case.expected_flagged:
                kind, detail = 'incorrect', 'named one participant where the exchange establishes only a role'
            elif want == gemini:
                kind, detail = 'incorrect', 'relabeled a part that Gemini had right'
            else:
                kind, detail = 'incorrect', 'relabeled to the wrong participant'
            add('identity', kind, wrong[0], wrong[-1] + 1, want or 'none',
                f'{got or "none"} for {len(wrong)} of {len(words)} words', detail)

    # Split points: every turn, including turns that need no split.
    for turn in case.turns:
        evaluated['splits'] += 1
        want = set(case.expected_segments[turn.id])
        got = {s.start for s in review.segments if s.turn == turn.id and s.split}
        missing, extra = sorted(want - got), sorted(got - want)
        for i in missing:
            near = min(extra, key=lambda j: abs(j - i), default=None)
            if near is not None:
                extra.remove(near)
                offset = near - i
                add('splits', 'wrong_word', min(i, near), max(i, near) + 1, f'split before “{case.words[i].text}”',
                    f'split before “{case.words[near].text}”',
                    f'{abs(offset)} word{"s" if abs(offset) != 1 else ""} {"late" if offset > 0 else "early"}')
            else:
                add('splits', 'missed', i, i + 1, f'split before “{case.words[i].text}”', 'no split',
                    'kept two speakers in one turn')
        for j in extra:
            add('splits', 'incorrect', j, j + 1, 'no split', f'split before “{case.words[j].text}”',
                'split a turn that has one speaker there')

    # Review status: every turn, and an audio time on every flag.
    timed = any(w.start is not None for w in case.words)
    for turn in case.turns:
        evaluated['status'] += 1
        want, got = case.expected_status(turn), actual_status(review, turn)
        if want != got:
            kind = 'missed' if want != 'unchanged' and got in ('unchanged', UNREVIEWED) else 'incorrect'
            add('status', kind, turn.start, turn.end, STATUS_TITLES[want], STATUS_TITLES[got])
        for segment in review.segments:
            if segment.turn == turn.id and segment.status == FLAGGED and timed and segment.time is None:
                add('status', 'incorrect', segment.start, segment.end, 'flag with its audio time',
                    'flag without an audio time')

    # Highlight placement: the label of every expected speech paragraph.
    expected_units, expected_owner = draft_units(case, case.expected_text)
    expected_yellow = set(label_highlights(case.expected_record(), case.expected_text))
    actual_units, actual_owner = draft_units(case, draft)
    actual_yellow = set(label_highlights(review.record(), draft))
    for k, unit in enumerate(expected_units):
        words = [i for i, owner in enumerate(expected_owner) if owner == k]
        if not words:
            continue
        evaluated['highlights'] += 1
        want = (unit.label_start, unit.label_end) in expected_yellow
        target = _majority([actual_owner[i] for i in words if actual_owner[i] is not None])
        got = target is not None and (actual_units[target].label_start, actual_units[target].label_end) in actual_yellow
        if want != got:
            label = actual_units[target].label if target is not None else 'no label'
            add('highlights', 'missed' if want else 'incorrect', words[0], words[-1] + 1,
                f'yellow {unit.label} label' if want else f'no highlight on the {unit.label} label',
                f'yellow {label} label' if got else f'no highlight on the {label} label')
    counts = {area: {'evaluated': evaluated[area], 'failures': sum(f.area == area for f in failures)}
              for area in AREAS}
    return {'case': case.id, 'title': case.title, 'counts': counts, 'failures': failures, 'summary': review.summary}


def _majority(values):
    values = [v for v in values if v is not None]
    return max(set(values), key=values.count) if values else None


def load_cases(folder):
    folder = Path(folder)
    paths = sorted(folder.glob('*.json')) if folder.is_dir() else [folder]
    return [Case.load(json.loads(path.read_text(encoding='utf-8'))) for path in paths]


def run_case(case, complete, *, formatter=None):
    """Run the live review on a case. `formatter(text)` optionally formats the resolved turns."""
    review = review_speakers(case.words, complete, context=case.context, notes=case.notes)
    draft = formatter(review.text) if formatter else None
    return review, draft


def model_complete(model, env_root):
    """A completion function for a processing model, using that folder's .env keys."""
    from shared.client import DeepSeekClient, load_config
    config = load_config(env_root)
    if model.startswith('deepseek-'):
        client = DeepSeekClient({**config, 'model': model, 'max_tokens': 65536, 'timeout_seconds': 1800})

        def complete(text, prompt):
            output = client.complete(text, prompt)
            if client.finish_reason != 'stop':
                raise ValueError('The response did not complete.')
            return output
        return complete
    if not config.get('gemini_api_key'):
        raise ValueError(f'Set GEMINI_API_KEY in {Path(env_root) / ".env"}.')
    from google import genai
    sdk = genai.Client(api_key=config['gemini_api_key'],
                       http_options={'timeout': 1800000, 'retry_options': {'attempts': 1}})

    def complete(text, prompt):
        response = sdk.interactions.create(model=model, input=text, system_instruction=prompt, store=False,
                                           automatic_continuation=False,
                                           generation_config={'max_output_tokens': 65536}, timeout=1800)
        if getattr(response.status, 'value', response.status) != 'completed':
            raise ValueError('The response did not complete.')
        return response.output_text
    return complete


def report(results):
    lines = []
    totals = {area: [0, 0] for area in AREAS}
    for result in results:
        lines.append(f'{result["case"]}: {result["title"]}')
        lines.append(f'  {result["summary"]}')
        for area in AREAS:
            count = result['counts'][area]
            totals[area][0] += count['evaluated']
            totals[area][1] += count['failures']
            lines.append(f'  {AREA_TITLES[area]}: {count["evaluated"] - count["failures"]} of {count["evaluated"]} correct')
        for f in result['failures']:
            lines.append(f'    {AREA_TITLES[f.area]}, turn {f.turn} {f.where}: expected {f.expected}; got {f.actual}'
                         + (f' ({f.detail})' if f.detail else ''))
            if f.clue:
                lines.append(f'      Clue: {f.clue}')
    lines.append('Totals')
    for area in AREAS:
        done, failed = totals[area]
        lines.append(f'  {AREA_TITLES[area]}: {done - failed} of {done} correct')
    return '\n'.join(lines)


def results_json(results):
    return [{**{k: v for k, v in r.items() if k != 'failures'},
             'failures': [vars(f) for f in r['failures']]} for r in results]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Grade the speaker attribution and turn-boundary review.')
    parser.add_argument('cases', nargs='?', default=str(Path(__file__).with_name('speaker_review_cases')))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--model', help='Run the live review with this model, such as gemini-4-argon (paid).')
    source.add_argument('--saved', help='Grade saved results: <case id>.review.json and optional <case id>.draft.txt.')
    parser.add_argument('--format-prompt', help='Also format the reviewed turns with this prompt file.')
    parser.add_argument('--format-model', help='Model for formatting. Defaults to --model.')
    parser.add_argument('--env-dir', default=str(Path(__file__).parent), help='Folder whose .env holds the API keys.')
    parser.add_argument('--save', help='Save each run as <case id>.review.json and <case id>.draft.txt here.')
    parser.add_argument('--json', help='Write the results as JSON.')
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    results = []
    if args.model:
        complete = model_complete(args.model, args.env_dir)
        formatter = None
        if args.format_prompt:
            prompt = Path(args.format_prompt).read_text(encoding='utf-8')
            format_complete = model_complete(args.format_model or args.model, args.env_dir)
            formatter = lambda text: format_complete(text, prompt)
        for case in cases:
            review, draft = run_case(case, complete, formatter=formatter)
            if args.save:
                folder = Path(args.save)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f'{case.id}.review.json').write_text(json.dumps(review.to_json(), ensure_ascii=False, indent=2),
                                                               encoding='utf-8')
                if draft is not None:
                    (folder / f'{case.id}.draft.txt').write_text(draft, encoding='utf-8')
            results.append(grade(case, review, draft))
    else:
        folder = Path(args.saved)
        for case in cases:
            path = folder / f'{case.id}.review.json'
            if not path.exists():
                print(f'{case.id}: no saved review, skipped.', file=sys.stderr)
                continue
            review = SpeakerReview.from_json(case.words, json.loads(path.read_text(encoding='utf-8')))
            draft_path = folder / f'{case.id}.draft.txt'
            draft = draft_path.read_text(encoding='utf-8') if draft_path.exists() else None
            results.append(grade(case, review, draft))
    print(report(results))
    if args.json:
        Path(args.json).write_text(json.dumps(results_json(results), ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
