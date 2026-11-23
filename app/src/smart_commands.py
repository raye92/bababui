"""Dispatch CaseCAT keyboard commands without invoking unrelated Qt shortcuts."""
from dataclasses import replace
import re

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import QFileDialog, QInputDialog

from app.src.casecat.anchors import utf16_index
from app.src.casecat.elements import CENTER_JUSTIFY, NativeElement
from app.src.smart_editing import (
    AFTER_WORD, DELETES, SMART_PUNCT, WORD, WORD_EDITS, CommandCancelled, apply_punctuation,
    current_word, delete, page_row, punctuation, replace_text, revision_of,
    select_text, selection, set_position, units, word_edit,
)


MOVES = {'Right': QTextCursor.NextCharacter, 'Left': QTextCursor.PreviousCharacter,
         'Word Right': QTextCursor.NextWord, 'Word Left': QTextCursor.PreviousWord,
         'Left Word Begin': QTextCursor.PreviousWord,
         'Document Top': QTextCursor.Start, 'Document Bottom': QTextCursor.End}
ROW_MOVES = {'Down', 'Up', 'Line Begin', 'Line Home', 'Line End', 'Page Down', 'Page Up',
             'Screen Page Down', 'Screen Page Up', 'Screen Top', 'Screen Bottom'}
NAVIGATION = {f'{verb} {target}' for verb in ('Move', 'Select') for target in MOVES.keys() | ROW_MOVES}
NAVIGATION |= {'Down One Line and Move to Beginning of Line', 'Move Word End', 'Move to End of Current Word'}
SEARCH = {'Search', 'Next Search', 'Search Previous', 'Replace'}
ROUTED = {'Change Keyboard Mode', 'Default Keyboard', 'Play Macro', 'Play Last Macro'}
WINDOW = {'Open File', 'Save File', 'Cycle Open Edit Files', 'Cycle (Reverse) Open Edit Files'}
NATIVE_COMMANDS = {'Fill In Field', 'Scan and Fill in Next Field', 'Insert Format Symbol Dialog',
                   'Scan Forward', 'Scan Backward', 'Reveal Codes', 'View Vertical Notes'}
PUNCT_CYCLES = {'Toggle All Punctuation', 'Toggle Paragraph Ending Punctuation', 'Toggle Sentence Ending Punctuation'}
SUPPORTED = (NAVIGATION | SEARCH | ROUTED | WINDOW | NATIVE_COMMANDS | PUNCT_CYCLES | DELETES
             | WORD_EDITS | AFTER_WORD.keys() | SMART_PUNCT.keys() | {
                 'Play Audio', 'Stop Audio', 'Bookmark Current Cursor Location', 'Go To Bookmarked Cursor',
                 'Copy', 'Paste', 'Cut', 'Undo', 'Redo', 'Insert Tab', 'Space', 'Insert New Line',
                 'Insert Question', 'Insert Answer', 'Insert Continuation Paragraph', 'Insert Colloquy',
                 'Toggle Insert/Overstrike', 'Go to Page/Line', 'Include File', 'Break to File',
                 'Print File', 'Print Current Page', 'Number Conversion', 'Scroll Text Forward',
                 'Scroll Text Backwards', 'Search Next Punctuation', 'Change Last Question Mark to Period',
                 'Interrupted Q/A/C', 'Change A to THE WITNESS',
                 'Spellcheck', 'Resume Spellcheck', 'Spelling Lookup', 'View Personal Dictionary', 'Center Justify',
             })
READ_ONLY = (NAVIGATION | WINDOW | {'Copy', 'Play Audio', 'Stop Audio', 'Search', 'Next Search',
             'Search Previous', 'Scroll Text Forward', 'Scroll Text Backwards', 'Go to Page/Line',
             'Search Next Punctuation', 'Bookmark Current Cursor Location', 'Go To Bookmarked Cursor',
             'Scan Forward', 'Scan Backward', 'Reveal Codes', 'Print File', 'Print Current Page',
             'View Personal Dictionary', 'View Vertical Notes'})


