"""Portable Case CATalyst keyboard assignments and Qt key normalization."""
import csv
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import json
from pathlib import Path, PureWindowsPath
import re

from PySide6.QtCore import Qt

from app.src.smart_key_macros import read_macro


_DEFAULT = Path(__file__).with_name('smart_keys_default.json')
_KEY = r'(?:(?:Shift|Ctrl|Alt|Meta)\+)*(?:<[^<>\r\n]+>|[^\s])'
_ROW = re.compile(rf'(?P<key>{_KEY})=(?P<value>.*?)(?:;(?P<meta>".*))?', re.IGNORECASE)
_NAMED = {
    Qt.Key_Backspace: 'Backspace', Qt.Key_Tab: 'Tab', Qt.Key_Backtab: 'Tab',
    Qt.Key_Return: 'Enter', Qt.Key_Enter: 'Enter', Qt.Key_Escape: 'Escape',
    Qt.Key_Space: 'Space', Qt.Key_PageUp: 'Page Up', Qt.Key_PageDown: 'Page Down',
    Qt.Key_End: 'End', Qt.Key_Home: 'Home', Qt.Key_Left: 'Left', Qt.Key_Up: 'Up',
    Qt.Key_Right: 'Right', Qt.Key_Down: 'Down', Qt.Key_Insert: 'Insert', Qt.Key_Delete: 'Delete',
    **{int(Qt.Key_F1) + i: f'F{i + 1}' for i in range(24)},
}
_SHIFTS = dict(zip('~!@#$%^&*()_+{}|:"<>?', "`1234567890-=[]\\;',./"))
_MODIFIERS = ((Qt.ControlModifier, 'Ctrl'), (Qt.AltModifier, 'Alt'),
              (Qt.ShiftModifier, 'Shift'), (Qt.MetaModifier, 'Meta'))


def event_key(event):
    """Use the physical base key for shifted US punctuation in a CATalyst map."""
    k, mods = event.key(), event.modifiers()
    if k == Qt.Key_Backtab:
        mods |= Qt.ShiftModifier
    name = _NAMED.get(k)
    keypad = bool(mods & Qt.KeypadModifier)
    if name is not None:
        key = f'<{name}>'
    elif 33 <= k <= 126:
        char = chr(k).lower()
        if keypad:
            key = f'<Keypad {char}>'
        elif mods & Qt.ShiftModifier:
            key = _SHIFTS.get(char, char)
        else:
            key = char
    else:
        return ''
    return ''.join(label + '+' for flag, label in _MODIFIERS if mods & flag) + key


def _canonical_key(key):
    if not isinstance(key, str) or not re.fullmatch(_KEY, key, re.I):
        raise ValueError('Invalid key name.')
    mods = set()
    while match := re.match(r'(Ctrl|Shift|Alt|Meta)\+', key, re.I):
        modifier = match[1].title()
        if modifier in mods:
            raise ValueError('Duplicate modifier.')
        mods.add(modifier)
        key = key[match.end():]
    if key.startswith('<') and len(key) > 1:
        label = key[1:-1].title()
        if label.startswith('Keypad '):
            label = 'Keypad ' + label[7:]
        key = '<' + label + '>'
    else:
        key = key.lower()
    return ''.join(label + '+' for _, label in _MODIFIERS if label in mods) + key


@dataclass(frozen=True)
class Binding:
    key: str
    kind: str
    value: str
    steps: tuple = ()
    reason: str = ''
    note: str = ''


@dataclass(frozen=True)
class SmartKeyProfile:
    name: str
    bindings: tuple

    def __post_init__(self):
        by_key = {binding.key: binding for binding in self.bindings}
        if not by_key or len(by_key) != len(self.bindings):
            raise ValueError('Keyboard contains duplicate keys or no assignments.')
        object.__setattr__(self, '_by_key', by_key)

    def get(self, key):
        return self._by_key.get(key)

    def to_dict(self):
        records = []
        for binding in self.bindings:
            row = asdict(binding)
            for field in ('steps', 'reason', 'note'):
                if not row[field]:
                    del row[field]
            records.append(row)
        return {'version': 1, 'name': self.name, 'bindings': records}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('name'), str):
            raise ValueError('Invalid keyboard profile.')
        if not isinstance(data.get('bindings'), list):
            raise ValueError('Invalid keyboard assignments.')
        bindings = []
        for row in data['bindings']:
            if not isinstance(row, dict):
                raise ValueError('Invalid keyboard row.')
            key = _canonical_key(row.get('key'))
            kind, value = row.get('kind'), row.get('value')
            if kind not in ('command', 'literal', 'macro', 'unassigned') or not isinstance(value, str):
                raise ValueError(f'{key} has an invalid assignment.')
            raw_steps = row.get('steps', [])
            if not isinstance(raw_steps, (tuple, list)) or any(
                    not isinstance(step, (tuple, list)) or len(step) != 2
                    or step[0] not in ('literal', 'command') or not isinstance(step[1], str)
                    or not step[1] for step in raw_steps):
                raise ValueError(f'{key} has invalid macro instructions.')
            steps = tuple(tuple(step) for step in raw_steps)
            reason, note = row.get('reason', ''), row.get('note', '')
            if not isinstance(reason, str) or not isinstance(note, str):
                raise ValueError(f'{key} has an invalid status.')
            if kind == 'macro':
                if not _is_macro_name(value) or bool(steps) == bool(reason):
                    raise ValueError(f'{key} has an incomplete macro.')
            elif steps or reason or note or (kind == 'unassigned') != (value == ''):
                raise ValueError(f'{key} has an inconsistent assignment.')
            bindings.append(Binding(key, kind, value, steps, reason, note))
        return cls(data['name'], tuple(bindings))

    def relink(self, key, path):
        original = self.get(key)
        if not original or original.kind != 'macro':
            raise ValueError('Select a macro assignment to relink.')
        path = Path(path)
        if path.suffix.casefold() != '.sgmac':
            raise ValueError('Choose a .sgmac file.')
        steps, reason = read_macro(path)
        updated = replace(original, steps=steps, reason=reason, note=f'Linked to {path.name}')
        return replace(self, bindings=tuple(updated if b == original else b for b in self.bindings))


