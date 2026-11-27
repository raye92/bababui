"""Build the reporter's five-page notice cover in the selected native job."""
from functools import lru_cache
from pathlib import Path
import re
import struct
import textwrap

from .caption import (BODY_DIVIDER, TABLE_END, TABLE_START, caption_value, cell, cover_end,
                      has_captions, reporter_divider_end)
from .codec import records, u32
from .field_table import field_record, field_texts, read_fields, replace_section, rewrite_fields
from .fields import update_speaker_xml
from .layout import index_positions, read_layouts
from .rendering import TextRenderer, render_record
from .structure import relocate, rendering_settings


BOARD = "WORKERS' COMPENSATION APPEALS BOARD"
RULE = '~' * 30
SINGLE_ON = b'\x12\x09'
SINGLE_OFF = b'\x12\x89'
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
            rows.extend((b'', b'', b''))
        rows.extend((b'FOR THE APPLICANT:' if person.side == 'Applicant' else b'FOR THE DEFENDANTS:', b''))
        if entries['firm']:
            rows.append(entries['firm'])
        rows.append(b'\t(Zoom videoconference)')
        attorney = b', '.join(x for x in (entries['attorney'], entries['title']) if x)
        separator = b' ' if person.address.rstrip().endswith(',') else b', '
        street = separator.join(x for x in (entries['address'], entries['suite']) if x)
        city = b', '.join(x for x in (entries['city'], entries['state']) if x)
        city = b' '.join(x for x in (city, entries['zip_code']) if x)
        rows.extend(x for x in ((b'\tBY:  ' + attorney) if attorney else b'',
                               street, city, entries['phone'], entries['email']) if x)
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


def _caption(details, left, right, source_caption):
    numbers = details.case_numbers or ('',)
    longest = max(map(len, numbers))
    gap = re.search(r'\bCASE NO\.:( *)(?=\S)', source_caption, re.I)
    padding = gap[1][:2] if gap else ' '
    label = b'CASE NO.:' + (padding.encode('ascii') if longest < 16 else b'')
    role = re.search(r'^[ \t]*(Defendants?\.)[ \t]*$', source_caption, re.I | re.M)
    defendant_role = _text(role[1]) if role else b'Defendants.'
    column = min(35, 56 - len(label) - longest)
    split = left + round((right - left) * column / 57)
    plaintiff, defendant = field_record('PLAINTIFF'), field_record('DEFENDANT')
    # Ordinary fields and CATalyst cell bounds keep the two columns independent.
    # The half-line returns reproduce the caption's single-spaced continuations.
    left_cell = (SINGLE_ON + plaintiff + b',' + _p(9) + _p(9, b'\t\t\t\tApplicant,') +
                 _p(9) + _p(9, b' \t\t\x12\x8evs.') + _p(9) + _p(9, defendant + b',') +
                 _p(9) + _p(9, b' \t  \t\t' + defendant_role) + _p(9) + _p(9, RULE))
    right_cell = label + _text(numbers[0])
    for number in numbers[1:]:
        right_cell += _p(9, b' ' * len(label) + _text(number))
    header = (_p() + TABLE_START + cell(left, split) + left_cell +
              cell(split, right) + right_cell + TABLE_END + SINGLE_OFF)
    rows = 9 + sum(caption_value(name, value).count('\n') + 1 for name, value in
                   (('PLAINTIFF', details.plaintiff), ('DEFENDANT', details.defendant)))
    return header, max(rows, len(numbers))


