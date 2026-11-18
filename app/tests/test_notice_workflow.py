from dataclasses import replace

from app.src import notice_model as notices


def test_filename_prefill_preserves_identifier_and_ignores_date_and_adj():
    assert notices.filename_file_number('261110thaler 1757905.pdf') == '1757905'
    assert notices.filename_file_number('261029kadri J015250856.PDF') == 'J015250856'
    for name in ('261110thaler.pdf', '261110.pdf', 'notice ADJ18095652.pdf'):
        assert notices.filename_file_number(name) == ''


def test_vocabulary_uses_confirmed_people_firms_and_caption_entities():
    appearance = notices.Appearance('Applicant', 'Advocates LLP', 'Ada Young', email='ada@example.com')
    details = notices.NoticeDetails(plaintiff='Jane Ellis', defendant='Blue Mill, Inc., insured by Plains Insurance Company; Sedgwick',
                                   deponent='Dr. Alan Xue', appearances=(appearance, replace(appearance, side='Defendant')))
    terms = details.vocabulary()
    assert {'Ada Young', 'Advocates LLP', 'Jane Ellis', 'Blue Mill, Inc.', 'Plains Insurance Company', 'Sedgwick', 'Dr. Alan Xue'} <= set(terms)
    assert terms.count('Ada Young') == 1 and 'ada@example.com' not in terms
    assert notices.NoticeDetails.from_dict(details.to_dict()) == details


def test_body_review_keeps_cover_spaces_and_discards_only_a_repeated_intro():
    from app.src.casecat.anchors import AnchoredSpan, Revision
    from app.src.notice_review import response_body, split_revision, joined_snapshot
    intro = 'My name is Matthew Bui.  I am a California Certified Shorthand Reporter, CSR No. 14977.'
    prefix = 'Plaintiff   \nMR. REPORTER:  ' + intro + '\n'
    original = Revision((AnchoredSpan('first', (0,), (), prefix + 'Old question.'),))
    head, body = split_revision(original, len(prefix))
    assert body.text == 'Old question.'
    assert response_body(head.text, '     THE REPORTER:  ' + intro + '\nEXAMINATION\nNew question.') == 'EXAMINATION\nNew question.'
    different = '     THE REPORTER:  My license changed yesterday.'
    assert response_body(head.text, different) == different
    original2, incoming, _ = joined_snapshot(head, head, (body, body.revise('New question.'), None))
    assert original2.text == original.text and incoming.text == prefix + 'New question.'
    assert [s.identity for s in incoming.spans].count('first') == 1


def test_portable_notice_preserves_source_pdf_and_effective_native_job(tmp_path, monkeypatch):
    from app.src import documents
    from app.src.casecat.codec import load_job
    from app.src.casecat.project import AttachedNotice
    from app.tests.test_native_projects import native_doc
    doc, source = native_doc(tmp_path, monkeypatch)
    state = doc.native
    pdf = b'%PDF-1.4\nexample source'
    attachment = AttachedNotice('notice.pdf', pdf, notices.NoticeDetails(deponent='Lea'),
                                state.job.native_bytes, None, 1)
    state.notice = attachment
    state.bundle = state.bundle.with_job_bytes(state.job.key, attachment.native_bytes, None)
    assert load_job(state.bundle, state.job.key).text == doc.original
    documents.save_document(doc, tmp_path/'test.bababui')
    documents.save_session(tmp_path/'session.json', [doc, doc.duplicate()], doc.id)
    source.unlink()
    for restored in (documents.open_document(tmp_path/'test.bababui'),
                     documents.load_session(tmp_path/'session.json')[0][1]):
        assert restored.native.notice == attachment
        assert restored.native.body_position(restored.native.original) == 1
        assert restored.native.bundle.data == state.bundle.data


