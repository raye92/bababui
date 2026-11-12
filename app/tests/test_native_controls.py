"""CaseCAT-style field creation, filling, insertion, and atomic editing."""
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
import pytest

from app.src.casecat import archive, codec
from app.src.casecat.anchors import Revision
from app.src.casecat.fields import field_values
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_editor import native_window
from app.tests.test_native_fields import field_files, field_job


def open_fields(window, tmp_path):
    files = field_files()
    del files['jobs/example.wav']
    source = tmp_path/'fields.zip'
    source.write_bytes(zip_bytes(files))
    window.import_zip(0, source)
    return window.current


def test_uninserted_definition_survives_export_and_project_serialization(tmp_path):
    bundle, job = field_job()
    revision = job.revision.define_field('WITNESS', '')
    revision = revision.set_field('WITNESS', 'MS. WITNESS')
    assert revision.text == job.text
    assert Revision.from_dict(revision.to_dict()) == revision
    target = tmp_path/'defined.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    restored = codec.load_job(archive.inspect_archive(target), job.key)
    assert restored.text == job.text
    assert field_values(restored.revision)['WITNESS'] == 'MS. WITNESS'
    assert not any(e.name == 'WITNESS' for e in restored.revision.elements)


def test_definition_only_change_can_be_undone_and_redone(native_window, tmp_path):
    view = open_fields(native_window, tmp_path)
    before = view.document.native.original
    after = before.define_field('WITNESS', '')
    view.editor.apply_native_revision(after)
    assert view.document.native.original == after
    view.editor.undo()
    assert view.document.native.original == before
    view.editor.redo()
    assert view.document.native.original == after


def test_arrow_selection_and_delete_treat_names_as_one_field(native_window, tmp_path):
    view = open_fields(native_window, tmp_path)
    editor = view.editor
    before = view.document.native.original
    field = next(e for e in before.elements if e.kind == 'field')
    cursor = editor.textCursor()
    cursor.setPosition(field.start)
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key_Right)
    assert editor.textCursor().position() == field.end
    QTest.keyClick(editor, Qt.Key_Left, Qt.ShiftModifier)
    assert editor.textCursor().selectedText() == 'MS. OLD'
    QTest.keyClick(editor, Qt.Key_Delete)
    assert len([e for e in view.document.native.original.elements if e.kind == 'field']) == 1
    assert 'MS. OLD' in view.document.original
    editor.undo()
    assert view.document.native.original == before


def test_field_list_separates_creation_fill_and_insertion(native_window, tmp_path, monkeypatch):
    from app.src.native_dialogs import FillFieldDialog
    view = open_fields(native_window, tmp_path)
    editor = view.editor
    before = view.document.original
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)
    editor.insert_native_field()
    dialog = editor._field_dialog
    assert dialog.isVisible()
    dialog.new_button.click()
    QApplication.processEvents()
    name_item = dialog.table.item(dialog.table.currentRow(), 0)
    name_item.setText('WITNESS')
    assert field_values(view.document.native.original)['WITNESS'] == ''
    assert view.document.original == before
    monkeypatch.setattr(FillFieldDialog, 'get_value', lambda *args: ('MS. WITNESS', True))
    dialog.fill_button.click()
    assert field_values(view.document.native.original)['WITNESS'] == 'MS. WITNESS'
    assert view.document.original == before
    dialog.insert_button.click()
    assert view.document.original.endswith('MS. WITNESS')
    assert dialog.isVisible()
    dialog.close_after.setChecked(True)
    dialog.insert_button.click()
    assert view.document.original.endswith('MS. WITNESSMS. WITNESS')
    assert not dialog.isVisible()
    target = tmp_path/'controls.zip'
    view.document.export_casecat(target)
    restored = codec.load_job(archive.inspect_archive(target), 'jobs/example')
    assert len([e for e in restored.revision.elements if e.name == 'WITNESS']) == 2


