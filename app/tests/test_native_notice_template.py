"""Check the generated notice against the scoped template's half-line grid."""
import re
from dataclasses import replace
from pathlib import Path
import pytest

from app.src.casecat import codec, cover
from app.src.casecat.field_table import field_texts
from app.src.casecat.presentation import presentation
from app.src.notice_model import Appearance, NoticeDetails
from app.src.casecat.structure import relocate, serialize_candidate
from app.tests.test_native_fields import field_files
from app.tests.test_native_notice_cover import covered


def sample_notice():
    return NoticeDetails(
        plaintiff='ALEX EXAMPLE', defendant='SAMPLE COMPANY', deponent='CASEY SAMPLE',
        case_numbers=('ADJ00000123',), file_number='FILE123', taking_side='Applicant',
        time='9:01 a.m.', weekday='Monday', date='May 4, 2026',
        appearances=(
            Appearance('Applicant', 'FIRST FIRM', 'SAM ONE', 'Attorney at Law',
                       '90 Example Lane', 'Suite 12', 'Sample City', 'California', '90001',
                       '(555) 010-1000', 'one@example.test'),
            Appearance('Defendant', 'SECOND FIRM', 'LEE TWO', 'Attorney at Law',
                       '25 Other Street', 'Floor 3', 'Other City', 'California', '90002',
                       '(555) 010-2000', 'two@example.test')),
        speakers=('MR. ONE', 'MS. TWO'))


def page_rows(bundle, job, heading):
    """Read paragraph spacing in half-lines, starting at the named page."""
    text, styles, breaks = presentation(job, bundle)
    start = text.rfind('\n', 0, text.index(heading)) + 1
    end = min((pos for pos in breaks if pos > start), default=len(text))
    rows = []
    half_line = 0
    for line in text[start:end].split('\n'):
        if line.strip():
            rows.append((' '.join(line.split()), 1 + half_line / 2))
        if start in styles:
            half_line += styles[start].spacing
        start += len(line) + 1
    return rows


def test_rebuilt_caption_and_repeated_recital_follow_the_scoped_spacing():
    _, _, bundle, job, _, _ = covered(field_files(), sample_notice())
    assert job.text.count('Defendants.\n\n' + '~' * 30) == 2
    # The scoped date and the second state heading include a trailing space
    # in their centering width, a half-character shift on the page.
    assert 'MAY 4, 2026 \n' in job.text
    assert job.text.count('STATE OF CALIFORNIA \n') == 1
    assert page_rows(bundle, job, 'Deposition of CASEY SAMPLE') == [
        ('Deposition of CASEY SAMPLE, taken on', 1),
        ('behalf of the Applicant, at (PARTICIPANTS REMOTE),', 2),
        ('California, commencing at 9:01 a.m., Monday,', 3),
        ('May 4, 2026, before Matthew Bui, CSR No. 14977.', 4)]


def test_appearances_keep_contacts_on_half_lines_and_suites_on_the_street_row():
    _, _, bundle, job, _, _ = covered(field_files(), sample_notice())
    rows = page_rows(bundle, job, 'A P P E A R A N C E S:')
    assert rows == [
        ('A P P E A R A N C E S:', 1),
        ('FOR THE APPLICANT:', 2), ('FIRST FIRM', 3), ('(Zoom videoconference)', 3.5),
        ('BY: SAM ONE, Attorney at Law', 4), ('90 Example Lane, Suite 12', 4.5),
        ('Sample City, California 90001', 5), ('(555) 010-1000', 5.5), ('one@example.test', 6),
        ('FOR THE DEFENDANTS:', 8), ('SECOND FIRM', 9), ('(Zoom videoconference)', 9.5),
        ('BY: LEE TWO, Attorney at Law', 10), ('25 Other Street, Floor 3', 10.5),
        ('Other City, California 90002', 11), ('(555) 010-2000', 11.5), ('two@example.test', 12)]
    assert field_texts(job.native_bytes)['SUITE'] == 'Suite 12'
    assert field_texts(job.native_bytes)['SUITE NO'] == 'Floor 3'