def command_dependency(command):
    if command in SUPPORTED:
        return ''
    groups = {
        'Requires the CaseCAT dictionary and steno definition engine.': (
            'J-Define', 'D-Define', 'K-Define', 'E-Define', 'Other Dictionary Define'),
        'Requires the CaseCAT global translation table.': ('Global Table', 'Undo Last Global'),
        'Requires a live CaseCAT translation session.': ('Stop Translation', 'Follow Realtime', 'Query Realtime Translations'),
        'Requires editable native table records.': ('Add Table Row After Current Row', 'Delete Current Table Row', 'Delete Entire Table'),
        'Requires native conflict choice records.': ('Insert Conflict Dialog', 'Choose Conflict 1', 'Choose Conflict 2', 'Choose Conflict 3'),
    }
    for reason, commands in groups.items():
        if command in commands:
            return reason
    return {
        'Word Definition Dictionary': 'Requires the CaseCAT word definition dictionary.',
        'Restore Steno': 'Requires original steno translation history.',
        'Change Header Text': 'Requires an editable CaseCAT running-header record.',
        'Insert Hidden Text': 'Requires native hidden-text records.',
        'Scan for Untranslates': 'Requires native untranslated-stroke markers.',
        'EZ Sync at Cursor': 'Requires an editable CaseCAT audio synchronization map.',
        'Automatic Number Conversion': 'Requires CaseCAT NumberConversion.ini context rules.',
        'Remove Oops (Hotspot)': 'Requires native Oops hotspot records.',
    }.get(command, f'No offline implementation for {command}.')


