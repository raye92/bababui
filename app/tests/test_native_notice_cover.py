import os
from dataclasses import replace
from pathlib import Path
import struct

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from app.src.casecat import archive, codec
from app.src.casecat.field_table import field_texts
from app.src.native_editor import NativeTranscriptEditor
from app.src.notice_model import Appearance, NoticeDetails
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_fields import field_files, native_stream


def details():
    return NoticeDetails(
        plaintiff='LEOBARDO TRUJILLO', defendant="COUNTY OF LOS ANGELES/SHERIFF'S DEPT.; SEDGWICK",
        deponent='ALEX DOE, M.D.', case_numbers=('ADJ18095652', 'ADJ17221459', 'ADJ17221460'),
        file_number='J10023', taking_side='Defendant', time='5:02 p.m.',
        weekday='Wednesday', date='October 28, 2026',
        appearances=(Appearance(side='Defendant', firm='DEFENSE FIRM', attorney='ANNA RAY',
                                title='Attorney at Law', address='18 First Street', city='Sacramento',
                                state='California', zip_code='95814', email='aray@example.org'),
                     Appearance(side='Applicant', firm='APPLICANT FIRM', attorney='BEN SMITH',
                                title='Attorney at Law', address='12 Main Street', suite='Suite 3',
                                city='Los Angeles', state='California', zip_code='90012',
                                phone='(213) 555-0101', email='ben@example.org')),
        speakers=('MS. RAY', 'MR. SMITH'))


def native_cover():
    from app.src import casecat
    from importlib.util import find_spec
    assert find_spec(casecat.__name__ + '.cover'), 'Native notice cover construction is missing.'
    from app.src.casecat import cover
    return cover


def covered(files, notice, **kwargs):
    cover = native_cover()
    bundle = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, bundle.jobs[0])
    native, xml, old, new = cover.build_cover(bundle, job, notice, **kwargs)
    files = dict(files)
    files[job.key + '.sgngl'] = native
    if xml is not None:
        files[job.key + '.sgxml'] = xml
    after = archive.inspect_archive(zip_bytes(files))
    return files, job, after, codec.load_job(after, job.key), old, new


def test_prepended_cover_retains_native_body_and_real_linked_fields(tmp_path):
    files = field_files()
    notice = details()
    _, old_job, bundle, job, old, new = covered(files, notice)
    assert old == 0
    assert native_stream(job).endswith(native_stream(old_job))
    assert job.text[new:] == old_job.text.replace('MS. OLD', 'MS. RAY')
    assert job.notes_bytes == old_job.notes_bytes
    assert bundle.read(job.audio_member) == files[old_job.audio_member]
    names = [e.name for e in job.baseline.elements if e.kind == 'field' and e.start < new]
    assert names.count('PLAINTIFF') == names.count('DEFENDANT') == 2
    assert names.count('DEPONENT') == 4
    assert 'CREATION DAY OF WEEK' in names and 'CREATION DATE IN WORDS' in names
    assert field_texts(job.native_bytes)['DEFENDANT'] == notice.defendant
    assert 'January 16, 2005' not in job.text
    assert job.text.index('APPLICANT FIRM') < job.text.index('DEFENSE FIRM')
    assert job.text[:new].count('EXAMINATION') == 1
    assert b'MS. RAY' in bundle.read(job.key + '.sgxml')
    target = tmp_path / 'verified_AI.zip'
    revision = job.revision.replace(job.text.index('Question?'), job.text.index('Question?') + 8, 'Where?')
    archive.export_zip(bundle, job.with_revision(revision), target)
    exported = archive.inspect_archive(target)
    assert codec.load_job(exported, exported.jobs[0]).text == revision.text