def test_index_uses_native_tabs_and_spaced_headings_on_its_own_sheet():
    _, _, bundle, job, _, _ = covered(field_files(), sample_notice(), index_pages=('5', '16'))
    rows = page_rows(bundle, job, 'I N D E X')
    assert rows[:6] == [
        ('I N D E X', 1), ('WITNESS: CASEY SAMPLE', 2), ('EXAMINATION PAGE', 3),
        ('BY MR. ONE 5', 4), ('BY MS. TWO 16', 5), ('E X H I B I T S', 7)]
    assert ('INSTRUCTIONS NOT TO ANSWER:', 12) in rows
    assert ('INFORMATION REQUESTED:', 17) in rows
    assert re.search(r'EXAMINATION\t+PAGE', job.text)
    # The next tab past the last explicit stop is the left edge of PAGE.
    # Both numbers end below its E, three spaces and two spaces later.
    assert re.search(r'\t+BY MR\. ONE\t{7} {3}5', job.text)
    assert re.search(r'\t+BY MS\. TWO\t{7} {2}16', job.text)


def test_classic_tabbed_caption_keeps_ids_stacked_next_to_the_left_column():
    caption = ('ALEX EXAMPLE,\t\tCASE NO.: ADJ00000123, ADJ00000125\n'
               '\t\t\t\t\t\t\t\t\t24-CV-001234\n'
               '\t\t\tApplicant,\t\t\t\tADJ00000124\n'
               '\t\tvs.\nSAMPLE COMPANY 123,\nDefendants.')
    assert cover._case_numbers(caption, False) == ('ADJ00000123', 'ADJ00000125', '24-CV-001234', 'ADJ00000124')


def test_reopening_a_classic_notice_reads_the_party_names_from_the_left_column():
    from app.tests.test_native_scoped_cover import scoped_bundle
    bundle, _ = scoped_bundle()
    key = bundle.jobs[0]
    native = bundle.read(bundle.member(key + '.sgngl'))
    start, length = codec.u32(native, 532), codec.u32(native, 536)
    paragraph = b'\x16\x08\x00'
    caption = paragraph.join((b'STATE OF CALIFORNIA', b'FIRST SERVICES,\t\tCASE NO.: ADJ00000123',
                              b'INC.,\t\t\t24-CV-001234', b'\t\t\tApplicant,', b' \t\tvs.\t\tADJ00000126',
                              b'                                             ADJ00000127',
                              b'SAMPLE COMPANY/\t\tADJ00000124', b'SECOND FIRM,', b' \t\tDefendants.',
                              b'~' * 30))
    stream = native[start:start + length].replace(b'Filed\tHere\x0aNext row.', caption)
    bundle = bundle.with_job_bytes(key, relocate(native, stream, [(0, 0, length, len(stream))]), None)
    known, _, _ = cover.existing_cover(bundle, codec.load_job(bundle, key))
    assert known['plaintiff'] == 'FIRST SERVICES, INC.'
    assert known['defendant'] == 'SAMPLE COMPANY/SECOND FIRM'
    assert known['case_numbers'] == ('ADJ00000123', '24-CV-001234', 'ADJ00000126', 'ADJ00000127', 'ADJ00000124')


def test_reapplying_preserves_the_reporters_index_and_oath_edits():
    notice = sample_notice()
    files, _, bundle, job, _, original_body = covered(field_files(), notice, index_pages=('5', '16'))
    revision = job.baseline
    revision = revision.revise(revision.text.replace('WITNESS:  ', 'REMOTE WITNESS:  ')
                               .replace('having been first duly sworn', 'having previously been sworn'))
    files[job.key + '.sgngl'] = serialize_candidate(job.with_revision(revision), bundle)
    _, _, _, updated, _, body = covered(files, replace(notice, file_number='FILE456'))

    assert 'REMOTE WITNESS:  CASEY SAMPLE' in updated.text
    assert 'having previously been sworn' in updated.text
    assert 'FILE NO.:  FILE456' in updated.text
    assert updated.text[body:] == job.text[original_body:]
    assert updated.notes_bytes == job.notes_bytes