class SmartCommands(QObject):
    def __init__(self, view):
        super().__init__(view if isinstance(view, QObject) else None)
        self.view = view
        self.cancelled = False
        self.query = ''
        self.replacement = ''
        self.last_toggle = None
        self.bookmarks = {}
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setInterval(1000)
        self.scroll_timer.timeout.connect(self._scroll)
        self.scrolling = None

    def eventFilter(self, obj, event):
        if self.scrolling and event.type() in (QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.Hide, QEvent.FocusOut):
            self._stop_scroll()
        return False

    def _stop_scroll(self):
        if self.scrolling:
            self.scrolling[0].removeEventFilter(self)
        self.scroll_timer.stop()
        self.scrolling = None

    def _scroll(self):
        if self.scrolling:
            editor, movement = self.scrolling
            previous = editor.textCursor().position()
            self._move(editor, movement)
            if editor.textCursor().position() == previous:
                self._stop_scroll()

    def insert_literal(self, value, editor):
        if editor is None or editor.isReadOnly():
            return 'Choose an editable transcript.'
        try:
            text, start, end = selection(editor)
            if editor.overwriteMode() and start == end and '\n' not in value:
                newline = text.find('\n', start)
                end = min(start + len(value), len(text) if newline < 0 else newline)
            return replace_text(editor, start, end, value, delete_atoms=True)
        except ValueError as exc:
            return str(exc)

    def execute(self, command, editor):
        self.cancelled = False
        unavailable = command_dependency(command)
        if unavailable:
            return unavailable
        if command in ROUTED:
            return 'This command requires the active keyboard profile.'
        if editor is None:
            return 'Choose a transcript editor.'
        if editor.isReadOnly() and command not in READ_ONLY:
            if command not in ('Undo', 'Redo') or not hasattr(editor, 'history_requested'):
                return 'This transcript view is read-only.'
        try:
            return self._execute(command, editor) or ''
        except CommandCancelled:
            self.cancelled = True
            return ''
        except (ValueError, OSError, UnicodeError) as exc:
            return str(exc)

    def _execute(self, name, editor):
        self._stop_scroll()
        if name in NAVIGATION:
            return self._move(editor, name)
        if name in WORD_EDITS:
            return word_edit(editor, name)
        if name in DELETES:
            return delete(editor, name)
        if name in SMART_PUNCT or name in AFTER_WORD:
            return punctuation(editor, name)
        if name in PUNCT_CYCLES or name == 'Change Last Question Mark to Period':
            return self._cycle_punctuation(editor, name)
        if name in SEARCH:
            return self._search(editor, name)
        if name in ('Cut', 'Copy', 'Paste', 'Undo', 'Redo'):
            getattr(editor, name.lower())()
        elif name in ('Play Audio', 'Stop Audio'):
            bar = getattr(self.view, 'playback', None)
            if bar is None:
                return 'Attach WAV audio to use playback.'
            if name == 'Play Audio':
                bar.play_from_cursor()
            else:
                bar.stop_from_keyboard()
        elif name in WINDOW:
            return self._window(name)
        elif name == 'Bookmark Current Cursor Location':
            cursor = editor.textCursor()
            cursor.clearSelection()
            self.bookmarks[editor] = cursor
        elif name == 'Go To Bookmarked Cursor':
            if editor not in self.bookmarks:
                return 'Set a bookmark in this transcript first.'
            editor.setTextCursor(self.bookmarks[editor])
            editor.ensureCursorVisible()
        elif name == 'Toggle Insert/Overstrike':
            editor.setOverwriteMode(not editor.overwriteMode())
        elif name.startswith('Scroll Text'):
            self.scrolling = editor, 'Move Down' if name.endswith('Forward') else 'Move Up'
            editor.installEventFilter(self)
            self.scroll_timer.start()
            self._scroll()
        elif name in ('Insert Question', 'Insert Answer'):
            if revision_of(editor):
                editor.insert_native_symbol(name.split()[-1][0])
            else:
                return self._paragraph(editor, '     ' + name.split()[-1][0] + '    ')
        elif name == 'Insert Colloquy':
            return self._colloquy(editor)
        elif name == 'Center Justify':
            return self._center(editor)
        elif name in ('Insert Continuation Paragraph', 'Insert New Line', 'Insert Tab', 'Space'):
            return self.insert_literal({'Insert Tab': '\t', 'Space': ' '}.get(name, '\n'), editor)
        elif name in NATIVE_COMMANDS:
            return self._native(editor, name)
        elif name == 'Go to Page/Line':
            return self._go_to(editor)
        elif name == 'Search Next Punctuation':
            text, _, end = selection(editor)
            match = re.search(r'--|[,.!?:;]', text[end:])
            if not match:
                return 'There is no further punctuation.'
            select_text(editor, text, end + match.start(), end + match.end())
        elif name in ('Change A to THE WITNESS', 'Interrupted Q/A/C'):
            return self._speaker(editor, name)
        elif name == 'Number Conversion':
            from app.src.smart_number import convert_number
            return convert_number(editor)
        elif name in ('Spellcheck', 'Spelling Lookup', 'Resume Spellcheck'):
            from app.src.smart_spelling import check_spelling
            return check_spelling(editor, name)
        elif name == 'View Personal Dictionary':
            from app.src.smart_files import view_dictionary
            return view_dictionary(editor)
        elif name in ('Print File', 'Print Current Page'):
            from app.src.smart_files import print_pages
            return print_pages(editor, current=name == 'Print Current Page')
        elif name in ('Include File', 'Break to File'):
            from app.src.smart_files import include_file, break_to_file
            return include_file(editor) if name == 'Include File' else break_to_file(self.view, editor)

    def _move(self, editor, name):
        select = name.startswith('Select ')
        target = name.split(' ', 1)[1]
        cursor = editor.textCursor()
        mode = QTextCursor.KeepAnchor if select else QTextCursor.MoveAnchor
        if name in ('Select Word Left', 'Select Word Right'):
            text = editor.toPlainText()
            pos = utf16_index(text, cursor.position())
            right = name.endswith('Right')
            # Reversing the direction unmarks one word, including the space
            # which joined it to the rest of the selection.
            shrinking = cursor.hasSelection() and (cursor.position() < cursor.anchor()) == right
            if right:
                word = next((m for m in WORD.finditer(text, pos) if m.end() > pos), None)
                dest = word.end() if word else len(text)
                if shrinking:
                    while dest < len(text) and text[dest].isspace():
                        dest += 1
            else:
                word = next(reversed(list(WORD.finditer(text, 0, pos))), None)
                dest = word.start() if word else 0
                if shrinking:
                    while dest and text[dest-1].isspace():
                        dest -= 1
            qt = units(text[:dest])
            if shrinking:
                qt = min(qt, cursor.anchor()) if right else max(qt, cursor.anchor())
            set_position(editor, qt, select=True)
            if hasattr(editor, '_snap_native_cursor'):
                editor._snap_native_cursor()
            return
        if name in ('Move Word End', 'Move to End of Current Word'):
            text, pos, _ = selection(editor)
            word = current_word(text, pos)
            if word:
                set_position(editor, units(text[:word.end()]))
            return
        if target in ('Line Begin', 'Line Home', 'Line End'):
            block = cursor.block()
            line = block.layout().lineForTextPosition(cursor.positionInBlock())
            if line.isValid():
                start = block.position() + line.textStart()
                if target == 'Line End':
                    raw = block.text().encode('utf-16-le')
                    row = raw[2*line.textStart():2*(line.textStart()+line.textLength())].decode('utf-16-le')
                    start += units(row.rstrip())
                set_position(editor, start, select=select)
                if hasattr(editor, '_snap_native_cursor'):
                    editor._snap_native_cursor()
            return
        if target in MOVES or target in ('Up', 'Down'):
            old = cursor.position()
            move = MOVES.get(target) or (QTextCursor.Up if target == 'Up' else QTextCursor.Down)
            cursor.movePosition(move, mode)
            revision = revision_of(editor)
            if revision:
                pos = utf16_index(revision.text, cursor.position())
                atom = next((e for e in revision.elements if e.start < pos < e.end), None)
                if atom:
                    pos = atom.end if cursor.position() > old else atom.start
                    cursor.setPosition(units(revision.text[:pos]), mode)
            editor.setTextCursor(cursor)
            editor.ensureCursorVisible()
            return
        rows, index = page_row(editor)
        if not rows:
            return
        row = rows[index]
        offset = min(units(row.text), max(0, cursor.position() - row.position))
        if name == 'Down One Line and Move to Beginning of Line':
            index = min(index + 1, len(rows) - 1)
            offset = 0
        elif target in ('Page Up', 'Page Down'):
            indices = [i for i, line in enumerate(rows) if line.page == row.page]
            index = indices[0 if target.endswith('Up') else -1]
            offset = 0
        else:
            height = max(1, editor.viewport().height())
            if target.startswith('Screen Page'):
                y = row.y + (height if target.endswith('Down') else -height)
            else:
                y = editor.verticalScrollBar().value() + (height - 1 if target.endswith('Bottom') else 0)
            index = min(range(len(rows)), key=lambda i: abs(rows[i].y - y))
        line = rows[index]
        position = line.position + min(offset, units(line.text))
        # Preserve valid Unicode cursor positions when the adjacent row contains emoji.
        line_bytes = line.text.encode('utf-16-le')[:(position-line.position)*2]
        if line_bytes and 0xD800 <= int.from_bytes(line_bytes[-2:], 'little') <= 0xDBFF:
            position -= 1
        set_position(editor, position, select=select)
        if hasattr(editor, '_snap_native_cursor'):
            editor._snap_native_cursor()

    def _window(self, name):
        window = self.view.window()
        if not hasattr(window, 'views'):
            return 'Open this transcript in a BABABUI document tab.'
        if name == 'Open File':
            path, _ = QFileDialog.getOpenFileName(window, 'Open CaseCAT working project', '',
                                                  'BABABUI projects (*.bababui)')
            if not path:
                raise CommandCancelled()
            window.open_file(path)
        elif name == 'Save File':
            if not window.save_view(self.view):
                raise CommandCancelled()
        else:
            views = [v for v in window.views() if v.document.native]
            if self.view in views:
                step = -1 if '(Reverse)' in name else 1
                window.tabs.setCurrentWidget(views[(views.index(self.view) + step) % len(views)])

    def _search(self, editor, name):
        cursor = editor.textCursor()
        selected = cursor.selectedText().replace('\u2029', '\n')
        if name in ('Search', 'Replace') or not self.query:
            query, ok = QInputDialog.getText(editor, name, 'Find text', text=selected or self.query)
            if not ok or not query:
                raise CommandCancelled()
            self.query = query
        if name == 'Replace':
            replacement, ok = QInputDialog.getText(editor, name, 'Replace with', text=self.replacement)
            if not ok:
                raise CommandCancelled()
            self.replacement = replacement
        backward = name == 'Search Previous'
        doc = editor.document()
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlags()
        if name == 'Replace' and selected.casefold() == self.query.casefold():
            found = cursor
        else:
            found = doc.find(self.query, cursor, flags)
            if found.isNull():
                found = doc.find(self.query, doc.characterCount() - 1 if backward else 0, flags)
        if found.isNull():
            return f'Could not find “{self.query}”.'
        editor.setTextCursor(found)
        editor.ensureCursorVisible()
        if name == 'Replace':
            _, start, end = selection(editor)
            return replace_text(editor, start, end, self.replacement)

    def _go_to(self, editor):
        rows, index = page_row(editor)
        if not rows:
            return 'This transcript has no printed lines.'
        value, ok = QInputDialog.getText(editor, 'Go to Page/Line', 'Page and line',
                                         text=f'{rows[index].page}/{rows[index].number}')
        if not ok:
            raise CommandCancelled()
        match = re.fullmatch(r'\s*(\d+)(?:[ /:.,]+(\d+))?\s*', value)
        if match:
            page, line = int(match[1]), int(match[2] or 1)
            row = next((r for r in rows if r.page == page and r.number == line), None)
            if row:
                set_position(editor, row.position)
                return
        return 'Enter a printed page and line number from this transcript.'

    def _paragraph(self, editor, prefix):
        text, start, end = selection(editor)
        return replace_text(editor, start, end, ('\n' if start and text[start-1] != '\n' else '') + prefix,
                            delete_atoms=True)

    def _colloquy(self, editor, label=''):
        revision = revision_of(editor)
        if not revision:
            return self._paragraph(editor, '     ' + label)
        text, start, end = selection(editor)
        old = editor.native_element_at_cursor()
        if old and old.kind == 'symbol' and end <= old.end:
            start, end = old.start, old.end
        start, end = revision.atomic_range(start, end)
        prefix = '\n' if start and text[start-1] != '\n' else ''
        revision = revision._replace(start, end, prefix + '     ' + label)
        pos = start + len(prefix)
        marker = NativeElement(pos, pos+5, 'symbol', '160400', 'Colloquy')
        kept = [e for e in revision.elements if e.end <= pos or e.start >= marker.end]
        updated = replace(revision, elements=tuple(sorted([*kept, marker], key=lambda e: e.start)))
        editor.apply_native_revision(updated, marker.end + len(label), edit_range=(start, end))

    def _center(self, editor):
        from PySide6.QtCore import Qt
        revision = revision_of(editor)
        if not revision:
            editor.setAlignment(Qt.AlignHCenter)
            return
        text, start, end = selection(editor)
        first = text.rfind('\n', 0, start) + 1
        starts = [first, *(m.end() + start for m in re.finditer('\n', text[start:end]) if m.end()+start < end)]
        elements = list(revision.elements)
        existing = {e.start for e in elements if e.kind == 'symbol' and e.name == 'Center Justify'}
        elements.extend(NativeElement(p, p, 'symbol', CENTER_JUSTIFY.hex(), 'Center Justify')
                        for p in starts if p not in existing)
        updated = replace(revision, elements=tuple(sorted(elements, key=lambda e: (e.start, e.end))))
        if updated != revision:
            editor.apply_native_revision(updated, end, edit_range=(start, end))

    def _cycle_punctuation(self, editor, name):
        text, pos, _ = selection(editor)
        if name == 'Change Last Question Mark to Period':
            index = text.rfind('?')
            if index < 0:
                return 'There is no question mark in this transcript.'
            return apply_punctuation(editor, text, index, '.')
        rows, index = page_row(editor)
        if not rows:
            return
        row = rows[index]
        start = utf16_index(text, row.position)
        end = start + len(row.text)
        if name == 'Toggle Paragraph Ending Punctuation':
            end = text.find('\n', pos)
            end = len(text) if end < 0 else end
            start = text.rfind('\n', 0, pos) + 1
        all_marks = name == 'Toggle All Punctuation'
        options = ('.', '?', ',', '--', '', ':', ';', '!') if all_marks else ('.', '?', '!', '--', '')
        pattern = r'--|[.,?:;!]' if all_marks else r'--|[.?!]'
        cursor_state = (editor, name, editor.document().revision(), editor.textCursor().position())
        if self.last_toggle and self.last_toggle[:4] == cursor_state:
            index, mark = self.last_toggle[4:]
        else:
            scan_start = pos if all_marks else start
            matches = list(re.finditer(pattern, text[scan_start:end]))
            if not matches:
                return 'There is no punctuation in this passage to cycle.'
            match = matches[0] if all_marks else matches[-1]
            mark = match[0]
            index = scan_start + match.start()
            while mark == '--' and index > start and text[index-1] == ' ':
                index -= 1
        replacement = options[(options.index(mark) + 1) % len(options)]
        error = apply_punctuation(editor, text, index, replacement)
        if not error:
            set_position(editor, cursor_state[-1])
            self.last_toggle = (editor, name, editor.document().revision(), editor.textCursor().position(),
                                index, replacement)
        return error

    def _native(self, editor, name):
        revision = revision_of(editor)
        if revision is None:
            return 'This command needs a native transcript page.'
        if name == 'Insert Format Symbol Dialog':
            if editor.choose_native_symbol() is False:
                raise CommandCancelled()
            return
        if name == 'Reveal Codes':
            from app.src.smart_files import reveal_codes
            return reveal_codes(editor)
        if name == 'View Vertical Notes':
            from app.src.smart_files import vertical_notes
            return vertical_notes(editor)
        text, start, end = selection(editor)
        if name == 'Fill In Field':
            if not any(e.kind == 'field' and e.start <= start < e.end for e in revision.elements):
                return 'Place the cursor on a native field.'
            if editor.edit_native_field() is False:
                raise CommandCancelled()
            return
        empty_fields = [e for e in revision.elements if e.kind == 'field' and not e.value]
        if name == 'Scan and Fill in Next Field':
            while True:
                field = next((e for e in empty_fields if e.start >= start), None)
                if not field:
                    return 'There are no further empty fields.'
                set_position(editor, units(revision.text[:field.start]))
                if editor.fill_native_field(field.name) is False:
                    raise CommandCancelled()
                updated = revision_of(editor)
                if updated == revision:
                    return
                revision = updated
                empty_fields = [e for e in revision.elements if e.kind == 'field' and not e.value]
                start = field.start
        stops = [e.start for e in empty_fields]
        stops.extend(m.start() for m in re.finditer(r'(?<!\S)\^(?=\s|$)', text))
        matches = [p for p in stops if p < start] if name == 'Scan Backward' else [p for p in stops if p > start]
        if not matches:
            return 'No further empty fields or conflict markers in this direction.'
        set_position(editor, units(text[:(max(matches) if name == 'Scan Backward' else min(matches))]))

    def _speaker(self, editor, name):
        text, pos, _ = selection(editor)
        start = text.rfind('\n', 0, pos) + 1
        pattern = re.compile(r"(?m)^     (?:(?P<qa>[QA])    |(?P<speaker>[\w .’'-]+:) *)")
        current = pattern.match(text, start)
        if not current:
            return 'Place the cursor in a question, answer, or speaker paragraph.'
        if name == 'Change A to THE WITNESS':
            if current['qa'] != 'A':
                return 'Place the cursor in an answer paragraph.'
            select_text(editor, text, start, current.end())
            return self._colloquy(editor, 'THE WITNESS:  ')
        label = current['qa'] or current['speaker']
        following = next((m for m in pattern.finditer(text, current.end())
                          if (m['qa'] or m['speaker']) == label), None)
        if not following:
            return 'There is no later matching speaker paragraph.'
        first_end = text.find('\n', current.end())
        boundary = first_end
        while boundary > current.end() and text[boundary - 1] in ' .?!':
            boundary -= 1
        word = WORD.match(text, following.end())
        after = following.end()
        # Both edits must remain independent of any intervening native speaker fields.
        revision = revision_of(editor)
        mark = '-- ' + (word[0][0].lower() if word and word[0] != 'I' else '')
        marked_end = after + int(bool(word and word[0] != 'I'))
        if revision:
            for a, b in ((after, marked_end), (boundary, first_end)):
                if any(a < e.end and b > e.start for e in revision.elements):
                    return 'This interruption crosses a native field.'
            editor.apply_native_revision(revision._replace(after, marked_end, mark), after + len(mark),
                                         edit_range=(after, marked_end))
            updated = revision_of(editor)
            editor.apply_native_revision(updated._replace(boundary, first_end, ' --'), pos,
                                         edit_range=(boundary, first_end))
        else:
            block = editor.textCursor()
            block.beginEditBlock()
            try:
                replace_text(editor, after, marked_end, mark)
                replace_text(editor, boundary, first_end, ' --', caret=pos)
            finally:
                block.endEditBlock()
