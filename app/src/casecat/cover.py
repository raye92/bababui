"""Build the reporter's five-page notice cover in the selected native job."""
from functools import lru_cache
from pathlib import Path
import re
import struct
import textwrap

from .caption import BODY_DIVIDER, TABLE_END, TABLE_START, caption_value, cell, has_captions
from .codec import records, u32
from .field_table import field_record, field_texts, read_fields, replace_section, rewrite_fields
from .fields import update_speaker_xml
from .layout import index_positions, read_layouts
from .rendering import TextRenderer, render_record
from .structure import relocate, rendering_settings


BOARD = "WORKERS' COMPENSATION APPEALS BOARD"
RULE = '~' * 30
OATH = ('having been first duly sworn, was', 'examined and testified as follows:')
REPORTER = ('MR. REPORTER:  My name is Matthew Bui.  I am a California Certified Shorthand '
            'Reporter, CSR No. 14977.  Stating a license number will ensure parties know '
            'they have a licensed court reporter reporting and producing a transcript of the proceeding.')
DEPOSITION_DATE = 'CREATION DATE IN WORDS'
WEEKDAY = 'CREATION DAY OF WEEK'
APPEARANCE_FIELDS = (
    ('firm', 'FIRM'), ('attorney', 'ATTORNEY'), ('title', 'TITLE'), ('address', 'ADDRESS-A'),
    ('suite', 'SUITE'), ('city', 'CITY'), ('state', 'STATE'), ('zip_code', 'ZIP'),
    ('phone', 'PHONE NUMBER'), ('email', 'E-MAIL'))


def _p(style=8, text=b''):
    return b'\x16' + struct.pack('<H', style) + (text.encode('cp1252') if isinstance(text, str) else text)


def _text(text):
    if any(ord(char) < 32 for char in text):
        raise ValueError('A notice entry must be a single line.')
    try:
        return text.encode('cp1252')
    except UnicodeEncodeError as exc:
        raise ValueError('Notice entries must use Windows-1252 characters for Case CATalyst.') from exc


def _appearance_name(attribute, number):
    if attribute == 'SUITE' and number <= 2:
        return ('SUITE', 'SUITE NO')[number - 1]
    return f'{attribute}{number}'


def _appearance_rows(details, *, references):
    rows, values = [], {}
    people = sorted(details.appearances, key=lambda person: person.side != 'Applicant')
    for number, person in enumerate(people, 1):
        values[f'APPEARANCE SIDE {number}'] = person.side
        entries = {}
        for attr, prefix in APPEARANCE_FIELDS:
            name = _appearance_name(prefix, number)
            value = getattr(person, attr).strip()
            values[name] = value
            entries[attr] = (field_record(name) if references else _text(value)) if value else b''
        if rows:
            rows.append(b'')
        rows.extend((b'FOR THE APPLICANT:' if person.side == 'Applicant' else b'FOR THE DEFENDANTS:',
                     entries['firm'], b'(Zoom videoconference)'))
        attorney = b', '.join(x for x in (entries['attorney'], entries['title']) if x)
        city = b', '.join(x for x in (entries['city'], entries['state']) if x)
        city = b' '.join(x for x in (city, entries['zip_code']) if x)
        rows.extend(x for x in ((b'BY:  ' + attorney) if attorney else b'',
                               entries['address'], entries['suite'], city, entries['phone'], entries['email']) if x)
    return rows, values


def cover_overflow(details):
    problems = []
    wrapped = []
    for name, value in (('Plaintiff', details.plaintiff), ('Defendant', details.defendant)):
        lines = caption_value(name.upper(), value).count('\n') + 1
        wrapped.append(lines)
        if len(value) > 200 or lines > 9:
            problems.append(name)
    if sum(wrapped) > 12 and not problems:
        problems.extend(('Plaintiff', 'Defendant'))
    if len(details.case_numbers) > 18:
        problems.append('Case numbers (the caption fits 18 docket lines)')
    if any(len(value) > 16 for value in details.case_numbers):
        problems.append('Case number (use an accurate docket form of 16 characters or fewer)')
    if len(details.deponent.strip()) + 1 > 56:
        problems.append('Deponent')
    if len('FILE NO.:  ' + details.file_number) > 56:
        problems.append('File number')
    if len('California, commencing at ' + details.time + ', ' + details.weekday + ',') > 56:
        problems.append('Time and weekday')
    if len(details.date + ', before Matthew Bui, CSR No. 14977.') > 56:
        problems.append('Date')
    problems.extend(f'EZ SPEAKER {i:02}' for i, value in enumerate(details.speakers, 1) if len(value) > 42)
    rows, _ = _appearance_rows(details, references=False)
    if (len(details.appearances) > 3 or any(len(value) > 200 for person in details.appearances
                                           for value in vars(person).values())
            or sum(max(1, len(textwrap.wrap(row.decode('cp1252'), 50))) for row in rows) > 42):
        problems.append('Appearances')
    return tuple(problems)


