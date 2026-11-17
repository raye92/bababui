"""Compare written integers with their standard English cardinal spellings."""
import re


SMALL = ('zero one two three four five six seven eight nine ten eleven twelve '
         'thirteen fourteen fifteen sixteen seventeen eighteen nineteen').split()
TENS = ('zero ten twenty thirty forty fifty sixty seventy eighty ninety').split()
SCALES = ((10**12, 'trillion'), (10**9, 'billion'), (10**6, 'million'),
          (1000, 'thousand'), (100, 'hundred'))
SCALE_WORDS = {word for _, word in SCALES}
NUMBER_WORDS = set(SMALL) | set(TENS) | SCALE_WORDS | {'point'}
INTEGER = re.compile(r'0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+')
CONNECTORS = "+-/‐‑–—−_'’"
TITLE_BEFORE_NAME = re.compile(r'\b(?:Mr|Mrs|Ms|Miss|Dr|Prof|Rev|Hon|St)\.? +$', re.I)


def _spelling(value):
    if value < 20:
        return SMALL[value]
    if value < 100:
        tens, units = divmod(value, 10)
        return TENS[tens] + (r'[ \-‐‑]' + SMALL[units] if units else '')
    for scale, name in SCALES:
        if value >= scale:
            count, remainder = divmod(value, scale)
            quantity = '(?:one|a)' if count == 1 else _spelling(count)
            head = f'{quantity} {name}'
            if remainder:
                head += (' (?:and )?' if remainder < 100 else ' ') + _spelling(remainder)
            return head


def _attached_notation(text, start, end):
    previous = text[start-1:start] if start else ''
    if previous and (previous.isalnum() or previous in CONNECTORS + '.,:'):
        return True
    next_char = text[end:end+1]
    return bool(next_char and (next_char.isalnum() or next_char in CONNECTORS
                               or next_char in '.,:' and text[end+1:end+2].isdigit()))


def _partial_number(text, start, end):
    if _attached_notation(text, start, end):
        return True
    # Do not convert a fragment of a larger spelling such as "twenty five".
    before = text[max(0, start-32):start]
    if TITLE_BEFORE_NAME.search(before):
        return True
    prefix = re.search(r'([A-Za-z]+)(?: +(and))? +$', before, re.I)
    if prefix:
        preceding = prefix[1].casefold()
        adjacent = SCALE_WORDS if prefix[2] else NUMBER_WORDS
        if preceding in adjacent:
            return True
    suffix = re.match(r' +([A-Za-z]+)\b', text[end:end+32])
    return bool(suffix and suffix[1].casefold() in NUMBER_WORDS)


def equivalent_integer(spelled, start, end, digits, digit_start, digit_end):
    literal = digits[digit_start:digit_end]
    if not INTEGER.fullmatch(literal) or len(literal.replace(',', '')) > 15:
        return False
    if _partial_number(spelled, start, end) or _attached_notation(digits, digit_start, digit_end):
        return False
    pattern = _spelling(int(literal.replace(',', '')))
    return bool(re.fullmatch(pattern, spelled[start:end], re.I))