@lru_cache(maxsize=1)
def default_profile():
    return SmartKeyProfile.from_dict(json.loads(_DEFAULT.read_text(encoding='utf-8')))


def _is_macro_name(name):
    return (name == PureWindowsPath(name).name and name.casefold().endswith('.sgmac')
            and not any(c in name for c in '<>:"/\\|?*') and not PureWindowsPath(name).is_reserved())


def _macro_binding(key, reference, files):
    name = PureWindowsPath(reference).name
    if not _is_macro_name(name):
        raise ValueError('Invalid .sgmac reference.')
    if path := files.get(name.casefold()):
        steps, reason = read_macro(path)
        return Binding(key, 'macro', name, steps, reason)
    if key == 'Ctrl+1' and name.casefold() == 'search next punctuation.sgmac':
        return Binding(key, 'macro', name, (('command', 'Search Next Punctuation'),),
                       note='Fallback: find the next punctuation mark. Relink to use the recorded macro.')
    return Binding(key, 'macro', name, reason=f'{name} is missing. Relink its .sgmac file.')


def import_profile(keyboard_path, macros_dir=None):
    path = Path(keyboard_path)
    if path.suffix.casefold() != '.sgkbd':
        raise ValueError('Choose a .sgkbd keyboard map.')
    data = path.read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        source = data.decode('utf-16')
    else:
        try:
            source = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            source = data.decode('cp1252')
    if '\0' in source:
        raise ValueError('Invalid keyboard file encoding.')
    folder = Path(macros_dir) if macros_dir is not None else path.parent / 'Macros'
    files = {}
    if macros_dir is not None or folder.exists():
        for candidate in folder.iterdir():
            if candidate.suffix.casefold() == '.sgmac' and candidate.is_file():
                files[candidate.name.casefold()] = candidate
    bindings = []
    for n, line in enumerate(source.splitlines(), 1):
        if not line:
            continue
        match = _ROW.fullmatch(line)
        if not match:
            raise ValueError(f'Invalid keyboard assignment on line {n}.')
        try:
            key = _canonical_key(match['key'])
            value = match['value']
            metadata = next(csv.reader([match['meta']], strict=True)) if match['meta'] else []
            if len(metadata) not in (0, 1, 3) or (len(metadata) == 3 and not metadata[1].isdigit()):
                raise ValueError('Invalid assignment metadata.')
            if value == '[Play Macro]':
                binding = _macro_binding(key, metadata[0] if metadata else '', files)
            elif value.startswith('[') and len(value) > 1:
                if not re.fullmatch(r'\[[^\[\]]+\]', value):
                    raise ValueError('Invalid bracketed command name.')
                binding = Binding(key, 'command', value[1:-1])
            else:
                binding = Binding(key, 'literal' if value else 'unassigned', value)
        except (ValueError, csv.Error) as exc:
            raise ValueError(f'Line {n}: {exc}') from exc
        bindings.append(binding)
    return SmartKeyProfile(path.stem, tuple(bindings))
# These commands use the document or window rather than an editor operation.
WINDOW_COMMANDS = frozenset(('Change Keyboard Mode', 'Default Keyboard', 'Play Last Macro',
                             'Play Audio', 'Stop Audio'))


def binding_dependency(binding):
    from app.src.smart_commands import command_dependency

    if binding.reason:
        return binding.reason
    steps = binding.steps if binding.kind == 'macro' else ((binding.kind, binding.value),)
    for kind, value in steps:
        if kind == 'command' and binding.kind == 'macro' and value in ('Play Macro', 'Play Last Macro', 'Undo', 'Redo'):
            return f'This recording requires nested macro or history playback ({value}).'
        if kind == 'command' and value not in WINDOW_COMMANDS:
            if reason := command_dependency(value):
                return f'{value}: {reason}' if binding.kind == 'macro' else reason
    return ''