def test_format_symbol_shortcut_selects_then_enter_accepts(native_window, tmp_path):
    from app.src.native_dialogs import FormatSymbolDialog
    view = open_fields(native_window, tmp_path)
    dialog = FormatSymbolDialog(view.editor)
    dialog.show()
    QTest.keyClick(dialog.table, Qt.Key_Q)
    assert dialog.symbol == 'Q' and dialog.isVisible()
    QTest.keyClick(dialog.table, Qt.Key_Return)
    assert dialog.result() == QDialog.Accepted


def test_changing_symbol_keeps_body_and_moves_caret_after_symbol(native_window, tmp_path, monkeypatch):
    from app.src.native_dialogs import FormatSymbolDialog
    view = open_fields(native_window, tmp_path)
    before = view.document.native.original
    start = before.text.index('     Q    ')
    cursor = view.editor.textCursor()
    cursor.setPosition(start)
    view.editor.setTextCursor(cursor)
    def choose_answer(dialog):
        assert dialog.symbol == 'Q'
        dialog.table.setCurrentCell(0, 0)
        return QDialog.Accepted
    monkeypatch.setattr(FormatSymbolDialog, 'exec', choose_answer)
    view.editor.change_native_symbol()
    assert view.document.original == before.text.replace('     Q    ', '     A    ')
    assert view.editor.textCursor().position() == start + 10
    view.editor.undo()
    assert view.document.native.original == before


def test_typing_over_selected_field_replaces_occurrence_not_definition(native_window, tmp_path):
    view = open_fields(native_window, tmp_path)
    field = next(e for e in view.document.native.original.elements if e.kind == 'field')
    cursor = view.editor.textCursor()
    cursor.setPosition(field.start)
    cursor.setPosition(field.end, QTextCursor.KeepAnchor)
    view.editor.setTextCursor(cursor)
    QTest.keyClicks(view.editor, 'TEXT')
    revision = view.document.native.original
    assert revision.text.startswith('BY TEXT:')
    assert field_values(revision)['EZ SPEAKER 01'] == 'MS. OLD'
    assert len([e for e in revision.elements if e.kind == 'field']) == 1


def test_clipboard_reuses_unused_destination_definition():
    from app.src.casecat.clipboard import selection_data, paste_revision
    _, job = field_job()
    destination = job.revision.define_field('WITNESS', 'DESTINATION NAME')
    source = job.revision.insert_field(len(job.text), 'WITNESS', 'SOURCE NAME')
    field = source.elements[-1]
    data = selection_data(source, field.start, field.end)
    result = paste_revision(destination, job.baseline, len(job.text), len(job.text), data)
    assert result.text.endswith('DESTINATION NAME')
    assert field_values(result)['WITNESS'] == 'DESTINATION NAME'


@pytest.mark.parametrize('newline', ['\r\n', '\r'])
def test_pasting_windows_newlines_over_a_field_keeps_model_and_editor_equal(native_window, tmp_path, newline):
    from PySide6.QtCore import QMimeData
    view = open_fields(native_window, tmp_path)
    before = view.document.native.original
    field = next(e for e in before.elements if e.kind == 'field')
    cursor = view.editor.textCursor()
    cursor.setPosition(field.start)
    cursor.setPosition(field.end, QTextCursor.KeepAnchor)
    view.editor.setTextCursor(cursor)
    data = QMimeData()
    data.setText('One' + newline + 'Two')
    view.editor.insertFromMimeData(data)
    expected = before.text[:field.start] + 'One\nTwo' + before.text[field.end:]
    assert view.document.original == view.editor.toPlainText() == expected
    view.editor.undo()
    assert view.document.native.original == before
    view.editor.redo()
    assert view.document.original == view.editor.toPlainText() == expected


