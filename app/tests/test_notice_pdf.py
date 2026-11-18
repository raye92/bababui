"""Exercise local extraction with generated notices and no client data."""
import os
from pathlib import Path
import sys

import pymupdf
import pytest


def put(page, x, y, *lines):
    for i, text in enumerate(lines):
        page.insert_text((x, y + i * 15), text, fontsize=10)


def note(page, x, y, text):
    page.add_freetext_annot((x, y, x + 155, y + 24), text, fontsize=9)


def sample(*, service=True, marked=True):
    pdf = pymupdf.open()
    page = pdf.new_page(width=612, height=792)
    put(page, 72, 65, 'Noel Stone, State Bar No. 111111', 'River Law LLP',
        '200 Willow Ave., Ste. B', 'Los Gatos, CA 95030', 'Telephone: (408) 555-0100',
        'Facsimile: (408) 555-0109', 'nstone@river.example', 'Attorneys for Defendant')
    if marked:
        note(page, 267, 48, 'Taylor Reed')
        note(page, 264, 113, 'treed@river.example')
    put(page, 140, 220, "WORKERS' COMPENSATION APPEALS BOARD")
    put(page, 72, 275, 'FRANCIS LAKE,', 'Applicant,', 'v.', 'MEADOW GROUP, INC.;',
        'insured by WESTERN INSURANCE,', 'administered by RIDGE CLAIMS,', 'Defendants.')
    put(page, 331, 275, 'WCAB Case No. ADJ30123456;', 'ADJ30123001', '',
        'NOTICE OF TAKING DEPOSITION', 'OF DR. CASEY ROSS')
    put(page, 72, 445, 'TO ALL PARTIES AND THEIR ATTORNEYS OF RECORD:',
        'Please take notice that Defendant will take the deposition of Dr. Casey Ross.',
        'DATE: September 10, 2026', 'TIME: 9:00 AM')
    if service:
        page = pdf.new_page(width=612, height=792)
        put(page, 210, 70, 'PROOF OF SERVICE BY MAIL')
        put(page, 72, 103, 'I served a copy of the attached notice, addressed as follows:')
        put(page, 72, 168, 'Jordan Ames, Esq.', 'Grove Law Group', '908 Juniper Street',
            'Suite 24', 'Ventura, CA 93001', 'Tel: (805) 555-0111')
        put(page, 355, 168, 'Pat Heller', 'Western Insurance', '123 Coast Drive',
            'Berkeley, CA 94701', 'pat@carrier.example')
        put(page, 72, 322, 'Casey Ross, D.D.S.', 'Medical Evaluations',
            '821 Bay Road', 'Fresno, CA 93720')
        put(page, 355, 322, 'North Court Reporters', '300 Pine Road',
            'Irvine, CA 92606')
        if marked:
            page.add_highlight_annot(page.search_for('Jordan Ames')[0])
            note(page, 212, 191, 'james@grove.example')
            note(page, 446, 158, 'Pat Heller')
        put(page, 72, 525, 'An unrelated matter on the service list: ADJ99999001.')
    data = pdf.tobytes()
    pdf.close()
    return data


def extract(data):
    from app.src.notice_pdf import extract_notice
    return extract_notice(data)


def test_preserves_caption_columns_order_and_explicit_witness_credentials():
    result = extract(sample())
    assert result.plaintiff == 'FRANCIS LAKE'
    assert result.defendant == ('MEADOW GROUP, INC.; insured by WESTERN INSURANCE, '
                                'administered by RIDGE CLAIMS')
    assert result.case_numbers == ('ADJ30123456', 'ADJ30123001')
    assert result.deponent.upper() == 'CASEY ROSS, D.D.S.'
    assert result.taking_side == 'Defendant'
    assert not any((result.time, result.weekday, result.date, result.file_number))