def test_replacing_cover_keeps_manual_index_and_does_not_duplicate_body_heading():
    files = field_files()
    old_native = files['jobs/example.sgngl']
    from app.src.casecat.structure import relocate
    start, size = struct.unpack_from('<II', old_native, 532)
    body = b'\x16\x07\x00EXAMINATION'
    files['jobs/example.sgngl'] = relocate(old_native, body + old_native[start:start + size],
                                            [(0, len(body), size, size)])
    files, _, bundle, job, _, original_body = covered(files, details(), index_pages=('5,  32', '17'))
    fields, pages, source_start = native_cover().existing_cover(bundle, job)
    assert fields['plaintiff'] == details().plaintiff
    assert fields['case_numbers'] == details().case_numbers
    assert pages == ('5,  32', '17')
    assert source_start == original_body
    notice = replace(details(), file_number='J10024', speakers=(*details().speakers, 'MS. THIRD'))
    _, _, new_bundle, updated, _, new_body = covered(files, notice)
    assert updated.text[new_body:] == job.text[original_body:]
    assert updated.text[new_body:].startswith('EXAMINATION')
    assert updated.text.count("WORKERS' COMPENSATION APPEALS BOARD") == 2
    assert native_cover().existing_cover(new_bundle, updated)[1] == ('5,  32', '17', '')
    assert 'BY MS. THIRD' in updated.text[:new_body]


def test_editor_places_both_captions_index_and_body_on_template_pages():
    app = QApplication.instance() or QApplication([])
    font_id = -1
    if not QFontDatabase.families() and Path('C:/Windows/Fonts/cour.ttf').is_file():
        font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/cour.ttf')
    _, _, bundle, job, _, new = covered(field_files(), details())
    editor = NativeTranscriptEditor(QFont('Courier New', 12))
    editor.resize(1100, 800)
    editor.set_native_source(bundle, job)
    editor.setPlainText(job.text)
    app.processEvents()
    lines = editor.page_lines()
    assert editor.toPlainText() == job.text
    for page in (1, 2):
        page_rows = [row for row in lines if row.page == page]
        assert any(row.number == 4 and 'ADJ18095652' in row.text for row in page_rows)
        assert any('COUNTY OF LOS ANGELES/' in row.text and 'SHERIFF' not in row.text for row in page_rows)
        assert any("SHERIFF'S DEPT.; SEDGWICK," in row.text for row in page_rows)
        assert sum('~' * 30 in row.text for row in page_rows) == 1
    assert any(row.page == 3 and 'A P P E A R A N C E S' in row.text for row in lines)
    assert any(row.page == 4 and 'I N D E X' in row.text for row in lines)
    assert any(row.page == 5 and row.number == 11 and row.position == new for row in lines)
    from app.src.inline_review import InlineReviewEditor
    from app.src.review_model import ReviewModel
    inline = InlineReviewEditor(editor.font())
    inline.set_source_editors(editor, editor)
    inline.set_model(ReviewModel(job.revision, job.revision, (), ()))
    for page in (1, 2):
        assert any(row.page == page and row.number == 4 and 'LEOBARDO' in row.text
                   and 'ADJ18095652' in row.text for row in inline.page_lines())
    docket = job.text.index('ADJ18095652') + 5
    assert inline.set_source_position('original', docket)
    assert inline.source_position() == ('original', docket)
    inline.close()
    editor.close()
    if font_id >= 0:
        QFontDatabase.removeApplicationFont(font_id)


def test_overflow_identifies_the_caption_or_appearance_that_needs_editing():
    cover = native_cover()
    notice = details()
    assert not cover.cover_overflow(notice)
    assert 'Defendant' in cover.cover_overflow(replace(notice, defendant='INSURER; ' * 100))
    overflowing = replace(notice.appearances[0], address='Business Center ' * 150)
    assert any('appearance' in label.lower() for label in
               cover.cover_overflow(replace(notice, appearances=(overflowing, *notice.appearances[1:]))))


def test_refresh_preserves_all_manual_index_sections_and_civil_case_numbers():
    from app.src.casecat.structure import serialize_candidate
    notice = replace(details(), case_numbers=('26STCV40123', 'ADJ14234567'))
    files, _, bundle, job, _, _ = covered(field_files(), notice)
    entries = ('Exhibit B, medical report, 17', '19               7', 'Record request, 21')
    revision = job.baseline
    for value in entries:
        pos = revision.text.index('(NONE)')
        revision = revision.replace(pos, pos + 6, value)
    files[job.key + '.sgngl'] = serialize_candidate(job.with_revision(revision), bundle)
    _, _, bundle, job, _, _ = covered(files, replace(notice, file_number='J10028'))
    known, _, _ = native_cover().existing_cover(bundle, job)
    assert known['case_numbers'] == notice.case_numbers
    assert all(value in job.text for value in entries)


