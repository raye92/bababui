"""Review a notice and the corresponding Case CATalyst job before changing either revision."""
from pathlib import Path
import re

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QProgressDialog, QPushButton, QRadioButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
    QWizard, QWizardPage)

from app.src.notice_model import Appearance, NoticeDetails, filename_file_number


class NoticeReader(QThread):
    def __init__(self, filename, parent):
        super().__init__(parent)
        self.filename = Path(filename)
        self.error = None

    def run(self):
        try:
            from app.src.notice_pdf import extract_notice
            self.data = self.filename.read_bytes()
            self.details = extract_notice(self.data)
        except Exception as exc:
            self.error = str(exc) or 'Could not read this notice PDF.'


def read_notice(filename, parent):
    progress = QProgressDialog('Reading notice PDF…', '', 0, 0, parent)
    progress.setWindowTitle('Notice PDF')
    progress.setCancelButton(None)
    progress.setWindowModality(Qt.WindowModal)
    reader = NoticeReader(filename, progress)
    reader.finished.connect(progress.accept)
    reader.start()
    progress.exec()
    reader.wait()
    try:
        if reader.error:
            raise ValueError(reader.error)
        return reader.data, reader.details
    finally:
        progress.deleteLater()


def _label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    return label


def _entry(form, label, candidates):
    """An editable choice shows the source of conflicting values in the form."""
    choices = {}
    for source, raw in candidates:
        value = ' '.join(raw.split()) if raw else ''
        if value:
            choices.setdefault(value, []).append(source)
    if len(choices) < 2:
        edit = QLineEdit(next(iter(choices), ''))
        form.addRow(label, edit)
        return edit
    container = QWidget()
    box = QVBoxLayout(container)
    box.setContentsMargins(0, 0, 0, 0)
    edit = QComboBox()
    edit.setEditable(True)
    edit.setInsertPolicy(QComboBox.NoInsert)
    edit.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    edit.setMinimumContentsLength(20)
    edit.addItems(choices)
    box.addWidget(edit)
    sources = _label('  |  '.join(f'{", ".join(origins)}: {value}' for value, origins in choices.items()))
    box.addWidget(sources)
    form.addRow(label, container)
    return edit


def _value(widget):
    return (widget.currentText() if isinstance(widget, QComboBox) else widget.text()).strip()


class SidePage(QWizardPage):
    def isComplete(self):
        return any(button.isChecked() for button in self.wizard().sides.values())