def test_annotations_select_attorneys_and_stay_with_their_address_column():
    result = extract(sample())
    by_side = {row.side: row for row in result.appearances}
    assert len(result.appearances) == len(by_side) == 2
    defense = by_side['Defendant']
    assert (defense.attorney, defense.firm) == ('Taylor Reed', 'River Law LLP')
    assert (defense.address, defense.suite) == ('200 Willow Ave.', 'Ste. B')
    assert (defense.city, defense.state, defense.zip_code) == ('Los Gatos', 'CA', '95030')
    assert (defense.phone, defense.email) == ('(408) 555-0100', 'treed@river.example')
    applicant = by_side['Applicant']
    assert (applicant.attorney, applicant.firm, applicant.title) == ('Jordan Ames', 'Grove Law Group', 'Esq.')
    assert (applicant.address, applicant.suite) == ('908 Juniper Street', 'Suite 24')
    assert (applicant.phone, applicant.email) == ('(805) 555-0111', 'james@grove.example')


def test_accepts_one_sided_notice_and_preserves_a_doctor_prefix_without_a_degree():
    result = extract(sample(service=False, marked=False))
    assert len(result.appearances) == 1
    row, = result.appearances
    assert (row.side, row.attorney, row.email) == ('Defendant', 'Noel Stone', 'nstone@river.example')
    assert result.deponent.upper() == 'DR. CASEY ROSS'


def test_reads_noticing_side_from_represented_party_and_additional_explicit_roles():
    pdf = pymupdf.open()
    page = pdf.new_page(width=612, height=792)
    put(page, 72, 80, 'Quinn Lake (SBN: 121212)', 'Juniper Law LLP',
        'Attorney for Chris Park', "WORKERS' COMPENSATION APPEALS BOARD")
    put(page, 72, 240, 'CHRIS PARK,', 'Applicant,', 'vs.', 'NORTH SERVICES,', 'Defendant.')
    put(page, 326, 240, 'WCAB NO: ADJ30121212', 'NOTICE OF DEPOSITION OF',
        'DEVON KEEN, Ph.D.')
    page = pdf.new_page(width=612, height=792)
    put(page, 160, 68, 'SERVICE LIST')
    put(page, 72, 158, 'Attorney for Defendant', 'Riley Gray, Esq.', 'Oak Law LLP',
        '124 Lake Drive', 'Irvine, CA 92606')
    put(page, 340, 158, 'Co-Counsel for Defendant', 'Sasha Bell, Esq.', 'Hill Law LLP',
        '25 Moss Road', 'Fresno, CA 93720')
    result = extract(pdf.tobytes())
    pdf.close()
    assert result.taking_side == 'Applicant'
    assert {(r.side, r.attorney) for r in result.appearances} == {
        ('Applicant', 'Quinn Lake'), ('Defendant', 'Riley Gray'), ('Defendant', 'Sasha Bell')}


def test_skips_signer_email_for_different_attendee_and_leaves_unwritten_firm_blank():
    pdf = pymupdf.open(stream=sample(service=False, marked=False), filetype='pdf')
    page = pdf[0]
    note(page, 270, 57, 'Taylor Reed')
    page = pdf.new_page(width=612, height=792)
    put(page, 175, 90, 'CERTIFICATE OF SERVICE')
    put(page, 72, 190, 'Jordan Ames, Esq.', '325 Park Avenue', 'Vista, CA 92084')
    page.add_highlight_annot(page.search_for('Jordan Ames')[0])
    result = extract(pdf.tobytes())
    pdf.close()
    rows = {r.side: r for r in result.appearances}
    assert rows['Defendant'].email == ''
    assert rows['Applicant'].attorney == 'Jordan Ames'
    assert rows['Applicant'].firm == ''


def test_medical_legal_provider_cannot_displace_an_opposing_attorney():
    pdf = pymupdf.open(stream=sample(), filetype='pdf')
    page = pdf.new_page(width=612, height=792)
    put(page, 72, 108, 'Dr. Casey Ross', 'Valley Legal Group',
        '45 Pine Street', 'Ventura, CA 93001')
    result = extract(pdf.tobytes())
    pdf.close()
    assert {row.attorney for row in result.appearances} == {'Jordan Ames', 'Taylor Reed'}


