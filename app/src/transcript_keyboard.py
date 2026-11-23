"""Dispatch transcript keystrokes before Qt looks for application shortcuts."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QInputDialog

from app.src.smart_commands import READ_ONLY, SmartCommands
from app.src.smart_keys import Binding, binding_dependency, default_profile, event_key


class TranscriptKeyboard(QObject):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.profile = default_profile()
        self.space_playback = False
        self.commands = SmartCommands(view)
        self.last_macro = None

    def eventFilter(self, editor, event):
        if event.type() not in (QEvent.ShortcutOverride, QEvent.KeyPress):
            return False
        view = self.view
        if editor is not view.active_view() or view.document.busy:
            return False
        key = event_key(event)
        binding = None
        if key == '/':
            binding = Binding(key, 'command', 'Change Keyboard Mode')
        elif key == 'Ctrl+Shift+/':
            binding = Binding(key, 'literal', '/')
        elif view.smart_keys:
            binding = self.profile.get(key)
            if key == '<Space>' and self.space_playback:
                binding = Binding(key, 'command', 'Play / pause')
            if binding is None and event.text().isprintable() and event.text() and not (
                    event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
                binding = Binding(key, 'unassigned', '')
        if binding is None:
            if key in ('Shift+<F9>', 'Ctrl+<F9>'):
                binding = Binding(key, 'command', 'Play Audio' if key.startswith('Shift') else 'Stop Audio')
            elif event.matches(QKeySequence.Undo) and view._review_undo:
                binding = Binding(key, 'command', 'Undo')
            elif event.matches(QKeySequence.Redo) and view._review_redo:
                binding = Binding(key, 'command', 'Redo')
        if binding is None:
            return False
        event.accept()
        if event.type() == QEvent.KeyPress and not (event.isAutoRepeat() and binding.value in
                ('Change Keyboard Mode', 'Default Keyboard', 'Play / pause', 'Play Audio', 'Stop Audio')):
            message = self.run(binding, editor)
            if message:
                view.document.status = message
                view.changed.emit()
        return True

    def run(self, binding, editor):
        if binding.kind == 'unassigned':
            return ''
        if binding.kind == 'command' and binding.value in ('Play Macro', 'Play Last Macro'):
            if binding.value == 'Play Last Macro':
                binding = self.last_macro
                if binding is None:
                    return 'Play a macro in this tab first.'
            else:
                macros = [b for b in self.profile.bindings if b.kind == 'macro']
                options = [f'{b.key}   {b.value}' for b in macros]
                if not options:
                    return 'This keyboard has no assigned macros.'
                choice, ok = QInputDialog.getItem(editor, 'Play Macro', 'Macro', options, editable=False)
                if not ok:
                    return ''
                binding = macros[options.index(choice)]
        if binding.value != 'Play / pause' and (reason := binding_dependency(binding)):
            return reason
        steps = binding.steps if binding.kind == 'macro' else ((binding.kind, binding.value),)
        view = self.view
        for kind, value in steps:
            if kind == 'command' and value in ('Play Audio', 'Stop Audio', 'Play / pause') and not view.playback:
                return 'Attach a WAV to use this audio command.'
            if editor.isReadOnly() and (kind == 'literal' or value not in READ_ONLY | {
                    'Change Keyboard Mode', 'Default Keyboard', 'Undo', 'Redo', 'Play / pause'}):
                return 'Choose Preview Accept All to edit this transcript.' if view.review_model.edits else 'This view is read-only.'
        if len(steps) == 1 and steps[0][0] == 'command' and steps[0][1] in ('Undo', 'Redo'):
            undo = steps[0][1] == 'Undo'
            if (view._review_undo if undo else view._review_redo):
                (view.undo_review if undo else view.redo_review)()
            else:
                (editor.undo if undo else editor.redo)()
            return ''
        snapshot = view.document.native
        before = snapshot.original, snapshot.incoming, snapshot.review
        cursor = editor.textCursor()
        old_selection = cursor.anchor(), cursor.position()
        undo_size = len(view._review_undo)
        saved_redo = view._review_redo.copy()
        previous_run = view._typing_run
        old_affinity = getattr(editor, 'caret_affinity', None)
        mode = view.smart_keys
        previous_dirty = view.document.dirty
        for kind, value in steps:
            error = ''
            self.commands.cancelled = False
            if kind == 'literal':
                error = self.commands.insert_literal(value, editor)
            elif value in ('Change Keyboard Mode', 'Default Keyboard'):
                view.set_smart_keys(value != 'Default Keyboard' and not view.smart_keys)
            elif value == 'Play / pause':
                view.playback.toggle()
            elif value == 'Stop Audio':
                view.playback.stop_from_keyboard()
            else:
                error = self.commands.execute(value, editor)
            if error or self.commands.cancelled:
                if before[:2] != (snapshot.original, snapshot.incoming):
                    snapshot.original, snapshot.incoming, snapshot.review = before
                    view.refresh()
                del view._review_undo[undo_size:]
                view._review_redo[:] = saved_redo
                view._typing_run = previous_run
                view._history_selection = (*old_selection, old_affinity)
                view._restore_history_selection()
                view.document.dirty = previous_dirty
                view.set_smart_keys(mode)
                return error
        if before[:2] != (snapshot.original, snapshot.incoming):
            view._review_undo[undo_size:] = [(*before, (*old_selection, old_affinity))]
            view._review_redo.clear()
            view._typing_run = None
        if binding.kind == 'macro':
            self.last_macro = binding
        return ''