@lru_cache(maxsize=1)
def _stock_layout():
    return (Path(__file__).parents[2] / 'assets' / 'notice_cover_layout.bin').read_bytes()


def _supply_styles(native):
    layouts = read_layouts(native)
    if layouts and all(len(layout.paragraphs) >= 9 for layout in layouts):
        return native
    stock = _stock_layout()
    if not layouts:
        data = stock
    else:
        parts = []
        for layout in layouts:
            count = len(layout.paragraphs)
            if count >= 9:
                parts.append(layout.raw)
                continue
            end = 1024 + 512 * count
            raw = bytearray(layout.raw)
            raw[end:end] = stock[end:1024 + 9 * 512]
            struct.pack_into('<I', raw, 4, 9)
            parts.append(bytes(raw))
        data = b''.join(parts)
    result = bytearray(replace_section(native, 540, data))
    struct.pack_into('<I', result, 624, len(layouts) or 1)
    return bytes(result)


def _caption(details, left, right):
    numbers = details.case_numbers or ('',)
    longest = max(map(len, numbers))
    label = b'CASE NO.:' + b' ' * min(2, max(0, 16 - longest))
    column = min(34, max(31, 56 - len(label) - longest))
    split = left + round((right - left) * column / 57)
    plaintiff, defendant = field_record('PLAINTIFF'), field_record('DEFENDANT')
    # Ordinary fields and CATalyst cell bounds keep the two columns independent.
    # The half-line returns reproduce the caption's single-spaced continuations.
    left_cell = (b'\x12\x09' + plaintiff + b',' + _p(9) + _p(9, '               Applicant,') +
                 _p(9) + _p(9, b'          \x12\x8evs.') + _p(9) + _p(9, defendant + b',') +
                 _p(9) + _p(9, '               Defendants.') + _p(9, RULE))
    right_cell = label + _text(numbers[0])
    for number in numbers[1:]:
        right_cell += _p(9, b' ' * len(label) + _text(number))
    header = (_p(7, BOARD) + _p(7, 'STATE OF CALIFORNIA') + _p() + TABLE_START +
              cell(left, split) + left_cell + cell(split, right) + right_cell + TABLE_END + b'\x12\x89')
    rows = 8 + sum(caption_value(name, value).count('\n') + 1 for name, value in
                   (('PLAINTIFF', details.plaintiff), ('DEFENDANT', details.defendant)))
    return header, max(rows, len(numbers))


