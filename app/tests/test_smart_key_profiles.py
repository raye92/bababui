import os
import struct
from collections import Counter

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeyEvent

from app.src import smart_keys


def write_macro(path, *records):
    header = bytearray(512)
    header[:8] = b'SGCAT32\0'
    struct.pack_into('<I', header, 288, 23)
    path.write_bytes(header + b''.join(struct.pack('<5I', *record) for record in records))


def instruction(code):
    return (0, 273, code, 0, 1)


def test_default_inventory_and_portable_recipes():
    profile = smart_keys.default_profile()
    assert Counter(b.kind for b in profile.bindings) == {
        'command': 145, 'macro': 35, 'literal': 58, 'unassigned': 128}
    assert sum(b.value == ' ' for b in profile.bindings) == 20
    assert len({b.value for b in profile.bindings if b.kind == 'command'}) == 107
    assert profile.get('k').steps == (('command', 'Move Down'), ('command', 'Move Line Begin'))
    assert profile.get('w').steps == (('command', 'Delete Entire Line'),)
    assert profile.get('Shift+d').steps == (('command', 'Add Suffix -ed'),)
    assert profile.get('Ctrl+1').note and profile.get('Ctrl+1').steps == (('command', 'Search Next Punctuation'),)
    assert profile.get('<F7>').reason and not profile.get('<F7>').steps
    assert profile.get('=').value == 'Word Definition Dictionary'
    assert profile.get('<Keypad +>').value == '+'


def test_import_uses_selected_folder_and_preserves_literal_space_and_empty(tmp_path):
    folder = tmp_path / 'Macros'
    folder.mkdir()
    write_macro(folder / 'PHRASE.SGMAC', instruction(577), instruction(654),
                instruction(ord('X')), instruction(ord('Y')), instruction(654))
    keyboard = tmp_path / 'My keys.sgkbd'
    keyboard.write_bytes(b'a=[Play Macro];"C:\\Private\\phrase.sgmac","123","2026-1-1"\r\n'
                         b'b= ;"","2","2026-1-1"\r\nc=\r\n==[Unknown Function]\r\n')
    profile = smart_keys.import_profile(keyboard)
    assert profile.get('a').value == 'phrase.sgmac'
    assert ('literal', 'XY') in profile.get('a').steps
    assert profile.get('b').value == ' '
    assert profile.get('c').kind == 'unassigned'
    assert profile.get('=').value == 'Unknown Function'
    assert 'Private' not in str(profile.to_dict())
    assert profile == smart_keys.SmartKeyProfile.from_dict(profile.to_dict())


def test_unrecognized_record_disables_whole_macro_and_relink_replaces_fallback(tmp_path):
    keyboard = tmp_path / 'keys.sgkbd'
    keyboard.write_text('Ctrl+1=[Play Macro];"Search Next Punctuation.SGMAC"')
    profile = smart_keys.import_profile(keyboard)
    assert profile.get('Ctrl+1').note
    source = tmp_path / 'different-name.sgmac'
    write_macro(source, instruction(ord('A')), instruction(65500))
    changed = profile.relink('Ctrl+1', source)
    assert '65500' in changed.get('Ctrl+1').reason
    assert not changed.get('Ctrl+1').steps
    write_macro(source, instruction(ord('B')))
    assert changed.relink('Ctrl+1', source).get('Ctrl+1').steps == (('literal', 'B'),)


@pytest.mark.parametrize('body', ['a=[Move Up]\na=1', 'line without assignment', 'a=[Play Macro]',
                                  'a=[Unclosed', 'a=[Play Macro];"unterminated'])
def test_reject_invalid_keyboard(tmp_path, body):
    keyboard = tmp_path / 'bad.sgkbd'
    keyboard.write_text(body)
    with pytest.raises(ValueError):
        smart_keys.import_profile(keyboard)


def test_reject_truncated_macro_even_after_valid_record(tmp_path):
    keyboard = tmp_path / 'keys.sgkbd'
    keyboard.write_text('k=[Play Macro];"K.sgmac"')
    macro = tmp_path / 'K.sgmac'
    write_macro(macro, instruction(258))
    macro.write_bytes(macro.read_bytes() + b'\0')
    with pytest.raises(ValueError):
        smart_keys.import_profile(keyboard, tmp_path)


@pytest.mark.parametrize(('qt_key','modifiers','text','want'), [
    (Qt.Key_A, Qt.NoModifier, 'a', 'a'),
    (Qt.Key_A, Qt.ShiftModifier, 'A', 'Shift+a'),
    (Qt.Key_Question, Qt.ShiftModifier, '?', 'Shift+/'),
    (Qt.Key_Plus, Qt.KeypadModifier, '+', '<Keypad +>'),
    (Qt.Key_1, Qt.ControlModifier | Qt.KeypadModifier, '', 'Ctrl+<Keypad 1>'),
    (Qt.Key_Space, Qt.NoModifier, ' ', '<Space>'),
    (Qt.Key_Backtab, Qt.ShiftModifier, '', 'Shift+<Tab>'),
])
def test_event_key(qt_key, modifiers, text, want):
    event = QKeyEvent(QEvent.KeyPress, qt_key, modifiers, text)
    assert smart_keys.event_key(event) == want
def test_settings_filter_import_failure_and_restore(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog
    from app.src.settings_page import SettingsPage

    app = QApplication.instance() or QApplication([])
    page = SettingsPage([], [])
    assert page.profile_table.rowCount() == 366
    assert not page.space_playback.isChecked()
    page.profile_search.setText('Search Next Punctuation')
    visible = [i for i in range(366) if not page.profile_table.isRowHidden(i)]
    assert len(visible) == 1
    assert page.profile_table.item(visible[0], 0).text() == 'Ctrl+1'
    assert 'fallback' in page.profile_table.item(visible[0], 2).text().lower()
    keyboard = tmp_path / 'Custom.sgkbd'
    keyboard.write_text('a=X\nb=Y')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(keyboard), ''))
    changes = []
    page.profileChanged.connect(changes.append)
    page.import_keyboard()
    assert len(changes) == 1 and changes[0].get('b').value == 'Y'
    keyboard.write_text('broken')
    page.import_keyboard()
    assert len(changes) == 1 and page.profile_table.rowCount() == 2
    assert page.profile_error.text()
    page.restore_defaults.click()
    assert len(changes) == 2 and page.profile_table.rowCount() == 366
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

def test_macro_status_preflights_every_recorded_step(tmp_path):
    keyboard = tmp_path / 'keys.sgkbd'
    keyboard.write_text('x=[Play Macro];"edit.sgmac"')
    path = tmp_path / 'edit.sgmac'
    write_macro(path, instruction(ord('!')), instruction(521))
    pending = smart_keys.import_profile(keyboard, tmp_path).get('x')
    assert 'dictionary' in smart_keys.binding_dependency(pending).lower()
    write_macro(path, instruction(ord('!')), instruction(513))
    pending = smart_keys.import_profile(keyboard, tmp_path).get('x')
    assert 'undo' in smart_keys.binding_dependency(pending).lower()