def _cover_pages(details, layout, pages, index_footer, source_caption):
    caption, caption_rows = _caption(details, layout.paragraphs[7].left, layout.paragraphs[7].right, source_caption)
    heading = _p(7, BOARD) + _p(7, 'STATE OF CALIFORNIA')
    deponent, date = field_record('DEPONENT'), field_record(DEPOSITION_DATE)
    # CATalyst resumes on a whole line after a table. If the rule falls
    # halfway between numbers, its title belongs one numbered line lower.
    title_returns = 6 if caption_rows % 2 == 0 else 4
    title_line = 8 + caption_rows // 2
    footer_gap = _p(9) * (2 * (24 - title_line - 4))
    page1 = (heading + caption + _p(9) * title_returns + _p(7, 'DEPOSITION OF') + _p(7, deponent) +
             _p(7, '(PARTICIPANTS REMOTE), CALIFORNIA') + _p(7, b'\x12\x08' + date + b'\x12\x88 ') +
             footer_gap + _p(9, 'REPORTED BY:  Matthew Bui, CSR NO. 14977') +
             _p(9) + _p(9, b'FILE NO.:  ' + _text(details.file_number)))
    party = {'Applicant': 'Applicant', 'Defendant': 'Defendants'}.get(details.taking_side, '')
    page2 = (heading + b' ' + caption + _p(9) * (title_returns - 2) +
             _p(8, b'\t\t\tDeposition of ' + deponent + b', taken on') +
             _p(8, b'\x12\x8ebehalf of the ' + _text(party) + b', at (PARTICIPANTS REMOTE),') +
             _p(8, b'California, commencing at ' + _text(details.time) + b', ' + field_record(WEEKDAY) + b',') +
             _p(8, date + b', before Matthew Bui, CSR No. 14977.'))
    appearance_rows, values = _appearance_rows(details, references=True)
    page3 = (_p(7, SINGLE_ON + b' A P P E A R A N C E S:') + _p(9) +
             b''.join(_p(9, b'\x12\x8e' + row) for row in appearance_rows) + SINGLE_OFF)
    page4 = (_p(7, SINGLE_ON + b'I N D E X') + _p(9) +
             _p(9, b'WITNESS:  ' + deponent) + _p(9) + _p(9, b'EXAMINATION' + b'\t' * 8 + b'PAGE'))
    for index in range(max(2, len(details.speakers))):
        name = f'EZ SPEAKER {index + 1:02}'
        value = details.speakers[index] if index < len(details.speakers) else ''
        manual = pages[index] if index < len(pages) else ''
        if manual and not re.fullmatch(r'[\d ,\-\u2013]+', manual):
            raise ValueError('An index page entry must contain page numbers.')
        # The scoped ruler's next tab after column 45 begins PAGE. Align
        # single page numbers to its right and leave room for longer lists.
        used = 8 + len(value or f'[!{name}]')
        target = max(used + 1, 54 - len(manual))
        tabs = max(0, (min(target, 50) // 5) - (used // 5))
        pad = target - ((used // 5 + tabs) * 5 if tabs else used)
        page4 += _p(9) + _p(9, b'\t\tBY ' + field_record(name) + b'\t' * tabs + b' ' * pad + _text(manual))
    page4 += _p(9) * 3 + (index_footer or
              (_p(7, 'E X H I B I T S') + _p(9) + _p(9, b'  NUMBER\t\t         DESCRIPTION\t\t     PAGE') +
               _p(9) + _p(7, ' (NONE)') + _p(9) * 5 + _p(7, 'INSTRUCTIONS NOT TO ANSWER:') +
               _p(9) + _p(7, 'PAGE             LINE') + _p(9) + _p(7, '(NONE)') +
               _p(9) * 5 + _p(7, 'INFORMATION REQUESTED:  ') + _p(9) + _p(7, 'PAGE             LINE') +
               _p(9) + _p(7, '(NONE)')))
    if not page4.endswith(SINGLE_OFF):
        page4 += SINGLE_OFF
    page5 = (_p(7, deponent + b',') + _p(8, b'\x12\x8e\t\t\t' + _text(OATH[0])) +
             _p(8, b'\x12\x8e\t\t\t' + _text(OATH[1])) + _p() +
             _p(8, b'\t\t' + _text(REPORTER)) + BODY_DIVIDER)
    values.update(PLAINTIFF=details.plaintiff, DEFENDANT=details.defendant, DEPONENT=details.deponent)
    values.update({WEEKDAY: details.weekday, DEPOSITION_DATE: details.date})
    values.update({f'EZ SPEAKER {i:02}': name for i, name in enumerate(details.speakers, 1)})
    return [page1, page2, page3, page4, page5], values


def _body_offset(job):
    """Find the reporter's final layout control, even inside a stroke group."""
    start, size = struct.unpack_from('<II', job.native_bytes, 532)
    boundary = cover_end(job.native_bytes)
    if boundary is not None:
        return boundary - start
    text = job.baseline.text
    if BOARD not in text[:100]:
        return 0
    if BOARD not in text[100:4500] or 'I N D E X' not in text[:12000]:
        return 0
    divider_end = reporter_divider_end(job.native_bytes, start, start + size)
    if divider_end is not None:
        return divider_end - start
    raise ValueError('The existing cover has no recognizable end after the reporter declaration.')


def _project_prefix(native, cut, speakers, all_caps):
    """Return the old/new logical body position and formatted cover lines."""
    if not cut:
        return 0, ''
    renderer = TextRenderer(all_caps=all_caps, cover_tables=True)
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


def _index_sections(native, cut):
    """Locate the index page, its exhibits, and the following oath page."""
    start = u32(native, 532)
    paragraph = page_start = start
    letters = bytearray()
    begin = None
    index = False
    single = page_single = False
    for offset, raw in records(native, start, start + cut):
        if raw[0] == 22 or raw == b'\x0c':
            heading = bytes(letters).replace(b' ', b'').upper()
            if heading == b'INDEX':
                index = True
            elif index and heading == b'EXHIBITS' and begin is None:
                begin = paragraph
            if raw == b'\x0c':
                if begin is not None:
                    return page_start - start, begin - start, offset - start, page_single
                page_start = offset + 1
                page_single = single
            paragraph = offset
            letters.clear()
        elif raw in (SINGLE_ON, SINGLE_OFF):
            single = raw == SINGLE_ON
        elif raw[0] >= 32:
            letters.extend(raw)
    return 0, 0, 0, False


def _cover_fields(stream):
    return {raw[10:-1].decode('cp1252') for _, raw in records(stream, 0, len(stream))
            if raw[:2] == b'\x15\x07'}


def _associations(native, start, end):
    return b''.join(raw for _, raw in records(native, start, end)
                    if raw[0] == 0x13 or raw[:2] == b'\x15\x08')


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
    # A scoped caption interleaves the two columns. Only read later IDs
    # to the right of a tab stop or a padded column boundary.
    numbers = []
    for index, row in enumerate(after[1].splitlines()):
        columns = re.split(r'\t+| {4,}', row)
        for column in (columns if index == 0 else columns[1:]):
            words = re.findall(r'[^\s,;/()]+', column)
            if words and all(re.fullmatch(r'(?=[\w-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)*', word, re.I)
                             for word in words):
                numbers.extend(words)
    return tuple(dict.fromkeys(numbers))


def _party_name(caption, pattern):
    match = re.search(pattern, caption, re.I | re.S | re.M)
    if not match:
        return ''
    left = (re.split(r'\t| {4,}|\bCASE NO\.\s*:', row, maxsplit=1, flags=re.I)[0].strip()
            for row in match[1].splitlines())
    return re.sub(r'(?<=/)\s+', '', ' '.join(part for part in left if part)).rstrip(', ')


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
    plaintiff = (_party_name(caption, r'STATE OF CALIFORNIA(.*?)^[ \t]*Applicants?,') or
                 _get_match(r'STATE OF CALIFORNIA\s+([^\t\n]+),', caption, re.I))
    defendant = _party_name(caption, r'\bvs\.(.*?)\s+Defendants?\.')
    parts = text.split('\f')
    appearance_page = next((p for p in parts if 'A P P E A R A N C E S:' in p), '')
    index_page = next((p for p in parts if 'I N D E X' in p), '').partition('E X H I B I T S')[0]
    index_rows = re.findall(r'(?im)^[ \t]*BY[ \t]+([^\n\f]*)', index_page)
    pages = tuple(_get_match(r'(\d+(?:\s*[,–-]\s*\d+)*)\s*$', row) for row in index_rows)
    tables = has_captions(job.native_bytes)
    values = dict(
        plaintiff=fields.get('PLAINTIFF') or plaintiff, defendant=fields.get('DEFENDANT') or defendant,
        deponent=re.sub(r'[\x00-\x1f]', '', fields.get('DEPONENT', '')),
        case_numbers=_case_numbers(parts[0] if tables else caption, tables),
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
    known, existing_pages, old_pos = existing_cover(bundle, job) if cut else ({}, (), 0)
    pages = existing_pages if index_pages is None else tuple(index_pages)
    native = _supply_styles(original)
    index, begin, end, single = _index_sections(original, cut)
    footer = original[start + begin:start + end]
    source_caption = job.baseline.text[:old_pos].partition('DEPOSITION OF')[0]
    cover_pages, values = _cover_pages(details, read_layouts(native)[0], pages, footer, source_caption)
    for value in values.values():
        _text(value)
    keep_from = begin if end else cut
    if end:
        index_page = original[start + index:start + end]
        speakers = details.speakers + ('',) * max(0, 2 - len(details.speakers))
        index_fields = {'DEPONENT', *(f'EZ SPEAKER {i:02}' for i in range(1, len(speakers) + 1))}
        # An existing scoped index already contains the correct tab stops and
        # examiner references. Preserve additions such as a remote-witness note.
        if (known['speakers'] == speakers and pages == existing_pages and
                index_fields <= _cover_fields(index_page)):
            cover_pages[3] = (SINGLE_ON if single else b'') + index_page
            if not index_page.endswith(SINGLE_OFF):
                cover_pages[3] += SINGLE_OFF
            keep_from = index
        oath = original[start + end + 1:start + cut]
        if 'DEPONENT' in _cover_fields(oath):
            cover_pages[4] = oath
        else:
            cover_pages[4] = _associations(original, start + end + 1, start + cut) + cover_pages[4]
    header = b'\x0c'.join(cover_pages)
    identifiers = {entry.name.encode('cp1252'): entry.identifier for entry in read_fields(native)}
    header = b''.join((raw[:6] + identifiers.get(raw[10:-1], raw[6:10]) + raw[10:]
                       if raw[:2] == b'\x15\x07' else raw) for _, raw in records(header, 0, len(header)))
    retained = _associations(original, start, start + keep_from)
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
