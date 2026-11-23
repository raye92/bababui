"""Read the fixed records in Case CATalyst .sgmac files without replaying OS events."""
import hashlib
from pathlib import Path
import struct


# Identifiers recorded by the transcript editor's WM_COMMAND dispatcher.
_COMMANDS = {
    256: 'Move Left', 257: 'Move Right', 258: 'Move Down', 259: 'Move Up',
    260: 'Move Page Up', 261: 'Move Page Down', 262: 'Move Screen Page Up',
    263: 'Move Screen Page Down', 264: 'Move Line Begin', 265: 'Move Line End',
    266: 'Move Word Left', 267: 'Move Word Right', 268: 'Move Document Top',
    269: 'Move Document Bottom', 270: 'Move Screen Top', 271: 'Move Screen Bottom',
    272: 'Select Left', 273: 'Select Right', 274: 'Select Down', 275: 'Select Up',
    276: 'Select Page Up', 277: 'Select Page Down', 278: 'Select Screen Page Up',
    279: 'Select Screen Page Down', 280: 'Select Line Home', 281: 'Select Line End',
    282: 'Select Word Left', 283: 'Select Word Right', 284: 'Select Document Top',
    285: 'Select Document Bottom', 286: 'Select Screen Top', 287: 'Select Screen Bottom',
    512: 'Redo', 513: 'Undo', 514: 'Word Swap', 515: 'Copy', 516: 'Cut',
    517: 'Paste', 518: 'Restore Steno', 520: 'Replace', 521: 'D-Define',
    522: 'K-Define', 523: 'J-Define', 524: 'E-Define', 525: 'Undo Last Global',
    529: 'Play Last Macro', 537: 'Cap/Uncap', 563: 'Scan Forward',
    565: 'Insert Format Symbol Dialog', 568: 'Insert Answer', 574: 'Insert Cap Next',
    575: 'Insert Colloquy', 577: 'Insert Continuation Paragraph', 592: 'Insert New Line',
    594: 'Insert Parenthetical', 596: 'Insert Question', 610: 'Insert Tab',
    623: 'Delete Backward', 624: 'Delete Forward', 631: 'Search', 632: 'Next Search',
    637: 'Smart Period', 638: 'Smart Question', 639: 'Smart Exclamation',
    640: 'Smart Comma', 641: 'Smart Semicolon', 642: 'Smart Colon',
    643: 'Insert Hyphen', 644: 'Smart Remove Punctuation', 654: 'Change Keyboard Mode',
    656: "Insert Reporter's Dash", 666: 'Move Left Word Begin', 671: 'Delete Entire Table',
    718: 'Choose Conflict 1', 719: 'Choose Conflict 2', 720: 'Choose Conflict 3',
    1033: 'Delete Current Table Row', 1114: 'Move to End of Current Word',
    1684: 'Search Next Punctuation',
}
# Some recordings perform a single transcript operation via several editor
# commands. Compare the instructions, so a same-named, edited recording wins.
_COMMAND_RECIPES = {
    (264, 281, 624, 623, 32): 'Delete Entire Line',
    (267, 640): 'Insert Comma After Word', (267, 641): 'Insert Semicolon After Word',
    (267, 637): 'Insert Period After Word', (267, 638): 'Insert Question Mark After Word',
    (267, 642): 'Insert Colon After Word', (1114, 623, 644, 266): 'Shave Current Word',
    (267, 666, 623, 32): 'Remove Oops (Hotspot)',
}
# Only these complete, verified dialog recordings have an offline equivalent.
# Hash the target, message and argument, excluding timing and scan-code fields.
_DIALOG_RECIPES = {
    'bf17ca707548ac0abbdc53d5d48c573ce8f82545d10dbaa4fa77c049d7ad2f73': 'Change A to THE WITNESS',
    '54c68fc35b316edd1c2d4dcf8354c4b7c550c3e4e2c62979681408d99a6f5c0d': 'Change Last Question Mark to Period',
    'f44f9ea6eea84e389e323fccf8fc985438eb2010f61a8d879dbdb950675bd9a9': 'Add Table Row After Current Row',
}
_RECORD = struct.Struct('<5I')


def read_macro(path: Path):
    data = path.read_bytes()
    if (len(data) <= 512 or data[:8] != b'SGCAT32\0'
            or struct.unpack_from('<I', data, 288)[0] != 23 or (len(data) - 512) % _RECORD.size):
        raise ValueError(f'{path.name} has an invalid or truncated Case CATalyst macro.')
    records = list(_RECORD.iter_unpack(data[512:]))
    # WM_COMMAND fields for the editor itself always have these fixed values.
    if any(msg == 273 and (target, flags, source) != (0, 0, 1)
           for target, msg, _, flags, source in records):
        return (), 'Requires a Case CATalyst control to receive a recorded command.'
    events = tuple((target, msg, code) for target, msg, code, _, _ in records)
    if all(msg == 273 for _, msg, _ in events):
        recipe = _COMMAND_RECIPES.get(tuple(code for _, _, code in events))
    else:
        digest = hashlib.sha256(b''.join(struct.pack('<3I', *event) for event in events))
        recipe = _DIALOG_RECIPES.get(digest.hexdigest())
    if recipe:
        return (('command', recipe),), ''
    for vk, suffix in ((83, 's'), (68, 'ed'), (71, 'ing')):
        if events == ((0, 273, 1026), (358, 256, vk), (358, 257, vk)):
            return (('command', 'Add Suffix -' + suffix),), ''
    steps = []
    for target, msg, code in events:
        if msg != 273:
            if ('command', 'D-Define') in steps:
                return (), 'Requires a Case CATalyst dictionary definition dialog.'
            return (), f'Requires Case CATalyst dialog {target} for recorded message {msg} (key {code}).'
        if 32 <= code <= 126:
            char = chr(code)
            if steps and steps[-1][0] == 'literal':
                steps[-1] = ('literal', steps[-1][1] + char)
            else:
                steps.append(('literal', char))
        elif code in _COMMANDS:
            steps.append(('command', _COMMANDS[code]))
        else:
            return (), f'Recorded Case CATalyst command {code} has no offline implementation.'
    return tuple(steps), ''
