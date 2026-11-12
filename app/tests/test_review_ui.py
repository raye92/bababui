import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication


def test_diff_places_inserted_heading_before_unchanged_context():
    from app.src.review_view import context_diff
    assert context_diff('BY MS. SIEMENS:', 'EXAMINATION\nBY MS. SIEMENS:') == [
        ('insert', 'EXAMINATION'), ('equal', 'BY MS. SIEMENS:')]
    assert context_diff('Removed\nKept', 'Kept') == [('delete', 'Removed'), ('equal', 'Kept')]
    rows = context_diff('The old wording.', 'The new wording.')
    assert [kind for kind, _ in rows] == ['delete', 'insert']
    assert all('<b ' in text for _, text in rows)

def test_page_fit_changes_display_scale_without_reflow():
    from app.src.page_view import PageView
    from app.src.native_editor import NativeTranscriptEditor
    from PySide6.QtGui import QFont
    app = QApplication.instance() or QApplication([])
    editor = NativeTranscriptEditor(QFont('Courier New', 12))
    editor.setPlainText('     Q    ' + 'Example wording. ' * 100)
    view = PageView(editor)
    view.resize(700, 700)
    view.show()
    app.processEvents()
    before = [(p.page,p.number,p.position,p.text) for p in editor.page_lines()]
    view.resize(500, 700)
    app.processEvents()
    assert view.transform().m11() < 1
    assert view.transform().m11() * editor.width() <= view.viewport().width()+1
    assert [(p.page,p.number,p.position,p.text) for p in editor.page_lines()] == before
    view.close()
