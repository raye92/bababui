"""Spelling choices and common English suffixes using a bundled offline dictionary."""
from functools import lru_cache
import re

from PySide6.QtWidgets import QInputDialog

from app.src.smart_editing import CommandCancelled, WORD, current_word, replace_text, revision_of, select_text, selection


@lru_cache(maxsize=1)
def dictionary():
    from spellchecker import SpellChecker
    return SpellChecker(language='en', distance=1)


def inflect(word, ending):
    root = word.lower()
    plain = root + ending
    options = [plain]
    if ending == 's' and root.endswith(('s', 'sh', 'ch', 'x', 'z')):
        options.insert(0, root + 'es')
    if re.search(r'[^aeiou]y$', root) and ending in ('s', 'ed'):
        options.insert(0, root[:-1] + ('ies' if ending == 's' else 'ied'))
    if root.endswith('ie') and ending == 'ing':
        options.insert(0, root[:-2] + 'ying')
    if root.endswith('e') and ending in ('ed', 'ing'):
        options.insert(0, root[:-1] + ending)
    if ending != 's' and re.search(r'[aeiou][bcdfghjklmnpqrstvz]$', root):
        options.append(root + root[-1] + ending)
    known = dictionary().known(options)
    result = next((option for option in options if option in known), plain)
    if word.isupper():
        return result.upper()
    return result.capitalize() if word.istitle() else result


def check_spelling(editor, command):
    text, start, end = selection(editor)
    checker = dictionary()
    revision = revision_of(editor)
    if command == 'Resume Spellcheck':
        start = min(len(text), getattr(editor, '_smart_spell_next', end))
    if command == 'Spelling Lookup':
        word = current_word(text, start)
        matches = [word] if word else []
    else:
        matches = WORD.finditer(text, start)
    for match in matches:
        word = match[0]
        if not word.isalpha() or len(word) > 64:
            continue
        if revision and any(match.start() < e.end and match.end() > e.start for e in revision.elements):
            continue
        if command != 'Spelling Lookup' and checker.known([word]):
            continue
        candidates = checker.candidates(word) or set()
        choices = sorted(candidates, key=lambda w: (-checker.word_usage_frequency(w), w))
        if word.istitle():
            choices = [w.capitalize() for w in choices]
        select_text(editor, text, match.start(), match.end())
        options = list(dict.fromkeys([word, *choices]))
        choice, ok = QInputDialog.getItem(editor, command, f'Spelling for “{word}” (choose or type a correction)',
                                          options, int(len(options) > 1), True)
        editor._smart_spell_next = match.end()
        if not ok:
            raise CommandCancelled()
        if choice != word:
            result = replace_text(editor, match.start(), match.end(), choice)
            if not result:
                editor._smart_spell_next = match.start() + len(choice)
            return result
        return
    return 'No further spelling issues found.' if command != 'Spelling Lookup' else 'Place the cursor on a word.'
