"""File, print, and native inspection commands used by Smart Keys."""
from pathlib import Path
import struct

from PySide6.QtCore import Qt, QRectF, QSortFilterProxyModel, QStringListModel
from PySide6.QtGui import QAbstractTextDocumentLayout, QPainter, QPalette, QFontDatabase, QTextCursor
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QDialog, QFileDialog, QPlainTextEdit, QVBoxLayout, QLabel, QLineEdit, QListView

from app.src.smart_editing import CommandCancelled, page_row, replace_text, revision_of, selection


def include_file(editor):
    path, _ = QFileDialog.getOpenFileName(editor, 'Include File', '',
        'Transcript passages (*.txt *.bababui);;Text files (*.txt);;BABABUI projects (*.bababui)')
    if not path:
        raise CommandCancelled()
    _, start, _ = selection(editor)
    path = Path(path)
    if path.suffix.lower() == '.bababui':
        from app.src.documents import open_document
        included = open_document(path).native
        dest = getattr(editor, '_native_source', None)
        if not dest or included.job.source_digest != dest[1].source_digest or included.job.key != dest[1].key:
            return 'Including a different native job requires merging its steno, fields, audio, and layout. A text passage or project from this same source can be included.'
        source = included.original
        revision = revision_of(editor)
        revision.atomic_range(start, start)
        updated = revision.adopt(start, start, source, 0, len(source.text))
        # Importing a working-project passage may require physically moving
        # source strokes. Check that the native writer can honor the edit.
        from app.src.casecat.codec import serialize_native
        serialize_native(dest[1].with_revision(updated), dest[0])
        editor.apply_native_revision(updated, start + len(source.text), edit_range=(start, start))
    else:
        raw = path.read_bytes()
        try:
            passage = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            passage = raw.decode('cp1252')
        if '\0' in passage:
            return 'Choose a plain-text passage or a BABABUI project.'
        return replace_text(editor, start, start, passage.replace('\r\n', '\n').replace('\r', '\n'))


def break_to_file(view, editor):
    from app.src.documents import save_document
    revision = revision_of(editor)
    if not revision or not getattr(view, 'document', None):
        return 'Breaking a passage to a project requires a native transcript.'
    text, start, end = selection(editor)
    start, end = revision.atomic_range(start, end if start != end else len(text))
    if start == end:
        return 'Select the passage or place the cursor before it.'
    path, _ = QFileDialog.getSaveFileName(editor, 'Break to New Project', '', 'BABABUI projects (*.bababui)')
    if not path:
        raise CommandCancelled()
    destination = Path(path)
    if not destination.suffix:
        destination = destination.with_suffix('.bababui')
    # Splitting a working project keeps the source ZIP, fields, stroke anchors,
    # and audio timing available on both sides of the split.
    retained = revision._replace(start, end, '')
    moved = revision._replace(end, len(text), '')._replace(0, start, '')
    copy = view.document.duplicate()
    copy.native.original = copy.native.incoming = moved
    copy.native.review = None
    save_document(copy, destination, save_as=True)
    editor.apply_native_revision(retained, start, edit_range=(start, end))


def reveal_codes(editor):
    existing = getattr(editor, '_smart_reveal', None)
    if existing is not None:
        existing.setVisible(not existing.isVisible())
        return
    panel = QDialog(editor)
    panel.setWindowTitle('Reveal Codes')
    layout = QVBoxLayout(panel)
    details = QPlainTextEdit(panel)
    details.setReadOnly(True)
    layout.addWidget(details)
    panel.resize(580, 320)

    def update():
        if not panel.isVisible():
            return
        revision = revision_of(editor)
        if not revision:
            return
        _, start, _ = selection(editor)
        pos = 0
        selected = next((e for e in revision.elements if e.start <= start < e.end), None)
        lines = []
        if selected:
            lines += [f'{selected.kind.title()} {selected.name}', selected.raw.upper(), '']
        for span in revision.spans:
            end = pos + len(span.content)
            if pos <= start < end or end == start == len(revision.text):
                lines += [f'Passage at characters {pos + 1} to {end}', span.content,
                          '', 'Native formatting records', *(span.formatting or ('None',))]
                break
            pos = end
        details.setPlainText('\n'.join(lines))

    editor.cursorPositionChanged.connect(update)
    editor.textChanged.connect(update)
    editor._smart_reveal = panel
    panel.show()
    update()


def steno_keys(data):
    keys = data[290:322].split(b'\0', 1)[0].decode('cp1252')
    if not keys or not keys.isprintable():
        raise ValueError('This file has no supported steno key table.')
    return keys


def stroke_text(data, keys):
    mask = int.from_bytes(data, 'big')
    return ''.join(key if mask & (1 << (31-i)) else ' ' for i, key in enumerate(keys))


def tape_rows(job):
    from app.src.casecat.codec import records, u32
    keys = steno_keys(job.notes_bytes)
    data = job.native_bytes
    start = u32(data, 532)
    rows = []
    for _, record in records(data, start, start + u32(data, 536)):
        if record[0] == 0x13:
            rows.extend(stroke_text(record[offset:offset+4], keys) for offset in range(3, len(record), 8))
    return keys, rows