def _cover_pages(details, layout, pages, index_footer):
    caption, caption_rows = _caption(details, layout.paragraphs[7].left, layout.paragraphs[7].right)
    deponent, date = field_record('DEPONENT'), field_record(DEPOSITION_DATE)
    # The first two sheets have the same heading and caption. Allow additional
    # names to consume blank space before the centered title and recital.
    gap = _p(9) * max(1, 19 - caption_rows)
    page1 = (caption + gap + _p(7, 'DEPOSITION OF') + _p(7, deponent) +
             _p(7, '(PARTICIPANTS REMOTE), CALIFORNIA') + _p(7, b'\x12\x08' + date + b'\x12\x88') +
             _p() * 3 + _p(8, 'REPORTED BY:  Matthew Bui, CSR NO. 14977') +
             _p(8, b'FILE NO.:  ' + _text(details.file_number)))
    party = {'Applicant': 'Applicant', 'Defendant': 'Defendants'}.get(details.taking_side, '')
    page2 = (caption + gap + _p(8, b'          Deposition of ' + deponent + b', taken on') +
             _p() + _p(8, b'\x12\x8ebehalf of the ' + _text(party) + b', at (PARTICIPANTS REMOTE),') +
             _p() + _p(8, b'California, commencing at ' + _text(details.time) + b', ' + field_record(WEEKDAY) + b',') +
             _p() + _p(8, date + b', before Matthew Bui, CSR No. 14977.'))
    appearance_rows, values = _appearance_rows(details, references=True)
    plain_rows, _ = _appearance_rows(details, references=False)
    count = sum(max(1, len(textwrap.wrap(row.decode('cp1252'), 51))) for row in plain_rows)
    spacing = 8 if count <= 22 else 9
    page3 = _p(7, 'A P P E A R A N C E S:') + _p()
    for row in appearance_rows:
        prefix = b'' if not row or row.startswith(b'FOR THE ') else b'     '
        page3 += _p(spacing, prefix + b'\x12\x8e' + row)
    single = any(raw in (b'\x09', b'\x0a') for _, raw in records(index_footer, 0, len(index_footer)))
    istyle = 9 if single else 8
    page4 = (_p(7, (b'\x12\x09' if single else b'') + b'I N D E X') + _p(istyle) +
             _p(istyle, b'WITNESS:  ' + deponent) + _p(istyle) +
             _p(istyle, 'EXAMINATION                                         PAGE'))
    for index in range(max(2, len(details.speakers))):
        name = f'EZ SPEAKER {index + 1:02}'
        value = details.speakers[index] if index < len(details.speakers) else ''
        manual = pages[index] if index < len(pages) else ''
        if manual and not re.fullmatch(r'[\d ,\-\u2013]+', manual):
            raise ValueError('An index page entry must contain page numbers.')
        label = b'     BY ' + field_record(name)
        pad = max(2, 52 - 8 - len(value or f'[!{name}]'))
        page4 += _p(istyle, label + b' ' * pad + _text(manual))
    page4 += _p(istyle) + (index_footer or
              (_p(7, 'E X H I B I T S') + _p(8, '  NUMBER            DESCRIPTION                     PAGE') +
               _p(7, '(NONE)') + _p() + _p(7, 'INSTRUCTIONS NOT TO ANSWER:') + _p(7, 'PAGE             LINE') +
               _p(7, '(NONE)') + _p() + _p(7, 'INFORMATION REQUESTED:') + _p(7, 'PAGE             LINE') +
               _p(7, '(NONE)')))
    if single and not page4.endswith(b'\x12\x89'):
        page4 += b'\x12\x89'
    page5 = (_p(7, deponent + b',') + _p(8, b'               \x12\x8e' + _text(OATH[0])) +
             _p(8, b'               \x12\x8e' + _text(OATH[1])) + _p() +
             _p(8, b'          ' + _text(REPORTER)) + BODY_DIVIDER)
    values.update(PLAINTIFF=details.plaintiff, DEFENDANT=details.defendant, DEPONENT=details.deponent)
    values.update({WEEKDAY: details.weekday, DEPOSITION_DATE: details.date})
    values.update({f'EZ SPEAKER {i:02}': name for i, name in enumerate(details.speakers, 1)})
    return b'\x0c'.join((page1, page2, page3, page4, page5)), values


def _body_offset(job):
    """Find the reporter's final layout control, even inside a stroke group."""
    text = job.baseline.text
    if BOARD not in text[:100]:
        return 0
    if BOARD not in text[100:4500] or 'I N D E X' not in text[:12000]:
        return 0
    start, size = struct.unpack_from('<II', job.native_bytes, 532)
    end = start + size
    reporter = job.native_bytes.find(b'Stating a license number', start, min(end, start + 25000))
    if reporter >= 0:
        divider = job.native_bytes.find(BODY_DIVIDER, reporter, min(end, reporter + 1300))
        if divider >= 0:
            return divider + len(BODY_DIVIDER) - start
    raise ValueError('The existing cover has no recognizable end after the reporter declaration.')


def _project_prefix(native, cut, speakers, all_caps):
    """Return the old/new logical body position and formatted cover lines."""
    if not cut:
        return 0, ''
    renderer = TextRenderer(all_caps=all_caps, cover_tables=has_captions(native))
    start, size = struct.unpack_from('<II', native, 532)
    text, pos = [], 0
    for offset, raw in records(native, start, start + size):
        if offset >= start + cut:
            renderer.cover_tables = False
        word = render_record(renderer, raw, speakers)
        if offset >= start + cut:
            if word:
                pos += int(word.startswith('\n'))
                break
            continue
        pos += len(word)
        text.append({b'\x09': '\t', b'\x0a': '\n', b'\x0c': '\f'}.get(raw, word))
    return pos, ''.join(text)


