"""Read a deposition notice locally, keeping pleading columns and PDF markup separate."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import re
import sys

import pymupdf

from app.src.notice_model import Appearance, NoticeDetails


@dataclass
class Line:
    box: pymupdf.Rect
    text: str


@dataclass
class Page:
    width: float
    lines: list[Line]
    marks: list[Line]


def _clean(text):
    return ' '.join(text.replace('\u00ad', '').split())


def _key(text):
    return ' '.join(re.findall(r'[^\W_]+', text.casefold()))


def _one(values):
    """Return the first spelling of a value only when all readings agree."""
    unique = {}
    for value in values:
        if value:
            unique.setdefault(_key(value), value)
    return next(iter(unique.values())) if len(unique) == 1 else ''


def _union(items):
    box = pymupdf.Rect(items[0].box)
    for item in items[1:]:
        box.include_rect(item.box)
    return box


def _scan_words(page, *, clip=None, scale=3):
    """Return positioned OCR words in the same PDF coordinates as the annotations."""
    if sys.platform != 'win32':
        try:
            return page.get_textpage_ocr(language='eng', dpi=216, full=True).extractWORDS()
        except (RuntimeError, OSError) as exc:
            raise ValueError('This scanned PDF needs a local English Tesseract installation.') from exc

    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        engine = OcrEngine.try_create_from_language(Language('en-US'))
        if engine is None:
            raise ValueError('Install English text recognition in Windows to read this scanned PDF.')
        area = clip or page.rect
        scale = min(scale, OcrEngine.max_image_dimension / max(area.width, area.height))
        matrix = pymupdf.Matrix(scale, scale)
        pixmap = page.get_pixmap(matrix=matrix, clip=clip, colorspace=pymupdf.csGRAY, alpha=False, annots=False)
        with SoftwareBitmap.create_copy_from_buffer(
                pixmap.samples_mv, BitmapPixelFormat.GRAY8, pixmap.width, pixmap.height) as bitmap:
            # WinRT forbids a blocking wait in the desktop UI's COM apartment.
            with ThreadPoolExecutor(max_workers=1) as worker:
                recognized = worker.submit(engine.recognize_async(bitmap).get).result()
        words = []
        for row, line in enumerate(recognized.lines):
            for col, word in enumerate(line.words):
                r = word.bounding_rect
                x, y = r.x + pixmap.x, r.y + pixmap.y
                box = pymupdf.Rect(x, y, x + r.width, y + r.height) / matrix
                words.append((*box, word.text, 0, row, col))
        return words
    except (ImportError, OSError, RuntimeError) as exc:
        raise ValueError('Windows could not read this scanned PDF using local English OCR.') from exc


def _read_page(page):
    display = page.get_displaylist(annots=False)
    textpage = display.get_textpage()
    if not isinstance(textpage, pymupdf.TextPage):
        textpage = pymupdf.TextPage(textpage)
    words = textpage.extractWORDS()
    # An image can have a few embedded page numbers or labels without a usable text layer.
    needs_scan = len(words) < 12 and any(
        pymupdf.Rect(image['bbox']).get_area() > page.rect.get_area() * .20 for image in page.get_image_info())
    if needs_scan:
        words = _scan_words(page) or words

    groups = defaultdict(list)
    for x0, y0, x1, y1, value, block, line, _ in words:
        groups[block, line].append(Line(pymupdf.Rect(x0, y0, x1, y1), _clean(value)))
    rows, tokens = [], []
    for group in groups.values():
        chunks = []
        for token in sorted(group, key=lambda item: item.box.x0):
            if not chunks or token.box.x0 - chunks[-1][-1].box.x1 > 1.65 * token.box.height:
                chunks.append([])
            chunks[-1].append(token)
        for chunk in chunks:
            text = _clean(' '.join(word.text for word in chunk)).strip(' |')
            box = _union(chunk)
            if (not text.strip('()_|-. ') or text.isdecimal() and len(text) <= 3
                    or box.height > 2 * box.width and len(text) > 3):
                continue
            # Read an unclear case identifier on its own before using it. Only accept
            # digits the OCR engine actually reads, without substituting letters.
            if (needs_scan and sys.platform == 'win32' and re.search(r'\bADJ[A-Za-z]', text, re.I)
                    and re.search(r'\d{3}', text)):
                padding = max(8, int(box.height))
                clip = (box + (-padding, -padding, padding, padding)) & page.rect
                readings = [' '.join(w[4] for w in _scan_words(page, clip=clip, scale=zoom))
                            for zoom in (2.5, 1.8)]
                valid = [v for v in readings if len(_CASE.findall(v)) > len(_CASE.findall(text))]
                text = _one(valid) or text
            rows.append(Line(box, text))
            tokens.extend(chunk)

    marks = []
    for annotation in page.annots() or ():
        subtype = annotation.type[1]
        box = annotation.rect * page.rotation_matrix
        if subtype in ('FreeText', 'Text'):
            value = _clean(annotation.info.get('content') or '')
        elif subtype in ('Highlight', 'Underline'):
            vertices = annotation.vertices or []
            regions = [pymupdf.Quad(vertices[i:i + 4]).rect * page.rotation_matrix
                       for i in range(0, len(vertices) - 3, 4)] or [box]
            selected = [w for w in tokens if any(
                (w.box & region).get_area() > w.box.get_area() * .32 for region in regions)]
            value = _clean(' '.join(w.text for w in sorted(selected, key=_position)))
        else:
            continue
        if value:
            marks.append(Line(box, value))
    return Page(page.rect.width, sorted(rows, key=_position), marks)


def _position(line):
    return round((line.box.y0 + line.box.y1) / 6), line.box.x0


def _rows(lines):
    """Join separate label/value fragments on a visual line within one selected column."""
    result = []
    for line in sorted(lines, key=_position):
        if result and abs(line.box.y0 - result[-1].box.y0) < min(line.box.height, result[-1].box.height) * .42:
            pair = sorted((line, result.pop()), key=lambda item: item.box.x0)
            result.append(Line(_union(pair), _clean(' '.join(x.text for x in pair))))
        else:
            result.append(line)
    return result


def _join(lines):
    return re.sub(r'([-/])\s+(?=\w)', r'\1', ' '.join(line.text for line in lines))


_PARTIES = {'applicant': 'Applicant', 'plaintiff': 'Applicant', 'defendant': 'Defendant',
            'respondent': 'Defendant'}
_ROLE = r'(applicant|plaintiff|defendant|respondent)(?:s|\(s\))?'
_COURT = re.compile(r'compensation appeals board|superior court|^of the state of|^state of california\b', re.I)
_SERVICE = re.compile(r'^(?:(?:proof|certificate|declaration|affidavit) of (?:mailing|service)|'
                      r'(?:mailing|service|distribution) list|persons served)\b', re.I)
_CASE = re.compile(r'\bADJ[\s#:.-]*(\d+)\b', re.I)
_CASE_FIELD = re.compile(r'^(?:(?:(?:civil|criminal|court|WCAB)\s+)*(?:case|docket)|WCAB)'
                         r'\s*(?:nos?\b\.?|numbers?\b|#|:)\s*[:#.]?\s*', re.I)
_OTHER_NUMBER = re.compile(r'\b(?:claim|policy|file|job|insurance(?:\s+policy)?)\s*'
                           r'(?:nos?\b\.?|numbers?\b|#|:)', re.I)
_DOCKET = re.compile(r'(?:(?:CIV|CV|CR|MC|SC|C)\s+)?[A-Za-z0-9]+(?:[./:\u2010-\u2014-][A-Za-z0-9]+)*', re.I)


def _docket_values(text, continuation):
    """Read consecutive identifiers from the value of an explicit court field."""
    values, pos = [], 0
    while pos < len(text):
        adj = _CASE.match(text, pos)
        match = adj or _DOCKET.match(text, pos)
        if (not match or not any(c.isdigit() for c in match[0])
                or not adj and match[0].upper().startswith('ADJ')
                or continuation and re.fullmatch(r'\d{1,2}/\d{1,2}/\d{2,4}', match[0])):
            return [] if continuation else values
        values.append((pos, 'ADJ' + adj[1] if adj else match[0]))
        separator = re.match(r'(?:[\s,;/&]+|\band\b)+', text[match.end():], re.I)
        if not separator:
            if continuation and text[match.end():].strip(' .)'):
                return []
            break
        pos = match.end() + separator.end()
    return values


def _case_numbers(page, start, end, divider):
    caption = [r for r in page.lines if start <= r.box.y0 <= end]
    # Keep the left party caption apart from the court and claim fields at its right.
    rows = _rows(r for r in caption if r.box.x0 < divider - 5)
    rows += _rows(r for r in caption if r.box.x0 >= divider - 5)
    hits = []
    for row in rows:
        text = _OTHER_NUMBER.split(row.text, maxsplit=1)[0]
        hits.extend((*_position(row), m.start(), 'ADJ' + m[1]) for m in _CASE.finditer(text))

    labels = [r for r in caption if _CASE_FIELD.match(r.text)]
    if not labels:
        labels = [r for r in page.lines if _CASE_FIELD.match(r.text)]
    for label in labels:
        # A label and its value can be separate PDF text objects. Follow only the
        # contiguous lines of this field, including vertically stacked docket numbers.
        following = _rows(r for r in page.lines if r.box.y0 >= label.box.y0 - 2
                          and r.box.x0 >= label.box.x0 - 6)
        previous = label
        for i, row in enumerate(following):
            if row.box.y0 - previous.box.y1 > max(9, previous.box.height):
                break
            text = row.text
            if i == 0:
                match = _CASE_FIELD.match(text)
                if not match:
                    break
                text = text[match.end():]
            content = _OTHER_NUMBER.split(text, maxsplit=1)[0].strip()
            values = _docket_values(content, continuation=i > 0)
            if not values and (i or text):
                break
            hits.extend((*_position(row), pos, value) for pos, value in values)
            if content != text.strip():
                break
            previous = row
    unique = {}
    for _, _, _, value in sorted(hits):
        unique.setdefault(value.casefold(), value)
    return tuple(unique.values())


def _caption_label(text):
    match = re.fullmatch(r'(?:(.+?),\s*)?' + _ROLE + r'[\s,;.():]*', text.strip(' )|'), re.I)
    if match:
        return _PARTIES[match[2].lower()], (match[1] or '')
    return '', ''


def _labeled(page, label):
    pattern = re.compile(r'^' + label + r'\s*[:=]\s*(.*)$', re.I)
    for i, row in enumerate(page.lines):
        match = pattern.match(row.text)
        if match:
            if match[1]:
                return match[1]
            adjacent = [r for r in page.lines if r.box.x0 >= row.box.x1 - 1
                        and abs(r.box.y0 - row.box.y0) < row.box.height * .65]
            if adjacent:
                return min(adjacent, key=lambda r: r.box.x0).text
            if i + 1 < len(page.lines) and page.lines[i + 1].box.y0 - row.box.y1 < row.box.height:
                return page.lines[i + 1].text
    return ''


def _caption(page):
    labels = [(row, *_caption_label(row.text)) for row in page.lines]
    applicant = next((item for item in labels if item[1] == 'Applicant'), None)
    defendant = next((item for item in labels if item[1] == 'Defendant'), None)
    app = _labeled(page, r'(?:Applicant|Plaintiff)s?')
    defense = _labeled(page, r'(?:Defendant|Respondent)s?')
    end = defendant[0].box.y1 if defendant else float('inf')
    courts = [r for r in page.lines if _COURT.search(r.text)
              and (not applicant or r.box.y0 < applicant[0].box.y0)]
    start = max((r.box.y1 for r in courts), default=0)
    right_starts = [r.box.x0 for r in page.lines if start <= r.box.y0 <= end
                    and r.box.x0 > page.width * .38
                    and re.search(r'^(?:(?:WCAB|case)\b|ADJ\d|notice of\b)', r.text, re.I)]
    divider = min(right_starts, default=page.width * .55)
    left = [r for r in page.lines if start <= r.box.y0 <= end and r.box.x0 < divider - 5]
    if applicant:
        preceding = [r for r in left if r.box.y0 < applicant[0].box.y0 - 2]
        # When the tribunal is absent, keep the block immediately above the party label.
        if not courts and preceding:
            i = len(preceding) - 1
            while i and preceding[i].box.y0 - preceding[i-1].box.y1 < preceding[i].box.height:
                i -= 1
            preceding = preceding[i:]
        app = applicant[2] or _join(preceding)
    if defendant:
        past = applicant[0].box.y1 if applicant else start
        between = [r for r in left if past <= r.box.y0 < defendant[0].box.y0 - 2]
        versus = [i for i, r in enumerate(between) if re.fullmatch(r'[- .]*(?:vs?|versus)[ .-]*', r.text, re.I)]
        if versus:
            between = between[versus[-1]+1:]
        defense = defendant[2] or _join(between)
    return app.strip(' ,;:'), defense.strip(' ,;:'), start, end, divider


_DEGREES = {'md': 'M.D.', 'do': 'D.O.', 'dds': 'D.D.S.', 'dmd': 'D.M.D.', 'dc': 'D.C.',
            'phd': 'Ph.D.', 'psyd': 'Psy.D.', 'jd': 'J.D.', 'rn': 'R.N.', 'np': 'N.P.'}
_DEGREE = re.compile(r',?\s+\b(M\.?D|D\.?O|D\.?D\.?S|D\.?M\.?D|D\.?C|Ph\.?D|'
                     r'Psy\.?D|J\.?D|R\.?N|N\.?P)\b\.?', re.I)
_MEDICAL_ROLE = re.compile(r'^(?:(?:panel|agreed|qualified|medical|evaluator|P?QME|AME)\s+)+', re.I)
_NAME_WORD = re.compile(r"[^\W\d_]+(?:[.'’-][^\W\d_]+)*\.?")
_NOT_NAME = re.compile(r'\b(?:law|counsel|firm|group|office|corporation|company|services?|insurance|'
                       r'administrat\w*|defendants?|applicants?|witness|app[e]?als|deposition|exam\w*|'
                       r'attorney|department|suite|street|avenue|boulevard|court|notice|telephone|'
                       r'facsimile|signed|dated|respectfully|following|record|no copy|case|address)\b', re.I)


def _is_name(text):
    words = text.split()
    return (2 <= len(words) <= 7 and not _NOT_NAME.search(text)
            and all(_NAME_WORD.fullmatch(w) for w in words)
            and words[0][0].isupper() and words[-1][0].isupper())


def _witness_name(text):
    text = _MEDICAL_ROLE.sub('', text.strip(' ,:'))
    doctor = re.match(r'^Dr\.?\s+', text, re.I)
    text = text[doctor.end():] if doctor else text
    degree = _DEGREE.search(text)
    name = text[:degree.start()] if degree else text
    name = re.split(r'\s*,?\s+(?:will|has|shall|was|before|at|on|via|scheduled|date|time|place|'
                    r'rescheduled|is to|is being|in the)\b|[,;:()\[\]]', name, maxsplit=1, flags=re.I)[0]
    name = name.strip(' ,;:.')
    if not _is_name(name):
        return ''
    if degree:
        return f"{name}, {_DEGREES[degree[1].lower().replace('.', '')]}"
    return ('Dr. ' if doctor else '') + name


def _witness(page, start, end, divider, pages):
    right = _join([r for r in page.lines if start <= r.box.y0 <= end and r.box.x0 >= divider - 5])
    body = _join(_rows(r for r in page.lines if end == float('inf') or r.box.y0 >= end))
    candidates = [_labeled(page, r'(?:witness|deponent|name of (?:the )?deponent)')]
    for text in (right, body):
        for m in re.finditer(r'\b(?:deposition|(?:cross[- ]?)?examination)\s+of\s+(?:the\s+)?', text, re.I):
            candidates.append(text[m.end():])
    name = next((result for candidate in candidates if (result := _witness_name(candidate))), '')
    if name and not _DEGREE.search(name):
        plain = _key(re.sub(r'^Dr\.?\s+', '', name, flags=re.I))
        matches = [_witness_name(row.text) for p in pages for row in p.lines if _DEGREE.search(row.text)]
        richer = _one(m for m in matches if _key(m.split(',')[0]) == plain)
        name = richer or name
    return name


_ADDRESS = re.compile(r'^(?:\d+[A-Z]?(?:-\d+)?\s+\S|(?:[^,]{1,20},\s*)?'
                      r'(?:P\.?\s*O\.?|Post Office)\s+Box\b)', re.I)
_STATES = ('Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|'
           'Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|'
           'Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|'
           'New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|'
           'South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|'
           'Wisconsin|Wyoming|District of Columbia|Puerto Rico')
_CITY = re.compile(r"^([^\d(),@;:]{2,45}?),?\s+([A-Z]{2}|" + _STATES + r")\s*,?\s+"
                   r"(\d{5}(?:-\d{4})?)[,.]?$", re.I)
_SUITE = re.compile(r'(?:Suite|Ste\.?|Unit|Floor|Bldg\.?|Building|#)\s*[\w#-]+'
                    r'|(?:\d+(?:st|nd|rd|th)|First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth)'
                    r'\s+Floor', re.I)
_EMAIL = re.compile(r"\b[\w.%+'-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r'(?<!\d)(?:\+?1[-. ]*)?\(?(\d{3})\)?[-. ]*(\d{3})[-. ]*(\d{4})(?!\d)'
                    r'((?:\s*(?:ext\.?|x)\s*\d+)?)', re.I)
_BAR = re.compile(r'[, (\s]+(?:(?:(?:state\s+)?bar(?:\s+(?:no\.?|number))?|SBN)[\s:#.(]*'
                  r'\d+|\d{5,6}\b)', re.I)
_TITLE = re.compile(r'(?:Esq(?:uire)?\.?|Attorney at Law|Hearing Representative|'
                    r'(?:(?:Senior|Managing|Equity) )?Partner|(?:Chief )?Deputy(?: County Counsel)?|'
                    r'County Counsel)\.?', re.I)
_REP = re.compile(r'^(?:(?:co[- ])?(?:attorneys?|counsel|representatives?)\s+for\b|'
                  r'(?:on behalf of|representing|for the)\b)\s*[:,/ -]*', re.I)
_FIRM = re.compile(r'\b(?:law (?:offices?|firm|group)|(?:labor|legal) group|'
                   r'(?:[A-Z][\w’\']+\s+)law\b|L\.?L\.?P|A\.?P\.?C|P\.?L\.?C|P\.?C)\b', re.I)
_NONCOUNSEL = re.compile(r'\bcourt report(?:er|ing)|\bcertified shorthand|\b(?:medical|panel) evaluat|'
                         r'\binsurance (?:company|services|group)|\badjuster\b', re.I)


def _side_for(text, parties):
    text = text.strip(' ,:;/-')
    direct = re.match(r'(?:the\s+)?' + _ROLE + r'\b', text, re.I)
    if direct:
        return _PARTIES[direct[1].lower()]
    name = _key(re.sub(r'^the\s+', '', text, flags=re.I))
    if not name:
        return ''
    # Punctuation and line breaks can differ between the caption and the signature.
    matches = [side for side, party in parties.items() if party and
               (f' {name} ' in f' {_key(party)} ' or f' {_key(party)} ' in f' {name} ')]
    return _one(matches)


def _represented(rows, parties):
    sides = []
    for i, row in enumerate(rows):
        match = _REP.match(row.text)
        if match:
            name = row.text[match.end():]
            sides.append(_side_for(name, parties))
            if i + 1 < len(rows) and not sides[-1]:
                sides.append(_side_for(_clean(name + ' ' + rows[i+1].text), parties))
        else:
            possessive = re.match(_ROLE + r"['’]s?\s+(?:attorney|counsel)\b", row.text, re.I)
            if possessive:
                sides.append(_PARTIES[possessive[1].lower()])
    return _one(sides)


def _firm(text):
    if (not text or not text[0].isupper() or len(text) > 85 or _REP.match(text)
            or _ADDRESS.match(text) or _EMAIL.search(text)
            or re.search(r'[:;]|\b(?:served|employment|attorneys? at law|hereby|shall|my|'
                         r'by mail|was|referred|executed|herein)\b', text, re.I)):
        return ''
    roster = (' & ' in text or ' and ' in text.lower()) and ',' in text and not re.search(r'\d', text)
    if _FIRM.search(text) or roster:
        return text.strip(' ,')
    return ''


def _person(text):
    """Return a possible printed attorney name and its explicit designation."""
    text = re.sub(r'^(?:by\b\s*:?|attn\.?\s*:)\s*', '', text, flags=re.I)
    text = re.sub(r'^(?:mr|mrs|ms|miss)\.?\s+', '', text, flags=re.I)
    text = _BAR.split(text, maxsplit=1)[0].strip(' (,;:')
    title = ''
    match = re.search(r',\s*(' + _TITLE.pattern + r')\s*$', text, re.I)
    if match:
        title = match[1]
        text = text[:match.start()]
    if not _is_name(text) or _firm(text) or re.search(r'\b(?:Dr\.?|center|board|reporters|reporting)\b', text, re.I):
        return '', ''
    return text, title


def _firm_name(rows):
    for i, row in enumerate(rows):
        if re.search(r',\s*(?:county|city) counsel$', row.text, re.I):
            jurisdiction = next((r.text.split(',')[0] for r in rows[i+1:i+3]
                                 if re.match(r'^(?:county|city) of\b', r.text, re.I)), '')
            office = row.text.rsplit(',', 1)[-1].strip()
            return ', '.join(filter(None, (jurisdiction, office)))
        name = _firm(row.text)
        if name:
            return name
    return ''


def _phones(text):
    for m in _PHONE.finditer(text):
        prefix = text[:m.start()]
        if re.search(r'(?:fax|facsimile)\s*[:.]?\s*$', prefix, re.I):
            continue
        yield f'({m[1]}) {m[2]}-{m[3]}{m[4]}'


def _address(rows):
    street = suite = city = state = postal = ''
    for row in rows:
        text = row.text.strip(' ,')
        loc = _CITY.fullmatch(text)
        if loc:
            city, state, postal = loc.groups()
        elif _ADDRESS.match(text) and not street and not _PHONE.fullmatch(text):
            street = text
            split = re.search(r'(?:,\s*|\s+)(' + _SUITE.pattern + r')\s*$', street, re.I)
            if split:
                suite = split[1]
                street = street[:split.start()].rstrip(', ')
        elif _SUITE.fullmatch(text):
            suite = text
    return dict(address=street, suite=suite, city=city, state=state, zip_code=postal)


def _appearance(rows, marks, side, signer=('', '')):
    firm = _firm_name(rows)
    printed = []
    for i, row in enumerate(rows):
        if _ADDRESS.match(row.text) or _REP.match(row.text) or _CITY.fullmatch(row.text):
            continue
        name, title = _person(row.text)
        if name:
            if not title and i + 1 < len(rows) and _TITLE.fullmatch(rows[i+1].text):
                title = rows[i+1].text
            printed.append((name, title, bool(title or _BAR.search(row.text))))
    selected = [name for mark in marks if (name := _person(mark.text)[0])]
    if selected:
        attorney = _one(selected)
    else:
        attorney = signer[0] or _one(n for n, _, tagged in printed if tagged) or _one(n for n, _, _ in printed)
    title = _one(t for n, t, _ in printed if _key(n) == _key(attorney))
    if not title:
        title = _one(t for mark in marks for n, t in [_person(mark.text)] if _key(n) == _key(attorney))
    if not title and _key(signer[0]) == _key(attorney):
        title = signer[1]
    printed_emails = [email for r in rows for email in _EMAIL.findall(r.text)]
    if selected and not any(_key(n) == _key(attorney) for n, _, _ in printed):
        # A replacement attendee can use the firm's general contact. A prior signer's
        # personal mailbox does not identify the person named in the annotation.
        printed_emails = [e for e in printed_emails if re.match(
            r'^(?:office|info|mail|service|calendar|depositions?|intake|contact|reception)@', e, re.I)]
    marked_emails = [e for mark in marks for e in _EMAIL.findall(mark.text)]
    marked_phones = [p for mark in marks for p in _phones(mark.text)]
    email = _one(marked_emails or printed_emails)
    phone = _one(marked_phones or [p for r in rows for p in _phones(r.text)])
    return Appearance(side=side, firm=firm, attorney=attorney, title=title, phone=phone, email=email,
                      **_address(rows))


def _around(page, anchor):
    """Bound one service recipient by the aligned address lines and adjacent column."""
    lane = [r for r in page.lines if abs(r.box.x0 - anchor.box.x0) < page.width * .055]
    i = lane.index(anchor)
    a = b = i

    def adjoining(first, second):
        return second.box.y0 - first.box.y1 <= max(6, .65 * max(first.box.height, second.box.height))

    while a and adjoining(lane[a-1], lane[a]):
        a -= 1
    while b + 1 < len(lane) and adjoining(lane[b], lane[b+1]):
        b += 1
    rows = lane[a:b+1]
    box = _union(rows)
    top = max(box.y0 - 24, lane[a-1].box.y1 if a else 0)
    bottom = min(box.y1 + 26, lane[b+1].box.y0 if b + 1 < len(lane) else float('inf'))
    neighbors = [r.box.x0 for r in page.lines if top <= r.box.y0 < bottom
                 and r.box.x0 > anchor.box.x0 + page.width * .31]
    right = min(neighbors, default=page.width)
    marks = [m for m in page.marks if box.x0 - 20 <= m.box.x0 < right - 2
             and top <= m.box.y0 + min(5, m.box.height / 2) < bottom]
    return rows, marks


def _service_appearances(pages, parties, header, witness):
    records = []
    witness_name = _key(re.sub(r'^Dr\.?\s+', '', witness.split(',')[0], flags=re.I))
    for page in pages:
        seen = set()
        for anchor in page.lines:
            if not (_firm(anchor.text) or _person(anchor.text)[1] or _REP.match(anchor.text)):
                continue
            rows, marks = _around(page, anchor)
            group = tuple(id(row) for row in rows)
            if group in seen:
                continue
            seen.add(group)
            side = _represented(rows, parties)
            if any(_NONCOUNSEL.search(r.text) or re.match(r'^Dr\.?\s+', r.text, re.I)
                   or witness_name and _key(r.text.split(',')[0]) == witness_name
                   for r in rows if not _REP.match(r.text)):
                continue
            row = _appearance(rows, marks, side)
            if not (row.firm or row.attorney) or not (row.address or row.email or marks or side):
                continue
            if header:
                same_firm = row.firm and _key(row.firm) == _key(header.firm)
                same_attorney = row.attorney and _key(row.attorney) == _key(header.attorney)
                same_side = not side or not header.side or side == header.side
                if same_attorney and same_side and (same_firm or not row.firm or not header.firm):
                    continue
                if same_firm:
                    if not row.attorney:
                        continue
                    if not side:
                        marked_names = [_key(_person(mark.text)[0]) for mark in marks]
                        if not header.side or _key(row.attorney) not in marked_names:
                            # A copy sent back to the sender may name only its mailing clerk.
                            continue
                        row = replace(row, side=header.side)
            if row not in records:
                records.append(row)
    unknown = [r for r in records if not r.side]
    if len(unknown) == 1 and header and header.side:
        opposite = 'Applicant' if header.side == 'Defendant' else 'Defendant'
        if not any(r.side == opposite for r in records):
            i = records.index(unknown[0])
            records[i] = replace(unknown[0], side=opposite)
    return [r for r in records if r.side]


def _signature(pages):
    candidates = []
    for page in pages:
        for i, row in enumerate(page.lines):
            if not re.fullmatch(r'By\s*:?\s*', row.text, re.I):
                continue
            nearby = [r.text for r in page.lines[i+1:] if row.box.y0 <= r.box.y0 < row.box.y1 + 85
                      and r.box.x0 >= row.box.x0 - 15]
            for j, text in enumerate(nearby):
                name, title = _person(text)
                if name:
                    if not title and j + 1 < len(nearby) and _TITLE.fullmatch(nearby[j+1]):
                        title = nearby[j+1]
                    candidates.append((name, title))
                    break
    return _one(n for n, _ in candidates), _one(t for _, t in candidates)


def extract_notice(pdf_bytes: bytes) -> NoticeDetails:
    """Extract only details supported by the notice. Recording dates come from the job."""
    try:
        with pymupdf.open(stream=pdf_bytes, filetype='pdf') as pdf:
            if not pdf.is_pdf or pdf.needs_pass:
                raise ValueError('Choose an unlocked PDF notice.')
            pages = [_read_page(page) for page in pdf]
    except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
        raise ValueError('The notice could not be read as a PDF.') from exc
    if not pages:
        raise ValueError('The PDF notice has no pages.')

    service_start = next((i for i, p in enumerate(pages) if any(_SERVICE.match(r.text) for r in p.lines)),
                         len(pages))
    notice = pages[:service_start] or pages[:1]
    page = next((p for p in notice if any(_caption_label(r.text)[0] == 'Applicant'
                                           or re.match(r'^(?:Applicant|Plaintiff)\s*:', r.text, re.I)
                                           for r in p.lines)), notice[0])
    plaintiff, defendant, start, end, divider = _caption(page)
    parties = dict(Applicant=plaintiff, Defendant=defendant)
    case_numbers = _case_numbers(page, start, end, divider)
    witness = _witness(page, start, end, divider, pages)

    tribunal = [r.box.y0 for r in page.lines if _COURT.search(r.text) and r.box.y0 <= start]
    header_end = min(tribunal, default=min((r.box.y0 for r in page.lines
                                           if _CASE.search(r.text) or _CASE_FIELD.match(r.text)), default=end))
    header_rows = _rows(r for r in page.lines if r.box.y0 < header_end)
    taking = _represented(header_rows, parties)
    if not taking:
        taking = _one(_represented(_rows(p.lines), parties) for p in notice)
    if not taking:
        text = ' '.join(_join(p.lines) for p in notice)
        taking = _one(_PARTIES[m[1].lower()] for m in re.finditer(
            r'\b' + _ROLE + r'\s+(?:will|shall)\s+(?:take|conduct)\s+(?:the|this|a)\s+deposition\b',
            text, re.I))
    marks = [m for m in page.marks if m.box.y0 < header_end]
    row = _appearance(header_rows, marks, taking, _signature(notice))
    represented_at = next((i for i, r in enumerate(header_rows) if _REP.match(r.text)), len(header_rows))
    letterhead = header_rows[:represented_at]
    legal_header = row.firm or represented_at < len(header_rows) or any(
        _BAR.search(' ' + r.text) or _person(r.text)[1] for r in letterhead)
    provider_header = any(_NONCOUNSEL.search(r.text) or re.match(r'^Dr\.?\s+', r.text, re.I) for r in letterhead)
    header = row if (row.firm or row.attorney) and legal_header and not provider_header else None
    service = _service_appearances(pages[service_start:], parties, header, witness)
    appearances = tuple(([header] if header else []) + service)
    return NoticeDetails(plaintiff=plaintiff, defendant=defendant, case_numbers=case_numbers,
                         deponent=witness, taking_side=taking, appearances=appearances)