def test_local_mailbox_and_title_follow_the_named_signatory():
    pdf = pymupdf.open()
    page = pdf.new_page(width=612, height=792)
    put(page, 72, 65, 'Lane Green, State Bar No. 123456', 'Jordan Gray, SBN: 246810',
        'Moss Law LLP', 'P.O. Box 12488', 'Oakland, CA 94604-2488', 'Attorney for Applicant')
    put(page, 150, 220, "WORKERS' COMPENSATION APPEALS BOARD")
    put(page, 72, 280, 'Chris Park,', 'Applicant,', 'vs.', 'Oak Services,', 'Defendant.')
    page = pdf.new_page(width=612, height=792)
    put(page, 330, 130, 'Respectfully submitted,', 'By:', 'Jordan Gray', 'Senior Partner',
        'Counsel for Applicant')
    result = extract(pdf.tobytes())
    pdf.close()
    row, = result.appearances
    assert (row.attorney, row.title) == ('Jordan Gray', 'Senior Partner')
    assert (row.address, row.city, row.state, row.zip_code) == (
        'P.O. Box 12488', 'Oakland', 'CA', '94604-2488')


def test_unboxed_notice_uses_its_labeled_parties_and_deposition_sentence():
    pdf = pymupdf.open()
    page = pdf.new_page()
    put(page, 72, 80, 'Applicant: Morgan Rush', 'Defendant: Brook Valley, Inc.',
        'WCAB Case No.: ADJ23567891',
        'Applicant will take the deposition of Dr. Riley James on July 2, 2026.')
    result = extract(pdf.tobytes())
    pdf.close()
    assert (result.plaintiff, result.defendant) == ('Morgan Rush', 'Brook Valley, Inc.')
    assert result.case_numbers == ('ADJ23567891',)
    assert result.deponent == 'Dr. Riley James'
    assert result.taking_side == 'Applicant'
    assert not result.appearances


def test_mixed_court_case_numbers_follow_their_label_and_preserve_order():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        put(page, 72, 180, 'SUPERIOR COURT OF CALIFORNIA')
        put(page, 72, 240, 'Sam Lane,', 'Plaintiff,', 'v.', 'Oak Group,', '', '', '', 'Defendant.')
        put(page, 321, 240, 'Court Case Nos.:')
        put(page, 430, 240, '26STCV40123,')
        put(page, 321, 255, '2:26-cv-00210-AB; ADJ12345678;', '26STCV40123',
            'Claim no.: ADJ99999001', 'File no.: 03046', 'Insurance Policy No. GH444444',
            'CASE NO. 00012345 / File No. 667711')
        result = extract(pdf.tobytes())
    assert result.case_numbers == ('26STCV40123', '2:26-cv-00210-AB', 'ADJ12345678', '00012345')


def test_ambiguous_adj_is_not_a_generic_docket_and_a_printed_civil_prefix_is_preserved():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        put(page, 72, 95, 'COURT CASE NO. ADJI1234567', 'Civil Case No. CV 26-00401',
            '100 Main Street', 'October 8, 2026')
        result = extract(pdf.tobytes())
    assert result.case_numbers == ('CV 26-00401',)


def test_keeps_distinct_attorneys_from_one_firm_and_skips_the_repeated_counsel():
    with pymupdf.open(stream=sample(service=False, marked=False), filetype='pdf') as pdf:
        page = pdf.new_page(width=612, height=792)
        put(page, 150, 75, 'PROOF OF SERVICE')
        put(page, 72, 180, 'Avery Hill, Esq.', 'River Law LLP', 'Attorney for Defendant',
            '200 Willow Avenue', 'Los Gatos, CA 95030')
        put(page, 72, 310, 'Noel Stone, Esq.', 'River Law LLP', 'Attorney for Defendant',
            '200 Willow Avenue', 'Los Gatos, CA 95030')
        put(page, 72, 445, 'Remy Bell, Esq.', 'River Law LLP',
            '200 Willow Avenue', 'Los Gatos, CA 95030')
        page.add_highlight_annot(page.search_for('Remy Bell')[0])
        result = extract(pdf.tobytes())
    assert [(r.side, r.attorney) for r in result.appearances] == [
        ('Defendant', 'Noel Stone'), ('Defendant', 'Avery Hill'), ('Defendant', 'Remy Bell')]