def vertical_notes(editor):
    existing = getattr(editor, '_smart_tape', None)
    if existing:
        existing.setVisible(not existing.isVisible())
        return
    keys, rows = tape_rows(editor._native_source[1])
    panel = QDialog(editor)
    panel.setWindowTitle('Vertical Notes')
    layout = QVBoxLayout(panel)
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    heading = QLabel(keys)
    heading.setFont(font)
    layout.addWidget(heading)
    tape = QPlainTextEdit(panel)
    tape.setFont(font)
    tape.setReadOnly(True)
    tape.setLineWrapMode(QPlainTextEdit.NoWrap)
    tape.setPlainText('\n'.join(rows))
    layout.addWidget(tape)
    panel.resize(340, 440)

    def follow():
        if not panel.isVisible():
            return
        revision = revision_of(editor)
        if not revision:
            return
        _, caret, _ = selection(editor)
        end = 0
        for span in revision.spans:
            end += len(span.content)
            if (end > caret or end == len(revision.text)) and span.stroke_refs:
                block = tape.document().findBlockByNumber(span.stroke_refs[0])
                if block.isValid():
                    cursor = QTextCursor(block)
                    cursor.select(QTextCursor.LineUnderCursor)
                    tape.setTextCursor(cursor)
                    tape.centerCursor()
                return
    editor.cursorPositionChanged.connect(follow)
    editor._smart_tape = panel
    panel.show()
    follow()


def dictionary_entries(data):
    if len(data) < 640 or data[:8] != b'SGCAT32\0':
        raise ValueError('Choose a CaseCAT .sgdct dictionary.')
    keys = steno_keys(data)
    position = 640
    entries = []
    while position < len(data):
        if position + 21 > len(data):
            raise ValueError('Incomplete dictionary record.')
        count, length = struct.unpack_from('<BH', data, position + 18)
        first = position + 21
        body = first + 4 * count
        end = body + length
        if not count or end > len(data):
            raise ValueError('Unsupported dictionary record length.')
        outlines = []
        for offset in range(first, body, 4):
            stroke = stroke_text(data[offset:offset+4], keys)
            left, middle = data[354], data[355]
            if left and middle and not stroke[left:left+middle].strip() and stroke[left+middle:].strip():
                stroke = stroke[:left] + '-' + stroke[left:]
            outlines.append(stroke.replace(' ', ''))
        translation = ''.join(chr(b) if 32 <= b <= 126 else bytes([b]).decode('cp1252', errors='replace')
                              if b >= 128 else f'⟨{b:02X}⟩' for b in data[body:end])
        entries.append('/'.join(outlines) + '    ' + translation)
        position = (end + 3) & ~3
    return entries


def view_dictionary(editor):
    if existing := getattr(editor, '_smart_dictionary', None):
        existing.setVisible(not existing.isVisible())
        return
    name, _ = QFileDialog.getOpenFileName(editor, 'View Personal Dictionary', '', 'CaseCAT dictionary (*.sgdct)')
    if not name:
        raise CommandCancelled()
    entries = dictionary_entries(Path(name).read_bytes())
    panel = QDialog(editor)
    panel.setWindowTitle(Path(name).name)
    layout = QVBoxLayout(panel)
    query = QLineEdit()
    query.setPlaceholderText('Find a steno outline or definition')
    layout.addWidget(query)
    words = QListView(panel)
    words.setEditTriggers(QListView.NoEditTriggers)
    proxy = QSortFilterProxyModel(words)
    proxy.setSourceModel(QStringListModel(entries, proxy))
    proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
    query.textChanged.connect(proxy.setFilterFixedString)
    words.setModel(proxy)
    layout.addWidget(words)
    panel.resize(600, 450)
    editor._smart_dictionary = panel
    panel.show()


def print_pages(editor, *, current):
    rows, index = page_row(editor)
    if not rows:
        return 'There are no printed transcript pages.'
    printer = QPrinter(QPrinter.HighResolution)
    pages = [rows[index].page] if current else sorted({row.page for row in rows})
    dialog = QPrintDialog(printer, editor)
    dialog.setWindowTitle('Print Current Page' if current else 'Print File')
    dialog.setMinMax(pages[0], pages[-1])
    if dialog.exec() != QDialog.Accepted:
        raise CommandCancelled()
    if printer.fromPage():
        pages = [page for page in pages if printer.fromPage() <= page <= printer.toPage()]
    return render_pages(editor, printer, rows, pages)


def render_pages(editor, printer, rows, pages):
    painter = QPainter()
    if not painter.begin(printer):
        return 'The printer could not open the output.'
    source = editor.source_editors[0] if hasattr(editor, 'source_editors') else editor
    try:
        for index, number in enumerate(pages):
            if index and not printer.newPage():
                return 'The printer could not begin another page.'
            top = (number - 1) * editor._page_height
            height = editor._page_height
            if hasattr(editor, 'pages'):
                page = next(p for p in editor.pages if p.number == number)
                top, height = page.top, page.height
            page_rect = printer.pageLayout().paintRectPixels(printer.resolution())
            scale = min(page_rect.width() / editor._page_width, page_rect.height() / height)
            painter.save()
            painter.scale(scale, scale)
            painter.translate(0, -top)
            clip = QRectF(0, top, editor._page_width, height)
            painter.setClipRect(clip)
            context = QAbstractTextDocumentLayout.PaintContext()
            context.clip = clip
            context.palette.setColor(QPalette.Text, Qt.black)
            context.palette.setColor(QPalette.Base, Qt.white)
            editor.document().documentLayout().draw(painter, context)
            painter.setPen(Qt.black)
            painter.setFont(source.font())
            for line in rows:
                if line.page == number:
                    painter.drawText(source.line_number_rect(line.y), Qt.AlignRight | Qt.AlignVCenter,
                                     str(line.number))
            footer = source.page_number_rect(number - 1)
            footer.translate(0, top + height - number * source._page_height)
            painter.setFont(source.page_number_font())
            painter.drawText(footer, Qt.AlignRight | Qt.AlignVCenter, str(number))
            painter.restore()
    finally:
        painter.end()
