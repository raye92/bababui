"""Q/A or colloquy from who spoke each turn and whom it addressed.

The formatter labels each turn by its speaker's role. Whom a turn addressed is
sometimes settled only later in the exchange:

     MR. SWEET:  What page are you on again, and what paragraph?
     THE WITNESS:  Are you asking me or counsel?  Sorry.
     MR. SWEET:  Counsel, I'm sorry.

The examiner's reply shows the first question was addressed to counsel, so all
three turns are colloquy, even though the question came during the examination.
Had the reply been "You, Doctor.", the question was addressed to the witness and
the three turns are Q, A and Q.

This pass reads the formatted draft as a whole after the formatter. For each turn
it knows who spoke, from the speaker labels the formatter was given. Where the
witness asks whom a question was for, it reads the examiner's reply and corrects
the labels that the reply contradicts:

- Addressed to counsel: the question, the witness's clarification and the reply
  are colloquy under their speakers' labels. While the examiner keeps addressing
  counsel, the exchange stays colloquy. The first examiner turn that clearly
  resumes questioning the witness becomes Q after a BY line. A turn resumes the
  questioning when it addresses the witness ("Doctor, ...") or when the witness
  answers it. A turn that opens with a remark to counsel and then addresses the
  witness is split where it turns to the witness.
- Addressed to the witness: the question is Q, the clarification is A, the reply
  is Q, and the witness's answer is A.

When the question came from an attorney who is not examining, a reply to counsel
makes the exchange colloquy in the same way, and that attorney's later turns stay
colloquy until the examiner resumes. A reply to the witness changes nothing, since
another attorney's question is not examination.

Only labels and BY lines change. Every spoken word stays, in order; a revision that
would change one is discarded.
"""
from collections import Counter
from dataclasses import dataclass, field
import re

from shared.speaker_review import align, label_key, word_tokens

WITNESS = 'THE WITNESS'

_BY = re.compile(r'^[ \t]*BY[ \t]+(?P<name>[^:\n]+?)[ \t]*:[ \t]*$')
_QA = re.compile(r'^[ \t]{0,8}(?P<label>[QA])[ \t]+(?P<body>\S.*)$')
_COLLOQUY = re.compile(r"^[ \t]*(?P<label>(?:SPEAKER|Speaker)[ \t]+\d+|UNKNOWN SPEAKER|THE [A-Z][A-Z .'-]*?"
                       r"|(?:MR|MS|MRS|MISS|DR)\. [^:\n]+?)(?:[ \t]+\[unconfirmed\])?:[ \t]*(?P<body>.*)$")
_HEADING = re.compile(r'^[ \t]*(?:FURTHER[ \t]+|CROSS-|REDIRECT[ \t]+|RECROSS-)?EXAMINATION[ \t]*$')
_PARENTHETICAL = re.compile(r'^[ \t]*\(.*\)[ \t]*$')
_NOTES = re.compile(r'^[ \t]*REVIEW NOTES[ \t]*:?[ \t]*$')
_REVIEW_TAG = re.compile(r'\[REVIEW[ \t]+\d+\]')
# A turn of the formatter's input: "Speaker 2: words" or "Speaker 2 [unconfirmed]: words".
_SOURCE = re.compile(r'^[ \t]*(?P<label>(?:SPEAKER|Speaker)[ \t]+\d+|UNKNOWN SPEAKER|Unknown speaker)'
                     r'(?:[ \t]+\[unconfirmed\])?:[ \t]?(?P<body>.*)$')

# The witness asks whom a question was for.
_CLARIFY = re.compile(
    r"\b(?:are|were)\s+you\s+(?:asking|talking\s+to|speaking\s+to|addressing)\s+me\s*(?:[?.!,]|$|or\b)"
    r"|\bwho\s+(?:are|were)\s+you\s+(?:asking|talking\s+to|speaking\s+to|addressing)\b"
    r"|\bwho(?:'s|’s|\s+is|\s+was)\s+(?:that|the\s+question)\s+(?:for|to)\b"
    r"|\b(?:is|was)\s+(?:that|this)(?:\s+question)?\s+(?:for|to|directed\s+(?:at|to))\s+me\b"
    r"|\bme\s+or\s+(?:counsel(?:or)?|your\s+(?:attorney|lawyer|counsel)|the\s+(?:attorney|lawyer)|him|her)\b", re.I)
