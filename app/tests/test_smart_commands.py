"""Offline Smart Keys act on the visible transcript and its Qt undo history."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QApplication

from app.src.native_editor import NativeTranscriptEditor
from app.tests.test_native_editor import native_window


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    widget = NativeTranscriptEditor(QFont('Courier New'))
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def command(name, editor):
    from app.src.smart_commands import SmartCommands
    return SmartCommands(editor).execute(name, editor)


def at(editor, position, end=None):
    cursor = editor.textCursor()
    cursor.setPosition(position)
    if end is not None:
        cursor.setPosition(end, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)


def test_word_swap_keeps_punctuation_and_undo(editor):
    editor.setPlainText('She would doing, start the dishes.')
    at(editor, 11)
    assert not command('Word Swap', editor)
    assert editor.toPlainText() == 'She would start, doing the dishes.'
    editor.undo()
    assert editor.toPlainText() == 'She would doing, start the dishes.'


def test_delete_word_inside_word_and_marked_word(editor):
    editor.setPlainText('A brown dog.')
    at(editor, 4)
    assert not command('Delete Word', editor)
    assert editor.toPlainText() == 'A dog.'
    editor.undo()
    at(editor, 2, 7)
    assert not command('Delete Word', editor)
    assert editor.toPlainText() == 'A  dog.'


def test_delete_printed_line_and_move_down_at_end(editor):
    editor.setPlainText(('long word ' * 17) + '\nLast')
    rows = editor.page_lines()
    assert len(rows) >= 3
    at(editor, rows[1].position + 2)
    original = editor.toPlainText()
    assert not command('Delete Entire Line', editor)
    assert editor.toPlainText() == original[:rows[1].position] + original[rows[2].position:]
    editor.undo()
    at(editor, len(original))
    assert not command('Down One Line and Move to Beginning of Line', editor)
    assert editor.textCursor().position() == rows[-1].position


def test_cap_cycle_and_smart_punctuation(editor):
    editor.setPlainText('some words')
    for expected in ('Some words', 'SOME words', 'some words'):
        at(editor, 0)
        assert not command('Cap/Uncap', editor)
        assert editor.toPlainText() == expected
    at(editor, 2)
    assert not command('Insert Period After Word', editor)
    assert editor.toPlainText() == 'some.  Words'


def test_read_only_editor_can_select_but_cannot_edit(editor):
    editor.setPlainText('one two')
    editor.setReadOnly(True)
    assert command('Word Swap', editor)
    assert not command('Select Word Right', editor)
    assert editor.textCursor().selectedText().strip() == 'one'
    assert editor.toPlainText() == 'one two'


def test_number_conversion_offers_distinct_formats_for_the_marked_number(editor, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    editor.setPlainText('I counted two hundred thirty-four total.')
    at(editor, 10, 33)
    choices = []
    def choose(parent, title, label, options, *args):
        choices.extend(options)
        return '234', True
    monkeypatch.setattr(QInputDialog, 'getItem', choose)
    assert not command('Number Conversion', editor)
    assert editor.toPlainText() == 'I counted 234 total.'
    assert '234th' in choices


def test_include_inserts_text_before_caret_and_undoes(editor, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    path = tmp_path / 'passage.txt'
    path.write_text('first\nsecond ', encoding='utf-8')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    editor.setPlainText('A word')
    at(editor, 2)
    assert not command('Include File', editor)
    assert editor.toPlainText() == 'A first\nsecond word'
    editor.undo()
    assert editor.toPlainText() == 'A word'


def test_search_remembers_query_in_both_directions(editor, monkeypatch):
    from app.src.smart_commands import SmartCommands
    from PySide6.QtWidgets import QInputDialog
    state = SmartCommands(editor)
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('word', True))
    editor.setPlainText('word WORD more word')
    for command_name, start in [('Search', 0), ('Next Search', 5), ('Search Previous', 0)]:
        assert not state.execute(command_name, editor)
        assert editor.textCursor().selectionStart() == start


def test_spelling_lookup_uses_offline_suggestions(editor, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    def choose(parent, title, prompt, options, *args):
        assert 'example' in options
        return 'example', True
    editor.setPlainText('An exampel today.')
    at(editor, 4)
    monkeypatch.setattr(QInputDialog, 'getItem', choose)
    assert not command('Spelling Lookup', editor)
    assert editor.toPlainText() == 'An example today.'


@pytest.mark.parametrize('word,suffix,result', [('study','s','studies'), ('hope','ing','hoping'), ('stop','ed','stopped')])
def test_suffix_spelling(editor, word, suffix, result):
    editor.setPlainText(word)
    assert not command('Add Suffix -' + suffix, editor)
    assert editor.toPlainText() == result


def test_select_word_right_excludes_separator_and_extends_by_words(editor):
    editor.setPlainText('one two three')
    assert not command('Select Word Right', editor)
    assert editor.textCursor().selectedText() == 'one'
    assert not command('Select Word Right', editor)
    assert editor.textCursor().selectedText() == 'one two'
    assert not command('Select Word Left', editor)
    assert editor.textCursor().selectedText() == 'one'


def test_h_macro_inserts_hyphen_at_the_join(editor):
    editor.setPlainText('part time work')
    at(editor, 5)
    assert not command('Delete Backward', editor)
    assert not command('Insert Hyphen', editor)
    assert editor.toPlainText() == 'part-time work'


def test_colloquy_insertion_exports_a_native_symbol(native_window, tmp_path):
    from app.tests.test_native_casecat import zip_bytes
    from app.tests.test_native_structure import container_files
    from app.src.casecat import archive, codec
    source = tmp_path / 'source.zip'
    source.write_bytes(zip_bytes(container_files()))
    native_window.import_zip(0, source)
    view = native_window.current
    editor = view.editor
    at(editor, len(view.document.original))
    assert not command('Insert Colloquy', editor)
    assert editor.toPlainText().endswith('     ')
    dest = tmp_path / 'colloquy.zip'
    view.document.export_casecat(dest)
    result = archive.inspect_archive(dest)
    job = codec.load_job(result, result.jobs[0])
    assert any(e.name == 'Colloquy' and e.raw == '160400' for e in job.revision.elements)




def test_native_word_swap_keeps_each_words_original_stroke_position(native_window, tmp_path):
    from app.src.casecat import archive, codec
    from app.tests.test_native_casecat import zip_bytes
    from app.tests.test_native_structure import container_files
    source = tmp_path / 'source.zip'
    source.write_bytes(zip_bytes(container_files(('First ', 'second ', 'third.'))))
    native_window.import_zip(0, source)
    editor = native_window.current.editor
    at(editor, 0)
    assert not command('Word Swap', editor)
    target = tmp_path / 'swap.zip'
    native_window.current.document.export_casecat(target)
    result = archive.inspect_archive(target)
    job = codec.load_job(result, result.jobs[0])
    assert [s.content.strip() for s in job.baseline.spans] == ['second', 'First', 'third.']


def test_vertical_tape_uses_job_key_order_and_one_row_per_stroke():
    from app.src.smart_files import tape_rows
    from types import SimpleNamespace
    notes = bytearray(640)
    notes[290:315] = b'STKPWHRAO*EUFRPBLGTSDZ#(!'
    stream = b'\x13\x01\x02' + bytes.fromhex('80000000 00000000 40300000 12345678')
    header = bytearray(1024)
    import struct
    struct.pack_into('<II', header, 532, 1024, len(stream))
    job = SimpleNamespace(notes_bytes=bytes(notes), native_bytes=bytes(header) + stream)
    header, rows = tape_rows(job)
    assert header.startswith('STKPWHR')
    assert rows[0].strip() == 'S'
    assert ''.join(rows[1].split()) == 'TEU'


@pytest.mark.parametrize('paragraph', [0, 1])
def test_center_justify_preserves_text_and_writes_catalyst_alignment_delta(native_window, tmp_path, paragraph):
    from PySide6.QtCore import Qt
    from app.src.casecat import archive, codec
    from app.src.casecat.anchors import Revision
    from app.tests.test_native_casecat import zip_bytes
    from app.tests.test_native_structure import container_files
    source = tmp_path / 'source.zip'
    source.write_bytes(zip_bytes(container_files(('First.', '\nSecond.'))))
    native_window.import_zip(0, source)
    view = native_window.current
    at(view.editor, (0, 8)[paragraph])
    before = view.document.native.original
    assert not command('Center Justify', view.editor)
    edited = view.document.native.original
    assert edited.text == before.text
    assert Revision.from_dict(edited.to_dict()) == edited
    assert view.editor.textCursor().blockFormat().alignment() == Qt.AlignHCenter
    target = tmp_path / 'center.zip'
    view.document.export_casecat(target)
    result = archive.inspect_archive(target)
    job = codec.load_job(result, result.jobs[0])
    assert job.text == before.text
    assert job.native_bytes.count(bytes.fromhex('1503030000000c0200')) == 1
    view.editor.undo()
    assert view.document.native.original == before


@pytest.mark.parametrize('name', ['Search', 'Go to Page/Line', 'Number Conversion', 'Include File'])
def test_cancelled_dialog_is_visible_to_macro_runner(editor, monkeypatch, name):
    from app.src.smart_commands import SmartCommands
    from PySide6.QtWidgets import QFileDialog, QInputDialog
    state = SmartCommands(editor)
    editor.setPlainText('123')
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **kw: ('', False))
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *a, **kw: ('', False))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **kw: ('', ''))
    assert not state.execute(name, editor)
    assert state.cancelled
    assert not state.execute('Move Right', editor)
    assert not state.cancelled


def test_old_saved_revision_keeps_source_colloquy_bytes_when_editing_elsewhere(tmp_path):
    from dataclasses import replace
    from app.src.casecat import archive, codec
    from app.tests.test_native_casecat import zip_bytes
    from app.tests.test_native_structure import container_files
    files = container_files(('\x16\x04\x00Speaker: Hello ', 'world.'))
    source = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(source, source.jobs[0])
    legacy = replace(job.revision, elements=tuple(e for e in job.revision.elements if e.name != 'Colloquy'))
    revision = legacy.replace(len(legacy.text)-1, len(legacy.text), '!')
    out = tmp_path/'legacy.zip'
    archive.export_zip(source, job.with_revision(revision), out)
    loaded = archive.inspect_archive(out)
    after = codec.load_job(loaded, loaded.jobs[0])
    assert any(e.raw == '160400' for e in after.revision.elements)


def test_print_current_page_renders_only_that_physical_page(editor, tmp_path):
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase, QPdfWriter
    import pymupdf
    from app.src.smart_files import render_pages
    font = Path('C:/Windows/Fonts/cour.ttf')
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    editor.setPlainText('\n'.join(f'Line {n}' for n in range(90)))
    rows = editor.page_lines()
    first = next(row for row in rows if row.page == 2)
    out = tmp_path / 'page.pdf'
    printer = QPdfWriter(str(out))
    assert not render_pages(editor, printer, rows, [2])
    del printer
    with pymupdf.open(out) as pages:
        assert len(pages) == 1
        assert first.text in pages[0].get_text()
        assert 'Line 0\n' not in pages[0].get_text()


def test_break_saves_passage_as_native_project_and_leaves_undo(native_window, tmp_path, monkeypatch):
    from app.src.documents import open_document
    from app.tests.test_native_casecat import zip_bytes
    from app.tests.test_native_structure import container_files
    from PySide6.QtWidgets import QFileDialog
    from app.src.smart_commands import SmartCommands
    source = tmp_path / 'break-source.zip'
    source.write_bytes(zip_bytes(container_files(('Alpha ', 'Beta ', 'Gamma.'))))
    native_window.import_zip(0, source)
    view = native_window.current
    before = view.document.native.original
    at(view.editor, 6)
    out = tmp_path / 'split.bababui'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(out), ''))
    assert not SmartCommands(view).execute('Break to File', view.editor)
    assert view.document.original == 'Alpha '
    other = open_document(out)
    assert other.original == 'Beta Gamma.'
    assert other.native.original.spans[-1].stroke_refs == (2,)
    view.editor.undo()
    assert view.document.native.original == before


def test_move_on_printed_lines_uses_current_layout_without_enumerating_each_page(editor, monkeypatch):
    editor.setPlainText('one two three four five ' * 18)
    rows = editor.page_lines()
    assert len(rows) >= 3
    at(editor, rows[1].position+2)
    def forbid_repagination():
        pytest.fail('Single-line cursor movement enumerated the entire transcript')
    monkeypatch.setattr(editor, 'page_lines', forbid_repagination)
    assert not command('Move Down', editor)
    assert not command('Move Line Begin', editor)
    assert editor.textCursor().position() == rows[2].position
    assert not command('Move Line End', editor)
    assert editor.textCursor().position() == rows[2].position + len(rows[2].text)


def test_repeated_toggle_targets_same_mark_without_moving_the_cursor(editor):
    from app.src.smart_commands import SmartCommands
    state = SmartCommands(editor)
    editor.setPlainText('Some words.  Then others?')
    for mark in ('?', ',', '--', '', ':'):
        assert not state.execute('Toggle All Punctuation', editor)
        assert editor.toPlainText().startswith('Some words' + (' ' if mark == '--' else '') + mark + ' ')
        assert editor.textCursor().position() == 0


def test_delete_word_at_document_end_keeps_the_last_word(editor):
    editor.setPlainText('last word')
    at(editor,len(editor.toPlainText()))
    assert not command('Delete Word', editor)
    assert editor.toPlainText() == 'last word'


def test_answer_to_witness_exports_a_real_colloquy(native_window, tmp_path):
    from app.src.casecat import archive, codec
    from app.tests.test_native_casecat import zip_bytes
    from app.tests.test_native_structure import container_files
    source = tmp_path / 'answer.zip'
    source.write_bytes(zip_bytes(container_files(('\x16\x03\x00Yes.', ' More.'))))
    native_window.import_zip(0, source)
    view = native_window.current
    at(view.editor, 12)
    assert not command('Change A to THE WITNESS', view.editor)
    target = tmp_path / 'witness.zip'
    view.document.export_casecat(target)
    result = archive.inspect_archive(target)
    after = codec.load_job(result, result.jobs[0])
    assert after.text == '     THE WITNESS:  Yes. More.'
    assert any(e.raw == '160400' for e in after.revision.elements)