def test_long_deponent_and_right_column_entries_cannot_push_the_body_down():
    cover = native_cover()
    notice = details()
    long_name = 'MICHAEL ALEXANDER CHRISTOPHER BENNETT RODRIGUEZ, PH.D., Q.M.E., M.D.'
    assert 'Deponent' in cover.cover_overflow(replace(notice, deponent=long_name))
    assert cover.cover_overflow(replace(notice, file_number='X' * 55))
    assert cover.cover_overflow(replace(notice, time='12:02 p.m. ' * 6))
    assert cover.cover_overflow(replace(notice, case_numbers=('ADJ123456789012345678',)))
    assert cover.cover_overflow(replace(notice, speakers=('MS. ' + 'LONG ' * 14,)))
    extended = replace(notice, case_numbers=('CV-2026-0102345', '24-CV-00012345'))
    assert not cover.cover_overflow(extended)
    _, _, bundle, job, _, _ = covered(field_files(), extended)
    assert cover.existing_cover(bundle, job)[0]['case_numbers'] == extended.case_numbers


def test_final_comma_fits_the_caption_boundary_even_after_an_unbroken_word_or_slash():
    for defendant in ('X' * 30, 'X' * 29 + '/'):
        _, _, _, job, _, _ = covered(field_files(), replace(details(), defendant=defendant))
        field = next(e for e in job.revision.elements if e.name == 'DEFENDANT')
        rows = job.text[field.start:field.end + 1].splitlines()
        assert max(map(len, rows)) <= 30
        assert ''.join(rows) == defendant + ','


def test_direct_edit_inside_wrapped_field_keeps_underlying_name_and_both_occurrences():
    notice = details()
    _, _, bundle, job, _, _ = covered(field_files(), notice)
    field = next(e for e in job.revision.elements if e.name == 'DEFENDANT')
    revision = job.revision.replace(field.start + 1, field.start + 2, 'A')
    value = "CAUNTY OF LOS ANGELES/SHERIFF'S DEPT.; SEDGWICK"
    assert dict(revision.definitions)['DEFENDANT'] == value
    assert revision.text.count("CAUNTY OF LOS ANGELES/\nSHERIFF'S DEPT.; SEDGWICK") == 2
    from app.src.casecat.structure import serialize_candidate
    assert field_texts(serialize_candidate(job.with_revision(revision), bundle))['DEFENDANT'] == value
    revision = revision.set_field('CREATION DATE IN WORDS', 'November 1, 2026')
    assert 'NOVEMBER 1, 2026' in revision.text and 'November 1, 2026, before' in revision.text


def test_legacy_single_spaced_index_footer_keeps_tabs_and_fits_page_four():
    from app.src.casecat.structure import relocate
    files, _, bundle, job, _, _ = covered(field_files(), details())
    stream = native_stream(job)
    first = stream.index(b'\x16\x07\x00E X H I B I T S')
    end = stream.index(b'\x0c', first)
    footer = (b'\x16\x07\x00E X H I B I T S\x0a' + b'\x16\x08\x00' * 15 +
              b'\x16\x08\x00EXHIBIT A\x09CERTIFICATE\x0aNOTED ON PAGE 17' + b'\x16\x08\x00' * 12)
    files[job.key + '.sgngl'] = relocate(job.native_bytes, stream[:first] + footer + stream[end:],
                                         [(0, 0, first, first), (first, first, end-first, len(footer)),
                                          (end, first + len(footer), len(stream)-end, len(stream)-end)])
    _, _, bundle, job, _, new = covered(files, details())
    assert footer in native_stream(job)
    assert 'EXHIBIT A\tCERTIFICATE\nNOTED ON PAGE 17' in job.text
    app = QApplication.instance() or QApplication([])
    font_id = -1
    if not QFontDatabase.families() and Path('C:/Windows/Fonts/cour.ttf').is_file():
        font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/cour.ttf')
    view = NativeTranscriptEditor(QFont('Courier New', 12))
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    assert any(row.page == 5 and row.number == 11 and row.position == new for row in view.page_lines())
    view.close()
    if font_id >= 0:
        QFontDatabase.removeApplicationFont(font_id)