_COUNSEL = r"counsel(?:or)?|opposing\s+counsel|your\s+(?:attorney|lawyer|counsel)|the\s+(?:attorney|lawyer)"
_WITNESS_WORDS = r"you|the\s+witness|the\s+doctor|doctor|dr\.?\s+[a-z'’-]+"
# "I'm asking counsel." "I was talking to you, Doctor."
_EXPLICIT = re.compile(rf"\b(?:asking|talking\s+to|speaking\s+to|addressing|meant|asked)\s+"
                       rf"(?P<whom>{_COUNSEL}|{_WITNESS_WORDS})\b", re.I)
_FILLER = r"(?:(?:yes|yeah|no|oh|sorry|actually|i'?m\s+sorry|i\s+apologize|my\s+apologies)\W+)*"
# The reply opens by naming whom it is for: "Counsel, I'm sorry." "You, Doctor."
_VOCATIVE = re.compile(rf"^\W*{_FILLER}(?:(?P<counsel>{_COUNSEL}|not\s+you)|(?P<witness>{_WITNESS_WORDS}|sir|ma'?am))\b",
                       re.I)
# A sentence of an examiner's turn that speaks to the witness: "Doctor, ..." or "Dr. Lee, ...".
_TO_WITNESS = re.compile(r"(?:^|(?<=[.?!])[ \t]+)(?P<word>Doctor|Dr\.[ \t]+[A-Z][\w'’-]*|Sir|Ma'?am|Witness)[,?]")
_COUNSEL_WORDS = re.compile(rf"(?:{_COUNSEL})", re.I)
# A turn that speaks to counsel: "Thank you, counsel." "Counsel, which page?"
_TO_COUNSEL = re.compile(r"(?:^|[,.?!][ \t]*)(?:counsel(?:or)?)[ \t]*(?:[,.?!]|$)", re.I)
_OBJECTION = re.compile(r"^\W*(?:objection|object\b|i\s+object\b)", re.I)


@dataclass
class Turn:
    line: int               # index of the turn's first line
    kind: str               # 'q', 'a' or 'colloquy'
    label: str              # Q, A, or the colloquy label as written
    body: str               # the first line's spoken words
    examiner: str | None    # the BY line in effect, as written
    after_by: int | None    # the BY line right before this turn
    tokens: list = field(default_factory=list)
    text: str = ''          # every line of the turn, as written
    speaker: str | None = None  # who spoke: a label key such as SPEAKER 2


def _parse(lines):
    """Labeled turns, and the lines that stop an exchange: headings, parentheticals and
    BY lines for another examiner."""
    turns, marks, examiner, by = [], {}, None, None
    for index, line in enumerate(lines):
        if _NOTES.match(line):
            marks[index] = 'end'
            break
        if not line.strip():
            continue
        if match := _BY.match(line):
            examiner, by = match['name'].strip(), index
            marks[index] = ('by', examiner)
            continue
        if _HEADING.match(line) or _PARENTHETICAL.match(line):
            marks[index] = 'stop'
            by = None
            continue
        match = _QA.match(line)
        kind = ('q' if match['label'] == 'Q' else 'a') if match else None
        if not match and (match := _COLLOQUY.match(line)):
            kind = 'colloquy'
        if match:
            turns.append(Turn(index, kind, match['label'], match['body'], examiner, by,
                              word_tokens(_REVIEW_TAG.sub(' ', match['body'])), match['body']))
        elif turns:
            turns[-1].tokens.extend(word_tokens(_REVIEW_TAG.sub(' ', line)))
            turns[-1].text += ' ' + line.strip()
        by = None
    return turns, marks