def _get_match(pattern, text, flags=0):
    match = re.search(pattern, text, flags)
    return match[1].strip() if match else ''


def _index_footer(native, cut):
    """Retain every record from the exhibits heading through the index footer."""
    start = u32(native, 532)
    paragraph = start
    letters = bytearray()
    begin = None
    index = False
    for offset, raw in records(native, start, start + cut):
        if raw[0] == 22 or raw == b'\x0c':
            heading = bytes(letters).replace(b' ', b'').upper()
            if heading == b'INDEX':
                index = True
            elif index and heading == b'EXHIBITS' and begin is None:
                begin = paragraph
            if raw == b'\x0c' and begin is not None:
                return begin - start, offset - start
            paragraph = offset
            letters.clear()
        elif raw[0] >= 32:
            letters.extend(raw)
    return 0, 0


def _case_numbers(text, table):
    after = re.split(r'CASE NO\.\s*:', text, maxsplit=1, flags=re.I)
    if len(after) != 2:
        return ()
    if table:
        # Additional entries begin at the same indentation in the next cell
        # lines. The empty paragraph after the table belongs to the cover.
        rows = after[1].split('\n')
        result = [rows[0].strip()]
        for row in rows[1:]:
            if not re.match(r'^ {9,}\S', row):
                break
            result.append(row.strip())
        return tuple(x for x in result if x)
    # Scoped captions use tabs to stack docket numbers, including civil IDs.
    line = after[1].split('\n')[0]
    return tuple(dict.fromkeys(re.findall(r'(?<![\w-])(?=[\w-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)*(?![\w-])',
                                          line, re.I)))


def _parse_appearances(page, fields):
    from app.src.notice_model import Appearance
    people = []
    groups = list(re.finditer(r'FOR THE (APPLICANT|DEFENDANTS?):', page, re.I))
    for i, heading in enumerate(groups):
        side = 'Applicant' if heading[1].upper() == 'APPLICANT' else 'Defendant'
        number = i + 1
        if fields.get(f'APPEARANCE SIDE {number}'):
            people.append(Appearance(side=side, **{
                attr: fields.get(_appearance_name(prefix, number), '') for attr, prefix in APPEARANCE_FIELDS}))
            continue
        end = groups[i + 1].start() if i + 1 < len(groups) else len(page)
        lines = [s.strip() for s in page[heading.end():end].splitlines() if s.strip()]
        firm = next((line for line in lines if 'zoom videoconference' not in line.lower()), '')
        by = next((j for j, line in enumerate(lines) if re.match(r'BY\s*:', line, re.I)), None)
        rest = lines[by + 1:] if by is not None else []
        attorney = re.sub(r'^BY\s*:\s*', '', lines[by], flags=re.I) if by is not None else ''
        title = _get_match(r',\s*((?:Attorney|Esquire|Esq\.).*)$', attorney, re.I)
        if title:
            attorney = attorney[:attorney.rfind(',')].strip()
        email = next((x for x in rest if '@' in x), '')
        phone = next((x for x in rest if re.search(r'\d{3}\)?[ .-]+\d{3}[ .-]\d{4}', x)), '')
        location = next((re.match(r'(.+?),\s*([A-Za-z. ]+)\s+(\d{5}(?:-\d{4})?)\b', x)
                         for x in rest if re.search(r',\s*[A-Za-z. ]+\s+\d{5}\b', x)), None)
        address = next((x for x in rest if x != email and x != phone and
                        (location is None or not x.startswith(location[1] + ','))), '')
        suite = _get_match(r'\b((?:Suite|Ste\.?|Floor)\s+[\w-]+)', ' '.join(rest), re.I)
        if suite and address.endswith(suite):
            address = address[:-len(suite)].rstrip(' ,')
        people.append(Appearance(side, firm, attorney, title, address, suite,
                                 *(location.groups() if location else ('', '', '')), phone, email))
    return tuple(people)


