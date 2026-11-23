"""Local number-format choices for the selected transcript passage."""
import re

from PySide6.QtWidgets import QInputDialog

from app.src.number_forms import SMALL, TENS, SCALES
from app.src.smart_editing import CommandCancelled, current_word, replace_text, selection


def cardinal(value):
    if value < 20:
        return SMALL[value]
    if value < 100:
        tens, ones = divmod(value, 10)
        return TENS[tens] + ('-' + SMALL[ones] if ones else '')
    for scale, name in SCALES:
        if value >= scale:
            quotient, remainder = divmod(value, scale)
            return cardinal(quotient) + ' ' + name + (' ' + cardinal(remainder) if remainder else '')


def number_value(text):
    if re.fullmatch(r'\d{1,15}|\d{1,3}(?:,\d{3}){1,4}', text):
        return int(text.replace(',', ''))
    numbers = dict(zip(SMALL, range(20)))
    numbers.update({word: n*10 for n, word in enumerate(TENS) if n >= 2})
    scales = {word: magnitude for magnitude, word in SCALES}
    total = group = 0
    previous_scale = 10**15
    for word in re.split(r'[ \-]+', text.casefold()):
        if word in numbers:
            group += numbers[word]
        elif word.isascii() and word.isdigit() and len(word) < 16:
            group += int(word)
        elif word == 'hundred' and 0 < group < 100:
            group *= 100
        elif word in scales and 0 < scales[word] < previous_scale and group:
            total += group * scales[word]
            previous_scale = scales[word]
            group = 0
        elif word != 'and':
            return None
    value = total + group
    if not 0 <= value < 10**15:
        return None
    normalized = re.sub(r'\s+and\s+', ' ', text.casefold()).replace('-', ' ')
    if not re.search(r'\d', text) and normalized != cardinal(value).replace('-', ' '):
        return None
    return value


def roman(value):
    output = []
    for magnitude, numeral in ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
                               (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'),
                               (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):
        count, value = divmod(value, magnitude)
        output.append(count*numeral)
    return ''.join(output)


def convert_number(editor):
    text, start, end = selection(editor)
    if start == end:
        word = current_word(text, start)
        if not word:
            return 'Select a number to convert.'
        start, end = word.span()
        digits = re.match(r'\d{1,3}(?:,\d{3})+\b', text[start:])
        if digits:
            end = start + digits.end()
    literal = text[start:end]
    value = number_value(literal)
    if value is None:
        return 'Select one integer, written in digits or words.'
    suffix = 'th' if 10 <= value % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(value % 10, 'th')
    formats = [str(value), f'{value:,}', cardinal(value), f'{value}{suffix}', f'${value:,}.00']
    if 0 < value < 4000:
        formats.append(roman(value))
    digits = literal.replace(',', '')
    if digits.isdigit():
        if len(digits) in (3, 4) and int(digits[:-2]) < 24 and int(digits[-2:]) < 60:
            formats.append(digits[:-2] + ':' + digits[-2:])
        if len(digits) == 9:
            formats.append(f'{digits[:3]}-{digits[3:5]}-{digits[5:]}')
        if len(digits) == 10:
            formats.append(f'({digits[:3]}) {digits[3:6]}-{digits[6:]}')
    options = list(dict.fromkeys(formats))
    choice, ok = QInputDialog.getItem(editor, 'Number Conversion', 'Formatted number', options, 0, False)
    if not ok:
        raise CommandCancelled()
    return replace_text(editor, start, end, choice)