@pytest.mark.parametrize(('plaintiff', 'defendant', 'title_line'), [
    ('ALEX EXAMPLE', 'SAMPLE COMPANY', 13),
    ('ALEX EXAMPLE', 'A' * 24 + ' ' + 'B' * 12, 14),
    (' '.join(['A' * 24] * 7), ' '.join(['B' * 24] * 5), 18),
], ids=['one-row-parties', 'wrapped-defendant', 'longest-allowed-parties'])
def test_title_follows_the_caption_and_footer_stays_on_lines_24_and_25(plaintiff, defendant, title_line):
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication
    from app.src.native_editor import NativeTranscriptEditor

    notice = replace(sample_notice(), plaintiff=plaintiff, defendant=defendant)
    assert not cover.cover_overflow(notice)
    _, _, bundle, job, _, body = covered(field_files(), notice)
    app = QApplication.instance() or QApplication([])
    font_id = -1
    if not QFontDatabase.families() and Path('C:/Windows/Fonts/cour.ttf').is_file():
        font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/cour.ttf')
    view = NativeTranscriptEditor(QFont('Courier New', 12))
    view.set_native_source(bundle, job)
    view.setPlainText(job.text)
    try:
        rows = view.page_lines()
        for label, line in (('DEPOSITION OF', title_line), ('REPORTED BY:', 24), ('FILE NO.:', 25)):
            row = next(row for row in rows if label in row.text)
            assert row.page == 1
            assert row.y == pytest.approx(view._top + (line - 1) * view._line_height, abs=1)
        recital = next(row for row in rows if 'Deposition of ' in row.text)
        assert recital.page == 2
        assert recital.y == pytest.approx(view._page_height + view._top + (title_line - 2) * view._line_height, abs=1)
        assert next(row.page for row in rows if row.position == body) == 5
    finally:
        view.close()
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


@pytest.mark.parametrize(('defendant', 'title_returns', 'footer_returns'), [
    ('SAMPLE COMPANY', 4, 14),
    ('A' * 24 + ' ' + 'B' * 12, 6, 12),
])
def test_native_spacing_after_caption_keeps_the_file_number_on_page_one(defendant, title_returns, footer_returns):
    # Measured in Case CATalyst Print Preview for single-line and wrapped parties.
    notice = replace(sample_notice(), defendant=defendant)
    _, _, _, job, _, _ = covered(field_files(), notice)
    stream = job.native_bytes
    after_table = cover.TABLE_END + cover.SINGLE_OFF
    half = cover._p(9)
    assert after_table + half * title_returns + cover._p(7, 'DEPOSITION OF') in stream
    assert after_table + half * (title_returns - 2) + cover._p(8, b'\t\t\tDeposition of ') in stream
    assert b'\x12\x88 ' + half * footer_returns + cover._p(9, 'REPORTED BY:') in stream


def test_reapplying_a_notice_keeps_its_singular_role_and_docket_spacing():
    notice = sample_notice()
    files, _, bundle, job, _, _ = covered(field_files(), notice)
    changed = job.baseline.revise(job.text.replace('Defendants.', 'Defendant.').replace('CASE NO.: ', 'CASE NO.:  '))
    files[job.key + '.sgngl'] = serialize_candidate(job.with_revision(changed), bundle)
    _, _, _, rebuilt, _, _ = covered(files, replace(notice, file_number='UPDATED'))
    assert rebuilt.text.count('Defendant.') == 2
    assert rebuilt.text.count('CASE NO.:  ADJ00000123') == 2