def test_incoming_definition_only_changes_can_be_reviewed(native_window, tmp_path):
    view = open_fields(native_window, tmp_path)
    original = view.document.native.original
    view.toggle_view()
    proposed = original.define_field('WITNESS', 'MS. WITNESS')
    view.document.set_text('incoming', proposed.text, revision=proposed)
    view.toggle_view()
    assert view.diff_view.has_changes
    assert view.diff_view.changes[0].kind == 'metadata'
    view.review(0, True)
    assert view.document.native.original == proposed
    assert not view.diff_view.has_changes
    view.document.export_casecat(tmp_path/'accepted-fields.zip')
    restored = codec.load_job(archive.inspect_archive(tmp_path/'accepted-fields.zip'), 'jobs/example')
    assert field_values(restored.revision)['WITNESS'] == 'MS. WITNESS'


def test_incoming_definition_only_changes_can_be_rejected(native_window, tmp_path):
    view = open_fields(native_window, tmp_path)
    original = view.document.native.original
    view.toggle_view()
    view.incoming_editor.apply_native_revision(original.define_field('WITNESS', 'MS. WITNESS'))
    view.review(0, False)
    assert view.document.native.original == view.document.native.incoming == original
    assert not view.diff_view.has_changes


def test_original_cannot_discard_pending_field_review(native_window, tmp_path):
    view = open_fields(native_window, tmp_path)
    original = view.document.native.original
    view.toggle_view()
    proposed = original.define_field('WITNESS', 'MS. WITNESS')
    view.document.set_text('incoming', proposed.text, revision=proposed)
    view.toggle_view()
    assert view.editor.isReadOnly()
    assert native_window.edit_btn.isEnabled()
    assert view.active_editor() is None
    QTest.keyClicks(view.editor, 'X')
    assert view.document.native.original == original
    assert view.document.native.incoming == proposed
    view.review(0, False)
    assert not view.editor.isReadOnly()


def test_undo_refreshes_field_list_and_stale_name_edit_is_safe(native_window, tmp_path):
    view = open_fields(native_window, tmp_path)
    view.editor.insert_native_field()
    dialog = view.editor._field_dialog
    dialog.new_field()
    item = dialog.table.item(dialog.table.currentRow(), 0)
    old_name = item.data(Qt.UserRole)
    dialog.table.closePersistentEditor(item)
    view.editor.undo()
    item.setText('RENAMED')
    assert 'RENAMED' not in field_values(view.document.native.original)
    dialog.refresh()
    assert old_name not in [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]


def test_fill_command_works_on_a_selected_field(native_window, tmp_path, monkeypatch):
    from app.src.native_dialogs import FillFieldDialog
    view = open_fields(native_window, tmp_path)
    field = next(e for e in view.document.native.original.elements if e.kind == 'field')
    cursor = view.editor.textCursor()
    cursor.setPosition(field.start)
    cursor.setPosition(field.end, QTextCursor.KeepAnchor)
    view.editor.setTextCursor(cursor)
    monkeypatch.setattr(FillFieldDialog, 'get_value', lambda *args: ('MS. FILLED', True))
    view.editor.edit_native_field()
    assert view.document.original.count('MS. FILLED') == 2


def test_field_dialog_closes_when_editor_is_hidden_for_review(native_window, tmp_path):
    view = open_fields(native_window, tmp_path)
    view.editor.insert_native_field()
    dialog = view.editor._field_dialog
    view.receive(view.document.original.replace('Question?', 'New question?'), [])
    proposal = view.document.native.incoming
    assert not dialog.isVisible()
    dialog.new_field()
    assert view.document.native.incoming == proposal


@pytest.mark.parametrize('key,at_end', [(Qt.Key_Backspace, True), (Qt.Key_Delete, False)])
def test_word_delete_removes_field_occurrence_not_linked_value(native_window, tmp_path, key, at_end):
    view = open_fields(native_window, tmp_path)
    original = view.document.native.original
    field = next(e for e in original.elements if e.kind == 'field')
    cursor = view.editor.textCursor()
    cursor.setPosition(field.end if at_end else field.start)
    view.editor.setTextCursor(cursor)
    QTest.keyClick(view.editor, key, Qt.ControlModifier)
    revision = view.document.native.original
    assert field_values(revision)['EZ SPEAKER 01'] == 'MS. OLD'
    assert len([e for e in revision.elements if e.kind == 'field']) == 1