def existing_cover(bundle, job):
    cut = _body_offset(job)
    if not cut:
        return {}, (), 0
    speakers, caps = rendering_settings(job, bundle)
    pos, text = _project_prefix(job.native_bytes, cut, speakers, caps)
    fields = field_texts(job.native_bytes)
    caption = text.partition(RULE)[0]
    plaintiff = _get_match(r'STATE OF CALIFORNIA\s+([^,\t\n]+),', caption)
    defendant = _get_match(r'\bvs\.\s+(.*?)\s+Defendants?\.', caption, re.I | re.S)
    defendant = re.sub(r'(?<=/)\s+', '', ' '.join(defendant.split())).rstrip(', ')
    parts = text.split('\f')
    appearance_page = next((p for p in parts if 'A P P E A R A N C E S:' in p), '')
    index_page = next((p for p in parts if 'I N D E X' in p), '').partition('E X H I B I T S')[0]
    index_rows = re.findall(r'(?im)^[ \t]*BY[ \t]+([^\n\f]*)', index_page)
    pages = tuple(_get_match(r'(\d+(?:\s*[,–-]\s*\d+)*)\s*$', row) for row in index_rows)
    values = dict(
        plaintiff=fields.get('PLAINTIFF') or plaintiff, defendant=fields.get('DEFENDANT') or defendant,
        deponent=re.sub(r'[\x00-\x1f]', '', fields.get('DEPONENT', '')),
        case_numbers=_case_numbers(parts[0] if has_captions(job.native_bytes) else caption,
                                   has_captions(job.native_bytes)),
        file_number=_get_match(r'FILE NO\.\s*:\s*([^\n\t\f]+)', text),
        taking_side=_get_match(r'behalf of the (Applicant|Defendant)', text, re.I).title(),
        time=_get_match(r'commencing at (\d{1,2}:\d{2}\s*[ap]\.?m\.?)', text, re.I),
        date=fields.get(DEPOSITION_DATE, ''), weekday=fields.get(WEEKDAY, ''),
        appearances=_parse_appearances(appearance_page, fields),
        speakers=tuple(fields.get(f'EZ SPEAKER {i:02}', '') for i in range(1, max(2, len(pages)) + 1)))
    return values, pages, pos


def build_cover(bundle, job, details, *, index_pages=None):
    problems = cover_overflow(details)
    if problems:
        raise ValueError('The notice exceeds the template space. Edit ' + ', '.join(problems) + '.')
    original = job.native_bytes
    start, length = struct.unpack_from('<II', original, 532)
    cut = _body_offset(job)
    _, existing_pages, old_pos = existing_cover(bundle, job) if cut else ({}, (), 0)
    pages = existing_pages if index_pages is None else tuple(index_pages)
    native = _supply_styles(original)
    begin, end = _index_footer(original, cut)
    footer = original[start + begin:start + end]
    header, values = _cover_pages(details, read_layouts(native)[0], pages, footer)
    for value in values.values():
        _text(value)
    identifiers = {entry.name.encode('cp1252'): entry.identifier for entry in read_fields(native)}
    header = b''.join((raw[:6] + identifiers.get(raw[10:-1], raw[6:10]) + raw[10:]
                       if raw[:2] == b'\x15\x07' else raw) for _, raw in records(header, 0, len(header)))
    retained = b''.join(raw for offset, raw in records(original, start, start + cut)
                        if not begin <= offset - start < end and (raw[0] == 0x13 or raw[:2] == b'\x15\x08'))
    body = original[start + cut:start + length]
    # A literal-first job needs a paragraph boundary at the end of the cover.
    # A native paragraph-first job already owns its paragraph, style and label.
    first = next((raw for _, raw in records(body, 0, len(body))
                  if raw[0] >= 32 or raw[0] in (1, 2, 22) or raw[:2] == b'\x15\x07'), b'')
    join = _p() if first and first[0] != 22 else b''
    prefix = retained + header
    stream = prefix + join + body
    positions = [(0, 0, cut, len(prefix)), (cut, len(prefix) + len(join), length - cut, len(body))]
    result = bytearray(relocate(native, stream, positions))
    # The first primary layout index always opens at the start of the job.
    for (old_field, primary), (new_field, _) in zip(index_positions(native), index_positions(result)):
        if primary and u32(native, old_field) == 0:
            struct.pack_into('<I', result, new_field, 0)
    result = rewrite_fields(bytes(result), values, wrap_captions=True)
    member = bundle.member(job.key + '.sgxml')
    xml = bundle.read(member) if member else None
    xml = update_speaker_xml(xml, {str(i): value for i, value in enumerate(details.speakers, 1)})
    speakers, caps = rendering_settings(job, bundle)
    speakers.update(field_texts(result, display=True))
    new_pos, _ = _project_prefix(result, len(prefix), speakers, caps)
    return result, xml, old_pos, new_pos
