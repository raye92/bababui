"""Confirmed notice fields and values supplied by the recording job."""
from dataclasses import asdict, dataclass, fields, replace
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
import re
from xml.etree import ElementTree

from app.src.casecat.fields import field_values


@dataclass(frozen=True)
class Appearance:
    side: str = ''
    firm: str = ''
    attorney: str = ''
    title: str = ''
    address: str = ''
    suite: str = ''
    city: str = ''
    state: str = ''
    zip_code: str = ''
    phone: str = ''
    email: str = ''


_ORGANIZATION_WORDS = frozenset(
    'inc llc llp corp corporation co company companies insurance ltd group services district county city state '
    'department hospital center centre university association associates bank trust authority fund mutual '
    'casualty indemnity partners clinic medical health systems school college agency board'.split())


def _party_kind(name):
    """An applicant is usually a person; an employer or insurer is an organization."""
    words = re.findall(r"[^\W_]+", name.casefold())
    return 'person' if 1 < len(words) <= 4 and not _ORGANIZATION_WORDS.intersection(words) else 'organization'


@dataclass(frozen=True)
class NoticeDetails:
    plaintiff: str = ''
    defendant: str = ''
    deponent: str = ''
    case_numbers: tuple[str, ...] = ()
    file_number: str = ''
    taking_side: str = ''
    time: str = ''
    weekday: str = ''
    date: str = ''
    appearances: tuple[Appearance, ...] = ()
    speakers: tuple[str, ...] = ()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        try:
            data = dict(data)
            appearances = tuple(Appearance(**row) if isinstance(row, dict) else row
                                for row in data.get('appearances', ()))
            if any(not isinstance(row, Appearance) or row.side not in ('Applicant', 'Defendant')
                   or any(not isinstance(x, str) for x in vars(row).values()) for row in appearances):
                raise ValueError('Invalid notice appearance.')
            data['appearances'] = appearances
            for key in ('case_numbers', 'speakers'):
                items = data.get(key, ())
                if not isinstance(items, (list, tuple)) or any(not isinstance(x, str) for x in items):
                    raise ValueError('Invalid notice fields.')
                data[key] = tuple(items)
            result = cls(**data)
            if any(not isinstance(getattr(result, f.name), str) for f in fields(cls)
                   if f.name not in ('appearances', 'case_numbers', 'speakers')):
                raise ValueError('Invalid notice text.')
            if result.taking_side not in ('', 'Applicant', 'Defendant'):
                raise ValueError('Invalid noticing side.')
            return result
        except (TypeError, KeyError) as exc:
            raise ValueError('Invalid notice details.') from exc

    def vocabulary(self):
        return tuple(dict.fromkeys(name for _, name in self._named()))

    def spelling_sources(self):
        """Confirmed spellings, each a ('person' or 'organization', name) pair."""
        found = {}
        for kind, name in self._named():
            found.setdefault(name.casefold(), (kind, name))
        return tuple(found.values())

    def _named(self):
        names = [('person', self.deponent)]
        for row in self.appearances:
            names.extend((('person', row.attorney), ('organization', row.firm)))
        attorney_words = {w.casefold() for row in self.appearances for w in re.findall(r"[\w’'-]+", row.attorney)}
        for label in self.speakers:
            name = re.sub(r'^(?:BY\s+)?(?:(?:MR|MRS|MS|MISS|DR)\.?\s+)?', '', label.strip(), flags=re.I)
            if not name or re.fullmatch(r'(?:SPEAKER|ATTORNEY|COUNSEL)(?:\s*\d+)?', name, re.I):
                continue
            # A short EZ speaker label often repeats a full attorney name, with
            # an older spelling. Keep the confirmed full form in that case.
            if len(name.split()) == 1 and any(SequenceMatcher(None, name.casefold(), w).ratio() >= .8
                                              for w in attorney_words):
                continue
            names.append(('person', name))
        for party in (self.plaintiff, self.defendant):
            entities = re.split(r'\s*[,;]?\s*\b(?:as\s+)?(?:insured|administered|adjusted)\s+by\s+|[;/]', party, flags=re.I)
            for entity in entities:
                # A second insurer can follow a corporate suffix without a
                # semicolon, e.g. “Blue Mill, Inc., Plains Insurance Company”.
                entity = re.sub(r'\b(Inc\.?|Corp\.?|LLC|Ltd\.?),\s+(?=\w)', r'\1;', entity, flags=re.I)
                names.extend((_party_kind(part), part) for part in entity.split(';'))
        terms = {}
        for kind, name in names:
            term = ' '.join(name.split()).strip(' ,;')
            if term and not term.startswith('[!'):
                terms.setdefault(term.casefold(), (kind, term))
        return list(terms.values())

    def speaker_context(self):
        """Confirmed participants and parties, for reviewing who speaks each turn."""
        lines = []
        sentence = lambda text: text if text.endswith('.') else text + '.'
        if self.deponent:
            lines.append(sentence(f'Witness (deponent): {self.deponent}'))
        for row in self.appearances:
            if row.attorney or row.firm:
                lines.append(sentence(f'{row.side} attorney: ' + ', '.join(x for x in (row.attorney, row.firm) if x)))
        if self.taking_side:
            lines.append(f'Deposition noticed by the {self.taking_side.lower()} side.')
        for role, party in (('Plaintiff or applicant', self.plaintiff), ('Defendant', self.defendant)):
            if party:
                lines.append(sentence(f'{role}: {party}'))
        return '\n'.join(lines)

    def with_current_names(self, revision):
        values = field_values(revision)
        appearances = sorted(self.appearances, key=lambda row: row.side != 'Applicant')
        return replace(self, plaintiff=values.get('PLAINTIFF', self.plaintiff),
                       defendant=values.get('DEFENDANT', self.defendant),
                       deponent=values.get('DEPONENT', self.deponent),
                       appearances=tuple(replace(row, attorney=values.get(f'ATTORNEY{i}', row.attorney),
                                                 firm=values.get(f'FIRM{i}', row.firm))
                                         for i, row in enumerate(appearances, 1)),
                       speakers=tuple(values.get(f'EZ SPEAKER {i:02}', name)
                                      for i, name in enumerate(self.speakers, 1)))