def test_notice_review_requires_side_and_prefills_file_only_when_enabled(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.src.notice_dialog import NoticeWizard
    app = QApplication.instance() or QApplication([])
    pdf = notices.NoticeDetails(plaintiff='Jane Ellis')
    recording = notices.NoticeDetails(speakers=('MR. ONE', 'MS. TWO'))
    wizard = NoticeWizard('261110thaler 1757905.pdf', pdf, notices.NoticeDetails(), recording, False)
    assert wizard.details().file_number == ''
    assert not wizard.page(1).isComplete()
    wizard.sides['Applicant'].click()
    assert wizard.page(1).isComplete()
    assert wizard.details().taking_side == 'Applicant'
    assert wizard.details().speakers == recording.speakers
    preset = NoticeWizard('261029kadri J15250856.pdf', replace(pdf, taking_side='Defendant'),
                          notices.NoticeDetails(), recording, True)
    assert preset.details().file_number == 'J15250856' and preset.sides['Defendant'].isChecked()
    assert (preset.details().plaintiff, preset.details().defendant) == ('Jane Ellis', '')
    wizard.close()
    preset.close()


def test_zip_fields_use_the_first_steno_clock_and_written_recording_date():
    from types import SimpleNamespace
    from app.src.casecat.anchors import Revision
    definitions = (('CREATION DATE IN WORDS', 'October 29, 2026'), ('EZ SPEAKER 01', 'MR. ONE'))
    notes = bytearray(656)
    notes[644:648] = ((8*3600 + 29*60 + 56)*100).to_bytes(4, 'little')
    notes[652:656] = ((8*3600 + 33*60)*100).to_bytes(4, 'little')
    job = SimpleNamespace(key='job', baseline=Revision((), definitions=definitions), notes_bytes=notes)
    actual = notices.recording_details(SimpleNamespace(member=lambda name: None), job)
    assert (actual.time, actual.weekday, actual.date) == ('8:29 a.m.', 'Thursday', 'October 29, 2026')
    assert actual.speakers == ('MR. ONE', '')


def test_recorded_oath_and_extra_reporter_words_survive_according_to_the_template():
    from app.src.notice_review import response_body
    oath = 'Lea Young,\nhaving been first duly sworn, was\nexamined and testified as follows:'
    introduction = 'My name is Laura Reid.  I am a certified shorthand reporter.'
    prefix = oath + '\n\nMR. REPORTER:  ' + introduction + '\n'
    recording = oath + '\n     THE REPORTER:  ' + introduction + '  Please identify yourself.\n'
    assert response_body(prefix, recording) == '     THE REPORTER:  Please identify yourself.\n'
    spoken_oath = '     THE REPORTER:  Do you solemnly swear to tell the truth?\n     A    Yes.'
    assert response_body(prefix, spoken_oath) == spoken_oath
    different_introduction = '     THE REPORTER:  My name is Laura.'
    assert response_body(prefix, different_introduction) == different_introduction


def test_reimported_native_cover_is_protected_without_an_attached_pdf():
    from app.src.casecat.project import NativeState
    from app.src.notice_review import begin_document_review, auto_accept_document
    from app.tests.test_native_notice_cover import covered, details, field_files
    _, _, bundle, job, _, start = covered(field_files(), details())
    state = NativeState.load(bundle, job.key)
    assert state.notice is None and state.body_position(state.original) == start
    prefix = state.original.text[:start]
    begin_document_review(state, 'Replacement testimony only.')
    auto_accept_document(state, disabled_rules=frozenset())
    assert state.original.text.startswith(prefix) and state.incoming.text == prefix + 'Replacement testimony only.'


def test_late_notice_preserves_pending_body_edits_and_native_speaker(tmp_path):
    from app.src.casecat import archive, codec
    from app.src.casecat.project import NativeState, project_bytes, read_project
    from app.src.notice_review import begin_document_review
    from app.tests.test_native_notice_cover import details, field_files, zip_bytes
    source = archive.inspect_archive(zip_bytes(field_files()))
    state = NativeState.load(source, source.jobs[0])
    pos = state.original.text.index('Question?')
    state.original = state.original.replace(pos, pos + 8, 'Which question?')
    begin_document_review(state, state.original.text.replace('Which question?', 'Whose question?'))
    updated = state.with_notice('original.pdf', b'%PDF original', details(), ())
    updated = read_project(project_bytes(updated, {}))[0]
    for side, question in ((updated.original, 'Which question?'), (updated.incoming, 'Whose question?')):
        start = updated.body_position(side)
        assert start > 0 and question in side.text[start:]
        assert 'MS. RAY' in side.text[start:]
        assert side.text[:start].count("WORKERS' COMPENSATION APPEALS BOARD") == 2
    assert updated.notice.pdf == b'%PDF original' and updated.bundle.data == source.data
    target = tmp_path / 'covered.zip'
    archive.export_zip(updated.bundle, updated.job.with_revision(updated.original), target)
    exported = archive.inspect_archive(target)
    assert codec.load_job(exported, exported.jobs[0]).text == updated.original.text


def test_recording_and_confirmed_recognition_names_stay_independent():
    from app.src.casecat import archive
    from app.src.casecat.project import NativeState
    from app.tests.test_native_notice_cover import details, field_files, zip_bytes
    source = archive.inspect_archive(zip_bytes(field_files()))
    state = NativeState.load(source, source.jobs[0])
    original_labels = state.recording.speakers
    assert original_labels[0] == 'MS. OLD'
    state = state.with_notice('court.pdf', b'%PDF', details(), ())
    assert state.recording.speakers == original_labels
    edit = state.original.set_field('ATTORNEY1', 'Drew Nguyen')
    words = state.notice.details.with_current_names(edit).vocabulary()
    assert 'Drew Nguyen' in words and 'BEN SMITH' not in words
    details_without_counsel = notices.NoticeDetails(defendant='Blue Mill, Inc., Plains Insurance Company',
                                                    speakers=('MS. NGUYEN', 'MR. CARLISLE'))
    assert set(details_without_counsel.vocabulary()) == {'Blue Mill, Inc.', 'Plains Insurance Company', 'NGUYEN', 'CARLISLE'}


def test_confirmed_side_assigns_unlabeled_counsel_and_revisits_preserve_edits():
    from PySide6.QtWidgets import QApplication
    from app.src.notice_dialog import NoticeWizard
    app = QApplication.instance() or QApplication([])
    pdf = notices.NoticeDetails(appearances=(notices.Appearance('', 'Summit Law LLP', 'Anna Lane'),))
    empty = notices.NoticeDetails()
    wizard = NoticeWizard('notice.pdf', pdf, empty, empty, False)
    wizard.show()
    wizard.next()
    assert not wizard.page(1).isComplete()
    wizard.sides['Defendant'].click()
    wizard.next()
    assert wizard.details().appearances == (notices.Appearance('Defendant', 'Summit Law LLP', 'Anna Lane'),)
    wizard.appearance_entries[0][1]['firm'].setText('Opposing law firm')
    wizard.back()
    wizard.next()
    assert wizard.details().appearances[0].firm == 'Opposing law firm'
    wizard.close()


def test_conflicting_long_caption_values_fit_the_review_window():
    from PySide6.QtWidgets import QApplication
    from app.src.notice_dialog import NoticeWizard
    app = QApplication.instance() or QApplication([])
    value = 'MUNICIPAL SERVICES AND CONTRACTORS GROUP, INC., INSURED BY COUNTY INSURANCE'
    pdf = notices.NoticeDetails(defendant=value)
    existing = notices.NoticeDetails(defendant=value + ' AND ADJUSTMENT SERVICES')
    wizard = NoticeWizard('notice.pdf', pdf, existing, notices.NoticeDetails(), False)
    wizard.show()
    app.processEvents()
    assert wizard.width() <= 800
    wizard.close()