def _speakers(turns, source):
    """Who spoke each turn, by aligning its words to the formatter's labeled input."""
    labels, tokens, current = [], [], None
    for line in (source or '').split('\n'):
        if match := _SOURCE.match(line):
            current, line = label_key(match['label']), match['body']
        words = word_tokens(line)
        tokens.extend(words)
        labels.extend([current] * len(words))
    draft, owners = [], []
    for k, turn in enumerate(turns):
        draft.extend(turn.tokens)
        owners.extend([k] * len(turn.tokens))
    votes = [Counter() for _ in turns]
    if tokens:
        for j, i in enumerate(align(draft, tokens)):
            if i is not None and labels[i]:
                votes[owners[j]][labels[i]] += 1
    witness = Counter()
    for turn, vote in zip(turns, votes):
        if turn.kind == 'a':
            witness.update(vote)
    witness = witness.most_common(1)[0][0] if witness else WITNESS
    for turn, vote in zip(turns, votes):
        if vote:
            turn.speaker = vote.most_common(1)[0][0]
        elif turn.kind == 'q':
            turn.speaker = label_key(turn.examiner)
        elif turn.kind == 'a':
            turn.speaker = witness
        else:
            turn.speaker = label_key(turn.label)
    return witness


def addressed(reply):
    """'counsel', 'witness' or None: whom the examiner's reply to "Are you asking me or
    counsel?" names."""
    opening = ' '.join(re.split(r'(?<=[.?!])\s+', reply.strip())[:2])
    if match := _EXPLICIT.search(opening):
        return 'counsel' if _COUNSEL_WORDS.fullmatch(match['whom']) else 'witness'
    if match := _VOCATIVE.match(opening):
        return 'counsel' if match['counsel'] else 'witness'
    return None


def _clarifies(turn, witness):
    return turn.speaker == witness and _CLARIFY.search(turn.text) is not None


class _Plan:
    def __init__(self):
        self.kinds, self.splits, self.by, self.heads, self.drop, self.notes = {}, {}, {}, {}, set(), {}

    def relabel(self, turn, kind, why):
        if turn.kind != kind or turn.line in self.kinds:
            self.kinds[turn.line] = kind
            self.notes[turn.line] = why

    def resume(self, turn, where, why, opening=()):
        """BY line, and any examination heading moved down, before the examiner's Q: the
        whole turn, or its part from `where` on."""
        if turn.after_by is not None:
            self.drop.add(turn.after_by)
        self.drop.update(opening)
        self.heads[turn.line] = list(opening[:1])  # the heading; the BY line is written fresh
        self.by[turn.line] = turn.examiner
        if where:
            self.splits[turn.line] = where
            self.notes[turn.line] = why
        else:
            self.relabel(turn, 'q', why)


def revise(draft, source=None):
    """(revised draft, notes) for a formatted draft. `source` is the text the formatter
    was given, one "Speaker N: words" line per turn; it tells who spoke each turn. Each
    note gives a revised turn's opening words, its new label and why."""
    lines = draft.split('\n')
    turns, marks = _parse(lines)
    witness = _speakers(turns, source)
    plan = _Plan()
    for k, turn in enumerate(turns):
        if k == 0 or not _clarifies(turn, witness):
            continue
        # Who asked, and the asker's reply to the witness.
        question = turns[k - 1]
        asker = question.speaker
        if asker is None or asker == witness or question.line in plan.kinds:
            continue
        reply = next((t for t in turns[k + 1:k + 3] if t.speaker in (asker, witness)), None)
        if reply is None or reply.speaker != asker:
            continue
        examiner = label_key(question.examiner) if question.examiner else None
        said = ' '.join(reply.body.split())
        whom = addressed(said)
        if whom == 'counsel':
            _to_counsel(turns, marks, lines, k, reply, said, examiner, witness, plan)
        elif whom == 'witness' and asker == examiner:
            # A question another attorney puts to the witness is not examination (Section 9).
            _to_witness(turns, marks, k, reply, said, witness, plan)
    if not (plan.kinds or plan.splits):
        return draft, []
    revised, notes = _write(lines, turns, plan, witness)
    if _spoken(revised) != _spoken(draft):
        return draft, []
    return revised, notes


