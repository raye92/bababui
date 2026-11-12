"""CaseCAT-style controls for name fields and supported format symbols."""
from dataclasses import replace

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QDialogButtonBox, QTableWidget, QTableWidgetItem, QPushButton,
    QCheckBox, QAbstractItemView, QHeaderView, QMessageBox)

from app.src.casecat.fields import field_values
from app.src.casecat.field_table import field_record


class FillFieldDialog(QDialog):
    def __init__(self, name, value, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Fill In Field')
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setReadOnly(True)
        self.value = QLineEdit(value)
        form.addRow('Field Name:', self.name)
        form.addRow('Field Value:', self.value)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(420, 140)
        self.value.selectAll()
        self.value.setFocus()

    @classmethod
    def get_value(cls, parent, name, value):
        dialog = cls(name, value, parent)
        accepted = dialog.exec() == QDialog.Accepted
        value = dialog.value.text()
        dialog.deleteLater()
        return value, accepted


class FieldListDialog(QDialog):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.new_names = set()
        self.setWindowTitle('Insert Field')
        self.setModal(False)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['Field Name', 'Field Value'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self.rename_new_field)
        self.table.cellDoubleClicked.connect(lambda row, column: self.fill_field() if column == 1 else self.insert_field())
        layout.addWidget(self.table)
        self.close_after = QCheckBox('Close dialog after inserting field.')
        layout.addWidget(self.close_after)
        row = QHBoxLayout()
        self.new_button = QPushButton('New Field')
        self.fill_button = QPushButton('Fill In Field')
        self.insert_button = QPushButton('Insert')
        self.close_button = QPushButton('Close')
        for button, action in ((self.new_button, self.new_field), (self.fill_button, self.fill_field),
                               (self.insert_button, self.insert_field), (self.close_button, self.close)):
            button.clicked.connect(action)
            button.setAutoDefault(False)
            row.addWidget(button)
        self.insert_button.setDefault(True)
        layout.addLayout(row)
        self.resize(540, 390)
        self.refresh()

    def selected_name(self):
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item else None

    def refresh(self, selected=None):
        selected = selected or self.selected_name()
        values = field_values(self.editor._native_source[1].revision)
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(values))
            for row, (name, value) in enumerate(sorted(values.items(), key=lambda item: item[0].casefold())):
                name_item, value_item = QTableWidgetItem(name), QTableWidgetItem(value)
                name_item.setData(Qt.UserRole, name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
                value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, 0, name_item)
                self.table.setItem(row, 1, value_item)
                if name == selected:
                    self.table.setCurrentCell(row, 0)
            if self.table.currentRow() < 0 and values:
                self.table.setCurrentCell(0, 0)
        self.fill_button.setEnabled(bool(values))
        self.insert_button.setEnabled(bool(values))

    def new_field(self):
        if self.editor.isReadOnly() or not self.editor.isVisible():
            return
        revision = self.editor._native_source[1].revision
        values = field_values(revision)
        number = 1
        while f'FIELD{number}' in values:
            number += 1
        name = f'FIELD{number}'
        self.editor.apply_native_revision(revision.define_field(name))
        self.new_names.add(name)
        self.refresh(name)
        item = self.table.item(self.table.currentRow(), 0)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.table.editItem(item)

    def rename_new_field(self, item):
        if item.column() != 0:
            return
        old, name = item.data(Qt.UserRole), item.text().strip().upper()
        if old == name:
            return
        revision = self.editor._native_source[1].revision
        try:
            if self.editor.isReadOnly() or not self.editor.isVisible():
                return
            if old not in self.new_names or any(e.name == old for e in revision.elements):
                raise ValueError('Only a new, uninserted field can be named here.')
            field_record(name)
            values = field_values(revision)
            if old not in values:
                self.refresh()
                return
            if name in values:
                raise ValueError('That field name already exists.')
            value = values[old]
            revision = replace(revision, definitions=tuple((key, val) for key, val in revision.definitions if key != old))
            revision = revision.define_field(name, value)
        except (ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, 'Cannot name field', str(exc))
            with QSignalBlocker(self.table):
                item.setText(old)
            return
        self.editor.apply_native_revision(revision)
        self.new_names.discard(old)
        self.new_names.add(name)
        with QSignalBlocker(self.table):
            item.setText(name)
            item.setData(Qt.UserRole, name)

    def fill_field(self):
        if self.editor.isReadOnly() or not self.editor.isVisible():
            return
        name = self.selected_name()
        if name:
            self.editor.fill_native_field(name)
            self.refresh(name)

    def insert_field(self):
        if self.editor.isReadOnly() or not self.editor.isVisible():
            return
        name = self.selected_name()
        if name and self.editor.insert_named_field(name):
            self.refresh(name)
            if self.close_after.isChecked():
                self.close()

    def refresh_if_idle(self):
        if self.isVisible() and self.table.state() != QAbstractItemView.EditingState:
            self.refresh()

    def closeEvent(self, event):
        super().closeEvent(event)
        if self.editor.isVisible():
            self.editor.setFocus(Qt.OtherFocusReason)


class FormatSymbolDialog(QDialog):
    SYMBOLS = (('Answer', 'a', 'A'), ('By-line', 'm', 'By-line'), ('Question', 'q', 'Q'))

    def __init__(self, parent=None, *, current=None):
        super().__init__(parent)
        self.setWindowTitle('Change Format Symbol' if current else 'Insert Format Symbol')
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(self.SYMBOLS), 2)
        self.table.setHorizontalHeaderLabels(['Format Symbol', 'Shortcut'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 75)
        for row, (name, shortcut, value) in enumerate(self.SYMBOLS):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(shortcut))
        self.table.setCurrentCell(next((i for i, item in enumerate(self.SYMBOLS) if item[2] == current), 0), 0)
        self.table.cellDoubleClicked.connect(lambda *_: self.accept())
        self.table.installEventFilter(self)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Change' if current else 'Insert')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(330, 220)

    @property
    def symbol(self):
        return self.SYMBOLS[self.table.currentRow()][2]

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is self.table and event.type() == QEvent.KeyPress:
            for row, (_, shortcut, _) in enumerate(self.SYMBOLS):
                if event.text().lower() == shortcut:
                    self.table.setCurrentCell(row, 0)
                    return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.accept()
                return True
        return super().eventFilter(watched, event)