@pytest.mark.parametrize('header, expected', [
    (('Noel Stone, State Bar No. 111111', 'River Law LLP'), ('Noel Stone', 'River Law LLP')),
    (('Dr. Casey Ross', 'Valley Legal Group'), None),
    (('Riley Hale', 'Meadow Insurance Company'), None),
])
def test_keeps_only_a_counsel_letterhead_when_the_noticing_side_is_unclear(header, expected):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        put(page, 72, 65, *header, '21 Garden Road', 'Los Gatos, CA 95030')
        put(page, 72, 180, 'SUPERIOR COURT OF CALIFORNIA')
        put(page, 72, 240, 'Sam Lane,', 'Plaintiff,', 'v.', 'Oak Group,', 'Defendant.')
        result = extract(pdf.tobytes())
    assert result.taking_side == ''
    if expected:
        row, = result.appearances
        assert row.side == ''
        assert (row.attorney, row.firm) == expected
    else:
        assert not result.appearances


def test_a_taking_side_in_the_body_does_not_make_an_insurer_letterhead_counsel():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        put(page, 72, 65, 'Riley Hale', 'Meadow Insurance Company', '21 Garden Road', 'Los Gatos, CA 95030')
        put(page, 72, 180, 'SUPERIOR COURT OF CALIFORNIA')
        put(page, 72, 240, 'Sam Lane,', 'Plaintiff,', 'v.', 'Oak Group,', 'Defendant.')
        put(page, 72, 362, 'Defendant will take the deposition of Dr. Casey Ross.')
        result = extract(pdf.tobytes())
    assert result.taking_side == 'Defendant'
    assert not result.appearances


@pytest.mark.skipif(sys.platform != 'win32', reason='Uses the installed Windows English OCR engine')
def test_reads_an_image_only_notice_with_real_local_ocr():
    from PySide6.QtWidgets import QApplication
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine
    if not OcrEngine.is_language_supported(Language('en-US')):
        pytest.skip('English text recognition is not installed in Windows.')
    app = QApplication.instance() or QApplication([])
    source = pymupdf.open(stream=sample(service=False, marked=False), filetype='pdf')
    raster = pymupdf.open()
    page = raster.new_page(width=612, height=792)
    pixmap = source[0].get_pixmap(matrix=pymupdf.Matrix(2, 2))
    page.insert_image(page.rect, pixmap=pixmap)
    assert not page.get_text().strip()
    result = extract(raster.tobytes())
    source.close()
    raster.close()
    assert result.plaintiff == 'FRANCIS LAKE'
    assert result.taking_side == 'Defendant'
    assert result.case_numbers == ('ADJ30123456', 'ADJ30123001')
    assert result.deponent.upper() == 'DR. CASEY ROSS'


@pytest.mark.skipif(sys.platform != 'win32', reason='Uses the installed Windows English OCR engine')
def test_recovers_a_numeric_case_identifier_in_a_serif_scan():
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine
    font = Path(os.environ['WINDIR']) / 'Fonts' / 'times.ttf'
    if not font.exists() or not OcrEngine.is_language_supported(Language('en-US')):
        pytest.skip('The serif font or English text recognition is unavailable.')
    with pymupdf.open() as source, pymupdf.open() as raster:
        page = source.new_page(width=612, height=792)
        put(page, 140, 210, "WORKERS' COMPENSATION APPEALS BOARD")
        put(page, 72, 245, 'SAM LANE,', 'Applicant,', '- vs -', 'PARK GROUP,', 'Defendant.')
        page.insert_text((325.51, 246.89), 'CASE NO: ADJ17468129', fontsize=12,
                         fontname='SerifNotice', fontfile=str(font))
        image_page = raster.new_page(width=612, height=792)
        image_page.insert_image(image_page.rect, pixmap=page.get_pixmap(matrix=pymupdf.Matrix(2.3, 2.3)))
        result = extract(raster.tobytes())
    assert result.case_numbers == ('ADJ17468129',)
    assert result.defendant == 'PARK GROUP'


def test_invalid_pdf_raises_a_readable_error():
    with pytest.raises(ValueError, match='PDF'):
        extract(b'not a PDF')