def _answer(turns, j, witness):
    """The witness's response to turn j: the next turn, past any objection."""
    for later in turns[j + 1:j + 3]:
        if later.speaker == witness:
            return None if _clarifies(later, witness) else later
        if not _OBJECTION.match(later.body):
            return None
    return None


def _to_counsel(turns, marks, lines, k, reply, said, examiner, witness, plan):
    question, clarifying = turns[k - 1], turns[k]
    asker = question.speaker
    who = 'examiner' if asker == examiner else 'attorney'
    plan.relabel(question, 'colloquy', f'The {who}\'s reply, “{said}”, shows this question was addressed to '
                                       'counsel. It is colloquy.')
    plan.relabel(clarifying, 'colloquy', 'The witness asked whom the question was for. That is colloquy, not an '
                                         'answer.')
    plan.relabel(reply, 'colloquy', f'The {who} answered the witness by addressing counsel. It is colloquy.')
    if examiner is None:
        return
    # A BY line is always followed by a Q. One that opened the examination moves down,
    # with its heading, to where the examiner turns to the witness.
    opening = ()
    if question.after_by is not None:
        above = next((i for i in range(question.after_by - 1, -1, -1) if lines[i].strip()), None)
        if above is not None and marks.get(above) == 'stop' and _HEADING.match(lines[above]):
            opening = (above, question.after_by)
        else:
            plan.drop.add(question.after_by)
    for turn in (clarifying, reply):
        if turn.after_by is not None:
            plan.drop.add(turn.after_by)
    resumed = 'The examiner turned from counsel to the witness here. It is Q.'
    index = turns.index(reply)
    match = _TO_WITNESS.search(reply.body)
    if asker == examiner and match and match.start('word'):
        plan.resume(reply, match.start('word'), resumed, opening)
        _answered(turns, index, witness, plan)
        return
    for j in range(index + 1, len(turns)):
        later = turns[j]
        # A heading, a parenthetical or another examiner's BY line ends the exchange.
        between = [marks[i] for i in range(turns[j - 1].line + 1, later.line) if i in marks]
        if any(m in ('stop', 'end') or label_key(m[1]) != examiner for m in between):
            return
        if later.speaker == witness:
            if _clarifies(later, witness):
                return
            plan.relabel(later, 'colloquy', 'The witness spoke during the exchange with counsel. It is colloquy.')
        elif later.speaker == asker != examiner:
            plan.relabel(later, 'colloquy', 'The attorney is not examining the witness. It is colloquy.')
        elif later.speaker == examiner:
            match = _TO_WITNESS.search(later.body)
            if match:
                where = match.start('word')
            elif _answer(turns, j, witness) is not None and not _TO_COUNSEL.search(later.body):
                where = 0
            else:
                plan.relabel(later, 'colloquy', 'The examiner was still addressing counsel. It is colloquy.')
                if later.after_by is not None:
                    plan.drop.add(later.after_by)
                continue
            plan.resume(later, where, resumed if where else 'The examiner resumed questioning the witness here. '
                                                             'It is Q.', opening)
            _answered(turns, j, witness, plan)
            return
        if later.after_by is not None:
            plan.drop.add(later.after_by)


def _answered(turns, j, witness, plan):
    if (answer := _answer(turns, j, witness)) is not None:
        plan.relabel(answer, 'a', 'The witness answered the resumed question. It is A.')


