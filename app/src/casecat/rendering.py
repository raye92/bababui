"""Stateful lexical rendering, without changing the native source bytes.

Paragraph and conflict controls are rendered separately from ordinary wording.
Sentence capitalization is supported by controlled CATalyst edits and the full
reporter-provided reference. It is not a title-case or dictionary substitution.
"""


from .caption import is_cell


CONFLICT_STARTS = (b'\x11\x09\x00\x00\x00\x00', b'\x11\x09\x02\x02\x00\x00')


class TextRenderer:
    def __init__(self, *, all_caps=False, cover_tables=False, legacy_projection=False):
        self.capitalize = True
        self.after_punctuation = False
        self.last = ''
        self.has_content = False
        self.all_caps = all_caps
        self.cover_tables = cover_tables
        self.uppercase = False
        self.legacy_projection = legacy_projection
        self.conflict_choice = 0

    def control(self, raw):
        # Measured with Insert Format Symbol, Uncap Next / Cap Next in 22.1.
        if raw in (b'\x12\x8e', b'\x12\x0e'):
            self.capitalize = raw[1] == 0x0e
            self.after_punctuation = False
        if self.cover_tables and raw in (b'\x12\x08', b'\x12\x88'):
            self.uppercase = raw[1] == 8
        if raw in CONFLICT_STARTS and not self.legacy_projection:
            self.conflict_choice = 1
        elif raw == b'\x03':
            self.conflict_choice = 0

    def literal(self, text):
        result = []
        for char in text:
            if char.isalpha():
                if self.capitalize or self.all_caps or self.uppercase:
                    char = char.upper()
                self.capitalize = False
            if char in '.!?:':
                self.after_punctuation = True
            elif char.isspace():
                if self.after_punctuation:
                    self.capitalize = True
                self.after_punctuation = False
            elif char not in '\"\'”’)]':
                self.after_punctuation = False
            result.append(char)
            self.last = char
            self.has_content = True
        return ''.join(result)

    def paragraph(self, style):
        prefix = {2: '     Q    ', 3: '     A    ', 4: '     '}.get(style, '')
        # CaseCAT uses the opening record only to establish the first style.
        text = ('\n' if self.has_content or (self.legacy_projection and style == 8) else '') + prefix
        self.capitalize = True
        self.after_punctuation = False
        self.has_content = True
        if text:
            self.last = text[-1]
            self.has_content = True
        return text

    def conflict_leading_space(self):
        if self.conflict_choice:
            # A translated conflict begins at its first caret. Each later
            # choice includes a leading space in addition to any literal ones.
            return self.conflict_choice > 1
        return bool(self.last and not self.last.isspace())

    def conflict(self):
        if not self.conflict_choice and not self.legacy_projection:
            return ''
        result = (' ' if self.conflict_leading_space() else '') + '^ '
        if self.conflict_choice:
            self.conflict_choice += 1
        self.last = ' '
        self.has_content = True
        return result


def render_record(renderer, raw, speakers):
    op = raw[0]
    if op >= 32:
        return renderer.literal(raw.decode('cp1252'))
    if op == 1:
        return renderer.literal(' ')
    if op == 2:
        return renderer.conflict()
    if op == 0x16:
        return renderer.paragraph(int.from_bytes(raw[1:], 'little'))
    if op == 9 and (not renderer.legacy_projection or renderer.cover_tables):
        return renderer.literal('\t')
    if renderer.cover_tables and (is_cell(raw) or op == 10):
        return renderer.paragraph(255)
    if op == 0x15 and raw[1] == 7:
        label = raw[10:].rstrip(b'\0').decode('cp1252')
        value = speakers.get(label)
        if value is None:
            value = speakers.get(str(int(label[11:])), f'[{label}]') if label.startswith('EZ SPEAKER ') else f'[{label}]'
        return renderer.literal(value or f'[!{label}]')
    renderer.control(raw)
    return ''
