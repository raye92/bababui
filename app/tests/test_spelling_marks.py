"""Orange spelling-review underlines in the transcript editor and the Incoming view."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from hashlib import sha256
import json
from types import SimpleNamespace
import zipfile

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTextEdit

from app.src.review_colors import ADDITION_BACKGROUND, SPELLING_UNDERLINE
from app.tests.test_native_editor import native_window, source_zip  # noqa: F401 (fixture)
from app.tests.test_suggestions import revision
from shared.spelling_review import PROMPT as SPELLING_PROMPT, review_spelling

ROUGH = 'Did Dr. Meyer see him at Pacific Orthopaedic Associates?\nYes. Dr. Meyer took the MRI.'
DRAFT = 'Did Dr. Meyer see him at Pacific Orthopaedic Associates?\nYes. Dr. Myers took the MRI.'
MEYER = {'word': 'Meyer', 'context': 'Meyer', 'category': 'person', 'alternatives': ['Meier'],
         'why': 'The surname is never spelled or confirmed.'}
MYERS = {'word': 'Myers', 'context': 'Dr. Myers', 'category': 'person', 'alternatives': ['Meyer', 'Meier']}


def spelling(*words, rough=ROUGH, draft=DRAFT, sources=()):
    return review_spelling(rough, draft, lambda payload, prompt: json.dumps({'words': list(words)}),
                           sources=sources).record()


def orange(marks):
    return [m for m in marks if m.format.underlineStyle() == QTextCharFormat.WaveUnderline
            and m.format.underlineColor() == QColor(SPELLING_UNDERLINE)]


def underlined(editor):
    return [m.cursor.selectedText() for m in orange(editor.extraSelections())]


def editor_with(text):
    from app.src.native_editor import NativeTranscriptEditor
    QApplication.instance() or QApplication([])
    editor = NativeTranscriptEditor(QFont())
    editor.setPlainText(text)
    return editor


def stored_underline(editor):
    """Whether any character of the document itself carries the spelling underline."""
    cursor = QTextCursor(editor.document())
    for position in range(1, len(editor.toPlainText()) + 1):
        cursor.setPosition(position)
        if cursor.charFormat().underlineStyle() == QTextCharFormat.WaveUnderline:
            return True
    return False


def test_the_editor_underlines_only_the_word_over_a_green_edit_and_keeps_the_text():
    editor = editor_with(ROUGH)
    green = QTextEdit.ExtraSelection()
    green.cursor = QTextCursor(editor.document())
    green.cursor.setPosition(ROUGH.index('Dr. Meyer'))
    green.cursor.setPosition(ROUGH.index('Dr. Meyer') + len('Dr. Meyer see'), QTextCursor.KeepAnchor)
    green.format.setBackground(QColor(ADDITION_BACKGROUND))
    editor.set_review_marks([green], [])
    editor.set_spelling(spelling(MEYER))
    marks = editor.extraSelections()
    assert underlined(editor) == ['Meyer', 'Meyer']
    # Drawn after the green edit, so the orange underline shows over it.
    assert marks[-2:] == orange(marks) and marks[-3].format.background().color() == QColor(ADDITION_BACKGROUND)
    assert editor.spelling_note(ROUGH.index('Meyer') + 2).startswith('Check the spelling: Meyer or Meier?')
    assert editor.spelling_note(ROUGH.index('Did')) == ''
    # The mark is never part of the transcript, its formatting or a copy.
    assert editor.toPlainText() == ROUGH and not stored_underline(editor)
    editor.selectAll()
    assert editor.createMimeDataFromSelection().text() == ROUGH
    editor.close()


def test_verified_or_unambiguous_words_stay_unmarked():
    draft = ROUGH.replace('Meyer', 'Meier')
    editor = editor_with(draft)
    confirmed = {**MEYER, 'word': 'Meier', 'alternatives': ['Meyer']}
    editor.set_spelling(spelling(confirmed, rough=draft, draft=draft, sources=[('person', 'Dr. John Meier')]))
    assert underlined(editor) == []
    editor.set_spelling(spelling({**MEYER, 'alternatives': []}, rough=draft, draft=draft))
    assert underlined(editor) == []
    editor.close()


def test_a_conflict_with_the_notice_is_underlined_without_the_model():
    editor = editor_with(ROUGH)
    editor.set_spelling(spelling(sources=[('person', 'Dr. John Meier')]))
    assert underlined(editor) == ['Meyer', 'Meyer']
    assert editor.spelling_note(ROUGH.index('Meyer')).startswith('Check the spelling of Meyer: the notice has Meier.')
    editor.close()


def test_fixing_the_spelling_removes_its_underline():
    editor = editor_with(ROUGH)
    editor.set_spelling(spelling(MEYER))
    cursor = QTextCursor(editor.document())
    second = ROUGH.rindex('Meyer')
    cursor.setPosition(second)
    cursor.setPosition(second + len('Meyer'), QTextCursor.KeepAnchor)
    cursor.insertText('Meier')
    QTest.qWait(300)
    assert underlined(editor) == ['Meyer']
    editor.close()


def test_the_accept_all_preview_draws_the_orange_underline_over_the_green_edit():
    from app.src.accept_all_preview import AcceptAllPreviewEditor
    QApplication.instance() or QApplication([])
    editor = AcceptAllPreviewEditor(QFont())
    editor.setPlainText(DRAFT)
    editor._text = DRAFT
    start = DRAFT.index('Dr. Myers')
    cursor = QTextCursor(editor.document())
    cursor.setPosition(start)
    cursor.setPosition(start + len('Dr. Myers'), QTextCursor.KeepAnchor)
    editor._highlights = [(start, start + len('Dr. Myers'), 0, cursor)]
    editor.set_spelling(spelling(MYERS))
    editor.highlight_edit(0)
    marks = editor.extraSelections()
    assert marks[-2].format.background().color() == QColor(ADDITION_BACKGROUND)
    assert underlined(editor) == ['Myers'] and marks[-1] == orange(marks)[0]
    editor.close()


def test_the_original_incoming_and_inline_views_mark_the_same_review(native_window, tmp_path):
    from app.src.ai_review import AssistedReview
    from app.src.suggestion_filter import auto_accept, begin_review
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    state = view.document.native
    state.original = state.incoming = state.original.revise(ROUGH)
    view.refresh()
    record = spelling(MEYER, MYERS)
    # The review arrives with the AI draft and stays with the document.
    draft = SimpleNamespace(original=state.original)
    begin_review(draft, DRAFT)
    before = draft.original, draft.incoming, draft.review
    auto_accept(draft)
    after = draft.original, draft.incoming, draft.review
    view.receive_reviewed(AssistedReview(state.original, None, before, after, after, 'Done.', record), [])
    assert state.spelling == record
    # Original shows the reporter's rough; Show Incoming shows the AI draft.
    assert underlined(view.editor) == ['Meyer', 'Meyer']
    assert underlined(view.incoming_editor) == ['Meyer', 'Myers']
    assert sorted(underlined(view.inline_editor)) == ['Meyer', 'Meyer', 'Myers']
    assert view.preview_editor._spelling == record
    inline = view.inline_editor
    myers = next(m.cursor.selectionStart() for m in orange(inline.extraSelections())
                 if m.cursor.selectedText() == 'Myers')
    assert inline.spelling_note(myers).startswith('Check the spelling: Myers or Meyer or Meier?')
    # The marks change no text.
    assert state.original.text == ROUGH and state.incoming.text == DRAFT
    assert not stored_underline(view.editor) and not stored_underline(view.incoming_editor)


def test_the_review_is_saved_with_the_document_but_never_exported(native_window, tmp_path):
    from app.tests.test_native_editor import zip_bytes
    from app.tests.test_native_structure import container_files
    files = container_files()
    del files['jobs/example.wav']
    source = tmp_path/'exportable.zip'
    source.write_bytes(zip_bytes(files))
    native_window.import_zip(0, source)
    view = native_window.current
    state = view.document.native
    state.original = state.incoming = state.original.replace(0, len(state.original.text), ROUGH)
    view.refresh()

    def exported(name):
        target = tmp_path/name
        view.document.export_casecat(target)
        with zipfile.ZipFile(target) as archive:
            return {member: archive.read(member) for member in archive.namelist()}
    plain = exported('plain.zip')
    record = spelling(MEYER)
    state.spelling = record
    view.refresh()
    assert underlined(view.editor) == ['Meyer', 'Meyer']
    assert exported('marked.zip') == plain
    saved = state.to_dict()
    assert saved['spelling'] == record
    restored = type(state).restore(state.bundle, json.loads(json.dumps(saved)))
    assert restored.spelling == record
    assert type(state).restore(state.bundle, {**saved, 'spelling': {'version': 1, 'terms': 'x'}}).spelling is None
    assert type(state).restore(state.bundle, {k: v for k, v in saved.items() if k != 'spelling'}).spelling is None


def run_worker(tmp_path, spelling_answer, *, sources=(), original=ROUGH):
    from app.src.audio_pipeline import Transcription
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    wav = tmp_path/'job.wav'
    wav.write_bytes(b'recording')

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            return Transcription('Raw transcript', (), (), 9000, sha256(path.read_bytes()).hexdigest())

    sent = []

    class Processor:
        def __init__(self, config, model):
            self.model = model

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            if prompt == SPELLING_PROMPT:
                sent.append((self.model, json.loads(text)))
                return spelling_answer(text)
            if prompt == 'rules':
                return DRAFT
            return '{}'

    request = Request('doc', str(wav), 'formatter', 'transcribe', 'rules', {}, original=revision(original),
                      review_model='reviewer', context='Witness (deponent): Dr. John Meier.', sources=sources)
    worker = ProcessingWorker(request, TranscriptionCoordinator(), Pipeline, Processor)
    reviewed, failed, progress = [], [], []
    worker.reviewed.connect(lambda *args: reviewed.append(args))
    worker.failed.connect(lambda *args: failed.append(args))
    worker.progress.connect(lambda _, message: progress.append(message))
    worker.run()
    assert not failed
    return reviewed[0][1], sent, progress


def test_the_pipeline_checks_the_rough_and_the_draft_against_the_notice(tmp_path):
    result, sent, progress = run_worker(tmp_path, lambda _: json.dumps({'words': [MYERS]}),
                                        sources=(('person', 'Dr. John Meier'),))
    assert 'Checking spellings...' in progress
    (model, payload), = sent
    assert model == 'reviewer' and payload['notice'] == 'Witness (deponent): Dr. John Meier.'
    assert payload['confirmed_names'] == ['Dr. John Meier']
    assert payload['transcript'].startswith('1: Did Dr. Meyer') and 'Myers' in payload['edits'][0]['draft']
    terms = {(t['word'], t['kind']) for t in result.spelling['terms']}
    # Meyer conflicts with the notice even though the model only raised Myers.
    assert terms == {('Meyer', 'conflict'), ('Myers', 'conflict')}
    assert 'Spelling review: 2 words to check.' in result.summary
    # The texts the review produced are unchanged by the spelling check.
    assert result.after_ai[1].text == DRAFT


def test_a_failed_spelling_check_still_delivers_the_draft(tmp_path):
    def broken(_):
        raise RuntimeError('model unavailable')
    result, _, _ = run_worker(tmp_path, broken)
    assert result.spelling is None
    assert 'Spelling review could not run.' in result.summary
    assert result.after_ai[1].text == DRAFT