def _to_witness(turns, marks, k, reply, said, witness, plan):
    question, clarifying = turns[k - 1], turns[k]
    plan.relabel(question, 'q', f'The examiner\'s reply, “{said}”, shows this question was addressed to the '
                                'witness. It is Q.')
    plan.relabel(clarifying, 'a', 'The witness asked about the pending question. It is A.')
    plan.relabel(reply, 'q', 'The examiner answered the witness. It is Q.')
    for turn in (clarifying, reply):
        if turn.after_by is not None:
            plan.drop.add(turn.after_by)
    index = turns.index(reply)
    answer = _answer(turns, index, witness)
    if answer is not None:
        plan.relabel(answer, 'a', 'The witness answered the question. It is A.')
        # Q and A continue, so the examiner's next question needs no BY line.
        after = turns[turns.index(answer) + 1] if turns.index(answer) + 1 < len(turns) else None
        if (answer.kind != 'a' and after is not None and after.after_by is not None and after.kind == 'q'
                and label_key(after.examiner) == question.speaker):
            plan.drop.add(after.after_by)
    if question.kind != 'q' and question.after_by is None:
        before = turns[k - 2] if k > 1 else None
        stopped = before is None or any(i in marks for i in range(before.line + 1, question.line))
        if stopped or plan.kinds.get(before.line, before.kind) not in ('q', 'a'):
            plan.by[question.line] = question.examiner


def _write(lines, turns, plan, witness):
    # Each speaker's colloquy label, as the draft writes it.
    written = {}
    for turn in turns:
        if turn.kind == 'colloquy' and turn.speaker:
            written.setdefault(turn.speaker, Counter())[turn.label] += 1
    at = {t.line: t for t in turns}
    out, notes = [], []

    def label(turn, kind):
        if kind in ('q', 'a'):
            return kind.upper()
        if turn.kind == 'colloquy':
            return turn.label
        if turn.speaker in written:
            return written[turn.speaker].most_common(1)[0][0]
        if turn.kind == 'q' and turn.examiner and label_key(turn.examiner) == turn.speaker:
            return turn.examiner
        return turn.speaker or (turn.examiner if turn.kind == 'q' else WITNESS)

    def line_for(kind, name, body):
        return f'     {name}    {body}' if kind in ('q', 'a') else f'     {name}:  {body}'

    for index, line in enumerate(lines):
        if index in plan.drop:
            continue
        turn = at.get(index)
        if turn is None:
            out.append(line)
            continue
        if index in plan.splits:
            where = plan.splits[index]
            first, rest = turn.body[:where].rstrip(), turn.body[where:]
            name = label(turn, 'colloquy')
            out.append(line_for('colloquy', name, first))
            out += [lines[i] for i in plan.heads.get(index, ())]
            out += [f'BY {plan.by[index]}:', line_for('q', 'Q', rest)]
            notes.append({'text': first, 'label': name,
                          'why': 'The examiner was still addressing counsel. It is colloquy.'})
            notes.append({'text': rest, 'label': 'Q', 'why': plan.notes[index]})
            continue
        out += [lines[i] for i in plan.heads.get(index, ())]
        if index in plan.by:
            out.append(f'BY {plan.by[index]}:')
        kind = plan.kinds.get(index, turn.kind)
        if kind == turn.kind:
            out.append(line)
            continue
        name = label(turn, kind)
        out.append(line_for(kind, name, turn.body))
        notes.append({'text': turn.body, 'label': name, 'why': plan.notes[index]})
    return '\n'.join(out), notes


def _spoken(text):
    """The draft's spoken words, exactly, without labels, BY lines or headings."""
    words = []
    for line in text.split('\n'):
        if _NOTES.match(line):
            break
        if _BY.match(line) or _HEADING.match(line):
            continue
        if match := _QA.match(line) or _COLLOQUY.match(line):
            line = match['body']
        words.extend(line.split())
    return words


def summary(notes):
    count = len(notes)
    return f"Addressee check: {count} label{'s' if count != 1 else ''} revised."


def note_spans(notes, text):
    """(label start, label end, note) for each revised turn in a draft, found in order by
    its words. Labels may have been renamed since, so only the words are matched."""
    if not notes or not text:
        return ()
    found, offset, lines, k = [], 0, [], 0
    for line in text.split('\n'):
        lines.append((offset, line))
        offset += len(line) + 1
    for note in notes:
        wanted = ' '.join(str(note.get('text', '')).split())
        for n in range(k, len(lines)):
            start, line = lines[n]
            match = _QA.match(line) or _COLLOQUY.match(line)
            if match and ' '.join(match['body'].split()) == wanted:
                found.append((start, start + match.start('body'), note))
                k = n + 1
                break
    return tuple(found)