def filename_file_number(filename):
    stem = Path(filename).stem
    match = re.search(r'(?:^|[\s_-])([a-zA-Z]*\d+)$', stem)
    if not match or match[1].upper().startswith('ADJ'):
        return ''
    # A standalone date is the recording identifier in this filename convention.
    if match.start(1) == 0 and re.fullmatch(r'\d{6}|\d{8}', stem):
        return ''
    return match[1]


def recording_details(bundle, job, revision=None):
    values = field_values(revision or job.baseline)
    member = bundle.member(job.key + '.sgxml')
    metadata = ({node.tag: node.get('sgpref-val', '') for node in ElementTree.fromstring(bundle.read(member)).iter()}
                if member else {})
    date = values.get('CREATION DATE IN WORDS', '').replace('\x01', ' ')
    weekday = values.get('CREATION DAY OF WEEK', '')
    for fmt, value in (('%m/%d/%Y', values.get('CREATION DATE', '')),
                       ('%B %d, %Y', date), ('%Y-%d-%m', metadata.get('Date-Taken', '').split('T')[0])):
        try:
            day = datetime.strptime(value, fmt)
        except ValueError:
            continue
        weekday = weekday or day.strftime('%A')
        date = date or f'{day:%B} {day.day}, {day.year}'
        break
    time = ''
    if len(job.notes_bytes) >= 648:
        minutes = int.from_bytes(job.notes_bytes[644:648], 'little') // 6000
        hour, minute = divmod(minutes % 1440, 60)
        time = f'{hour % 12 or 12}:{minute:02d} ' + ('p.m.' if hour >= 12 else 'a.m.')
    speakers = tuple(values.get(f'EZ SPEAKER {i:02d}') or metadata.get(f'Speaker-{i}', '') for i in (1, 2, 3))
    return NoticeDetails(time=time, weekday=weekday, date=date, speakers=speakers if speakers[2] else speakers[:2])
