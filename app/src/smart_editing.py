"""Text operations shared by Smart Keys and recorded macro steps."""
import re
from bisect import bisect_right

from PySide6.QtGui import QTextCursor

from app.src.casecat.anchors import utf16_index


class CommandCancelled(Exception):
    """A modal command ended without accepting the requested input."""


WORD = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*['’]?", re.UNICODE)
AFTER_WORD = {
    'Insert Comma After Word': ',', 'Insert Period After Word': '.',
    'Insert Semicolon After Word': ';', 'Insert Colon After Word': ':',
    'Insert Question Mark After Word': '?',
}
SMART_PUNCT = {
    'Smart Comma': ',', 'Smart Period': '.', 'Smart Exclamation': '!',
    'Smart Remove Punctuation': '', 'Smart Question': '?', 'Smart Colon': ':',
    'Smart Semicolon': ';', "Insert Reporter's Dash": '--',
}
WORD_EDITS = {
    'Word Swap', 'Cap/Uncap', 'Cycle Possession', 'Surround With Dash',
    'Add Suffix -s', 'Add Suffix -ed', 'Add Suffix -ing', 'Force Lowercase',
    'Shave Current Word', 'Insert Hyphen', 'Insert Cap Next', 'Cap Next Word',
}
DELETES = {'Delete Word', 'Delete Backward', 'Backspace Word', 'Delete Forward', 'Delete Entire Line'}


def units(text):
    return len(text.encode('utf-16-le')) // 2


def revision_of(editor):
    source = getattr(editor, '_native_source', None)
    return source[1].revision if source else None


def selection(editor):
    text = editor.toPlainText()
    c = editor.textCursor()
    return text, utf16_index(text, c.selectionStart()), utf16_index(text, c.selectionEnd())


def set_position(editor, position, *, select=False):
    c = editor.textCursor()
    limit = editor.document().characterCount() - 1
    c.setPosition(max(0, min(position, limit)), QTextCursor.KeepAnchor if select else QTextCursor.MoveAnchor)
    editor.setTextCursor(c)
    editor.ensureCursorVisible()


def select_text(editor, text, start, end):
    set_position(editor, units(text[:start]))
    set_position(editor, units(text[:end]), select=True)


def replace_text(editor, start, end, content, *, caret=None, delete_atoms=False):
    """Edit through Qt contentsChange. Explicit deletions may remove entire CAT atoms."""
    if editor.isReadOnly():
        return 'This transcript view is read-only.'
    text = editor.toPlainText()
    revision = revision_of(editor)
    if revision:
        first, last = revision.atomic_range(start, end)
        if any(first < e.end and last > e.start for e in revision.elements):
            if not delete_atoms:
                return 'This edit crosses a native field or format symbol. Select ordinary transcript text.'
            editor.apply_native_revision(revision._replace(first, last, content), first + len(content),
                                         edit_range=(first, last))
            return ''
    cursor = editor.textCursor()
    cursor.setPosition(units(text[:start]))
    cursor.setPosition(units(text[:end]), QTextCursor.KeepAnchor)
    cursor.beginEditBlock()
    if content:
        cursor.insertText(content)
    else:
        cursor.removeSelectedText()
    cursor.endEditBlock()
    if caret is not None:
        cursor.setPosition(units(editor.toPlainText()[:caret]))
    editor.setTextCursor(cursor)
    return ''


def current_word(text, pos):
    """Word under or immediately after the cursor, within this paragraph."""
    begin = text.rfind('\n', 0, pos) + 1
    end = text.find('\n', pos)
    for word in WORD.finditer(text, begin, len(text) if end < 0 else end):
        if word.end() > pos:
            return word
        if word.end() == pos and (pos == len(text) or text[pos] == '\n'):
            return word
    return None


def page_row(editor):
    rows = editor.page_lines()
    index = max(0, bisect_right(rows, editor.textCursor().position(), key=lambda line: line.position) - 1)
    return rows, index


def delete(editor, name):
    text, start, end = selection(editor)
    if name == 'Delete Entire Line':
        rows, index = page_row(editor)
        if not rows:
            return ''
        start = utf16_index(text, rows[index].position)
        end = utf16_index(text, rows[index + 1].position) if index + 1 < len(rows) else len(text)
        if index == len(rows) - 1 and start > 0 and text[start - 1] == '\n':
            start -= 1
    elif start == end:
        if name == 'Delete Word':
            if start == len(text) or text[start] == '\n':
                return ''
            word = current_word(text, start)
            if word is None:
                return ''
            start, end = word.span()
            while text[end:end + 1] in (' ', '\t'):
                end += 1
        else:
            cursor = editor.textCursor()
            movement = {'Backspace Word': QTextCursor.PreviousWord, 'Delete Forward': QTextCursor.NextCharacter,
                        'Delete Backward': QTextCursor.PreviousCharacter}[name]
            cursor.movePosition(movement, QTextCursor.KeepAnchor)
            start, end = (utf16_index(text, pos) for pos in (cursor.selectionStart(), cursor.selectionEnd()))
    return replace_text(editor, start, end, '', delete_atoms=True)


def apply_punctuation(editor, text, position, mark):
    """Replace attached punctuation and normalize the following gap and initial."""
    start = position
    while start and text[start - 1] in ' \t':
        start -= 1
    while start and text[start - 1] in '.,;:!?':
        start -= 1
    if text[:start].endswith('--'):
        start -= 2
        while start and text[start - 1] == ' ':
            start -= 1
    match = re.match(r'(?:[ \t]*--|[.,;:!?])*[ \t]*', text[start:])
    end = start + match.end()
    old_mark = text[start:end].strip()
    replacement = (' ' if mark == '--' and start and text[start - 1] != '\n' else '') + mark
    before_next = end < len(text) and text[end] != '\n'
    next_initial = ''
    if before_next:
        sentence = mark in ('.', '?', '!', ':')
        replacement += '  ' if sentence else ' '
        following = WORD.match(text, end)
        if following and sentence:
            next_initial = text[end].upper()
        elif following and old_mark in ('.', '?', '!', ':') and following[0] != 'I' and not following[0].isupper():
            next_initial = text[end].lower()
    caret = start + len(replacement)
    return replace_text(editor, start, end + bool(next_initial), replacement + next_initial, caret=caret)


def punctuation(editor, name):
    text, start, _ = selection(editor)
    if name in AFTER_WORD:
        word = current_word(text, start)
        if word is None:
            return 'There is no word on this line.'
        return apply_punctuation(editor, text, word.end(), AFTER_WORD[name])
    return apply_punctuation(editor, text, start, SMART_PUNCT[name])


def word_edit(editor, name):
    text, start, end = selection(editor)
    if name == 'Insert Hyphen':
        return replace_text(editor, start, end, '-')
    word = current_word(text, start)
    if start == end:
        if not word:
            return 'There is no word on this line.'
        start, end = word.span()
    value = text[start:end]
    if name == 'Word Swap':
        if not word:
            return 'Place the cursor on the first word to swap.'
        following = WORD.search(text, word.end())
        if not following or '\n' in text[word.end():following.start()]:
            return 'A second word is needed on this paragraph.'
        start, end = word.start(), following.end()
        revision = revision_of(editor)
        if revision:
            if any(start < e.end and end > e.start for e in revision.elements):
                return 'Choose two words outside native fields and paragraph symbols.'
            # CAT swaps the words but leaves their steno in place. Two edits
            # keep the original stroke and audio associations on each side.
            updated = revision._replace(following.start(), following.end(), word[0])
            if hasattr(editor, 'native_edit_requested'):
                editor.apply_native_revision(updated, start, edit_range=following.span())
                updated = revision_of(editor)._replace(start, word.end(), following[0])
                editor.apply_native_revision(updated, start, edit_range=word.span())
            else:
                updated = updated._replace(start, word.end(), following[0])
                editor.apply_native_revision(updated, start, edit_range=(start, end))
            return ''
        replacement = following[0] + text[word.end():following.start()] + word[0]
    elif name == 'Cap/Uncap':
        if value.isupper():
            replacement = value.lower()
        elif value[0].isupper():
            replacement = value.upper()
        else:
            replacement = WORD.sub(lambda m: m[0][0].upper() + m[0][1:], value)
    elif name == 'Cycle Possession':
        if value.endswith(("s'", 's’')):
            replacement = value[:-1]
        elif value.endswith(("'s", '’s')):
            replacement = value[:-2] + "s'"
        elif value.endswith('s'):
            replacement = value[:-1] + "'s"
            # An unmodified plural starts the cycle with its plural possessive.
            if getattr(editor, '_possession_position', None) != (start, value):
                replacement = value + "'"
        else:
            replacement = value + "s'"
        editor._possession_position = (start, replacement)
    elif name == 'Surround With Dash':
        replacement = '-- ' + value.strip() + ' --'
    elif name.startswith('Add Suffix '):
        from app.src.smart_spelling import inflect
        replacement = inflect(value, name.split('-')[-1])
    elif name == 'Shave Current Word':
        replacement = value[:-1]
    elif name in ('Cap Next Word', 'Insert Cap Next'):
        replacement = value[:1].upper() + value[1:]
    else:
        replacement = value.lower()
    return replace_text(editor, start, end, replacement, caret=start)