class NoticeWizard(QWizard):
    def __init__(self, filename, extracted, existing, recording, auto_file, parent=None, *, previously_attached=False):
        super().__init__(parent)
        self.setWindowTitle('Review notice PDF')
        self.setButtonText(QWizard.FinishButton, 'Apply notice')
        self.resize(760, 640)
        self.entries = {}
        self.warnings = {}
        self.appearance_entries = []
        self.previous, self.extracted = existing.appearances, extracted.appearances
        self.provisional_side = ''

        cover = self._page('File number and caption')
        cover.setSubTitle(Path(filename).name)
        form = QFormLayout()
        cover.layout().addLayout(form)
        for name, label in (('file_number', 'File number'), ('plaintiff', 'Plaintiff / applicant'),
                            ('defendant', 'Defendant'), ('deponent', 'Deponent'), ('case_numbers', 'Case numbers')):
            current = getattr(existing, name)
            notice = getattr(extracted, name)
            if name == 'case_numbers':
                current, notice = ', '.join(current), ', '.join(notice)
            candidates = [('Current cover', current), ('Notice PDF', notice)]
            if name == 'file_number' and auto_file:
                candidates.insert(1 if previously_attached else 0, ('Filename', filename_file_number(filename)))
            self.entries[name] = _entry(form, label, candidates)
        self.entries['case_numbers'].setToolTip('Separate case numbers with a comma.')

        side = self._page('Taking side and commencement', SidePage())
        side.layout().addWidget(_label('On whose behalf was the deposition taken?'))
        group = QHBoxLayout()
        side.layout().addLayout(group)
        self.sides = {}
        for role in ('Applicant', 'Defendant'):
            control = QRadioButton(role)
            self.sides[role] = control
            group.addWidget(control)
            control.toggled.connect(side.completeChanged)
            control.setChecked(extracted.taking_side == role)
        if existing.taking_side and existing.taking_side != extracted.taking_side:
            side.layout().addWidget(_label(f'Current cover: {existing.taking_side}'))
        form = QFormLayout()
        side.layout().addLayout(form)
        for name, label in (('time', 'First stroke time'), ('weekday', 'Creation day of week'), ('date', 'Creation date in words')):
            choices = [('Recording ZIP', getattr(recording, name)), ('Current cover', getattr(existing, name))]
            if previously_attached and name != 'time':
                choices.reverse()
            self.entries[name] = _entry(form, label, choices)

        appearances = self._page('Appearances')
        self.appearance_tabs = QTabWidget()
        appearances.layout().addWidget(self.appearance_tabs)
        buttons = QHBoxLayout()
        appearances.layout().addLayout(buttons)
        self.add_buttons = []
        for role in ('Applicant', 'Defendant'):
            button = QPushButton(f'Add {role.lower()} appearance')
            button.clicked.connect(lambda _, r=role: self._appearance(r, Appearance(r), Appearance(r), select=True))
            buttons.addWidget(button)
            self.add_buttons.append(button)
        self._populate_appearances(extracted.taking_side)

        index = self._page('Examiner index')
        form = QFormLayout()
        index.layout().addLayout(form)
        self.speaker_inputs = []
        for i in range(3):
            if i == 2:
                self.third = QCheckBox('Include a third examining attorney')
                self.third.setChecked(len(existing.speakers) > 2 or (len(recording.speakers) > 2 and bool(recording.speakers[2])))
                form.addRow(self.third)
            candidates = [(source, row[i]) for source, row in
                          (('Recording ZIP', recording.speakers), ('Current cover', existing.speakers)) if i < len(row)]
            if previously_attached:
                candidates.reverse()
            edit = _entry(form, f'EZ SPEAKER {i+1:02d}', candidates)
            self.speaker_inputs.append(edit)
        self.speaker_inputs[2].setEnabled(self.third.isChecked())
        self.third.toggled.connect(self.speaker_inputs[2].setEnabled)
        index.layout().addWidget(_label('Enter examination page numbers in the index after the transcript is edited.'))
        for step in range(4):
            self.warnings[step] = _label('')
            self.warnings[step].setStyleSheet('color: #a63813;')
            self.page(step).layout().addWidget(self.warnings[step])

    def _page(self, title, page=None):
        page = page or QWizardPage()
        page.setTitle(title)
        QVBoxLayout(page)
        self.addPage(page)
        return page

    def initializePage(self, page_id):
        super().initializePage(page_id)
        if page_id == 2 and any(not row.side for row in self.extracted):
            role = next((s for s, button in self.sides.items() if button.isChecked()), '')
            if role != self.provisional_side:
                self._populate_appearances(role)

    def _populate_appearances(self, selected_side):
        # Keep manual corrections if the user goes back and changes the taking side.
        edits = [(role, {key: _value(widget) for key, widget in entries.items()
                         if _value(widget) != widget.property('initialValue')})
                 for role, entries in self.appearance_entries]
        while self.appearance_tabs.count():
            tab = self.appearance_tabs.widget(0)
            self.appearance_tabs.removeTab(0)
            tab.deleteLater()
        self.appearance_entries.clear()
        self.provisional_side = selected_side
        for role in ('Applicant', 'Defendant'):
            previous = [row for row in self.previous if row.side == role]
            parsed = [row for row in self.extracted if (row.side or selected_side) == role]
            manual = [values for side, values in edits if side == role]
            for i in range(max(1, len(previous), len(parsed), len(manual))):
                self._appearance(role, previous[i] if i < len(previous) else Appearance(role),
                                 parsed[i] if i < len(parsed) else Appearance(role))
                if i < len(manual):
                    for key, value in manual[i].items():
                        widget = self.appearance_entries[-1][1][key]
                        if isinstance(widget, QComboBox):
                            widget.setEditText(value)
                        else:
                            widget.setText(value)
        self.appearance_tabs.setCurrentIndex(0)

    def _appearance(self, role, current, notice, select=False):
        page = QWidget()
        form = QFormLayout(page)
        entries = {}
        for name, label in (('firm', 'Law firm'), ('attorney', 'Representative'), ('title', 'Professional title'),
                            ('address', 'Street or PO box'), ('suite', 'Suite'), ('city', 'City'), ('state', 'State'),
                            ('zip_code', 'ZIP code'), ('phone', 'Phone'), ('email', 'Email')):
            entries[name] = _entry(form, label, [('Current cover', getattr(current, name)), ('Notice PDF', getattr(notice, name))])
            entries[name].setProperty('initialValue', _value(entries[name]))
        count = sum(side == role for side, _ in self.appearance_entries) + 1
        self.appearance_entries.append((role, entries))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        i = self.appearance_tabs.addTab(scroll, role if count == 1 else f'{role} {count}')
        for button in self.add_buttons:
            button.setEnabled(len(self.appearance_entries) < 3)
        if select:
            self.appearance_tabs.setCurrentIndex(i)

    def details(self):
        data = {key: _value(edit) for key, edit in self.entries.items()}
        data['case_numbers'] = tuple(dict.fromkeys(x.strip() for x in re.split(r'[,;\n]+|\s+(?=ADJ\s*\d)',
                                      data['case_numbers'], flags=re.I) if x.strip()))
        data['taking_side'] = next((s for s, button in self.sides.items() if button.isChecked()), '')
        data['speakers'] = tuple(_value(edit) for edit in self.speaker_inputs[:3 if self.third.isChecked() else 2])
        rows = []
        for side, entries in self.appearance_entries:
            values = {key: _value(edit) for key, edit in entries.items()}
            if any(values.values()):
                rows.append(Appearance(side, **values))
        return NoticeDetails(**data, appearances=tuple(rows))

    def accept(self):
        from app.src.casecat.cover import cover_overflow
        controls = [(0, self.entries[k]) for k in ('file_number', 'plaintiff', 'defendant', 'deponent', 'case_numbers')]
        controls += [(1, self.entries[k]) for k in ('time', 'weekday', 'date')]
        controls += [(2, widget) for _, entries in self.appearance_entries for widget in entries.values()]
        controls += [(3, widget) for widget in self.speaker_inputs if widget.isEnabled()]
        for step, widget in controls:
            try:
                _value(widget).encode('cp1252')
            except UnicodeEncodeError:
                self._show_problem(step, 'Use characters supported by Case CATalyst in this entry.', widget)
                return
        for error in cover_overflow(self.details()):
            if re.search(r'appearance', error, re.I):
                step = 2
            elif re.search(r'speaker|examiner|index', error, re.I):
                step = 3
            elif re.search(r'time|creation|date|weekday|commencement', error, re.I):
                step = 1
            else:
                step = 0
            if error == 'Case numbers':
                message = 'The case-number column fits 18 entries of up to 16 characters. Enter only the complete case identifiers.'
            else:
                message = f'Shorten {error.lower()} to keep the first testimony on page 5, line 11.'
            self._show_problem(step, message)
            return
        super().accept()

    def _show_problem(self, step, message, widget=None):
        while self.currentId() > step:
            self.back()
        self.warnings[step].setText(message)
        if widget is not None:
            if step == 2:
                for i in range(self.appearance_tabs.count()):
                    if self.appearance_tabs.widget(i).isAncestorOf(widget):
                        self.appearance_tabs.setCurrentIndex(i)
                        break
            widget.setFocus()
