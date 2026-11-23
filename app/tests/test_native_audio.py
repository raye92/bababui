"""Synthetic recording clocks, pauses, and native anchor playback."""
import os
import struct
import wave

import pytest

from app.src.casecat.anchors import AnchoredSpan


def audio_archive(tmp_path, resume_clock=13000, stop_elapsed=4000, last='gamma.', *, copy_stroke=False,
                  editable=False, embedded_clock_high_byte=0):
    from app.src.casecat import archive
    from app.tests.test_native_casecat import job_files, zip_bytes
    clocks = (10600, 13200, 14000)
    notes = bytes(640) + b''.join(struct.pack('<II', 1, clock) for clock in clocks)
    marker = lambda clock, size: (b'\x15\x08\x08\0\0\0' + struct.pack('<II', clock, size)).hex()
    spans = (AnchoredSpan('a', (0,), (marker(10500, 158400),), 'Alpha '),
             AnchoredSpan('b', (1,), (marker(13100, 350400),), 'beta '),
             AnchoredSpan('c', (2,), (), last))
    events = [(10000, 0, 0), (11000, 1000, 1), (resume_clock, 1000, 0), (16000, stop_elapsed, 1)]
    xml = '<JobHistory><Read-Settings>'
    for field, index in (('Timestamp', 0), ('ElapsedTime', 1), ('Pause', 2)):
        xml += f'<Read-Audio-{field}>' + ''.join(
            f'<Read-Audio-{field}-{n} sgpref-val="{event[index]}"/>' for n, event in enumerate(events))
        xml += f'</Read-Audio-{field}>'
    xml += '</Read-Settings></JobHistory>'
    wav = tmp_path/'sample.wav'
    with wave.open(str(wav), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(bytes(32000 * 40))
    embedded_clocks = (clocks[0], clocks[1] | (embedded_clock_high_byte << 24), clocks[2])
    groups = [b'\x13\x01\x01' + struct.pack('<II', 1, clock) +
              b''.join(bytes.fromhex(value) for value in span.audio) + span.content.encode('cp1252')
              for clock, span in zip(embedded_clocks, spans)]
    if copy_stroke:
        groups.insert(2, b'\x13\x01\x01' + struct.pack('<II', 1, clocks[0]) + b'copied ')
    stream = b''.join(groups)
    audio = b'example.wav'.ljust(260, b'\0') + struct.pack('<I', len(events))
    audio += b''.join(struct.pack('<III', paused, clock, elapsed) for clock, elapsed, paused in events)
    if editable:
        from app.tests.test_native_structure import container_files
        from app.src.casecat.structure import relocate
        files = container_files(tuple(span.content for span in spans))
        native = files['jobs/example.sgngl']
        old_end = 1024 + struct.unpack_from('<I', native, 536)[0]
        candidate = bytearray(relocate(native, stream, [(0, 0, old_end - 1024, len(stream))]))
        start, size = struct.unpack_from('<II', candidate, 556)
        assert start + size == len(candidate)
        candidate[start:] = audio
        struct.pack_into('<I', candidate, 560, len(audio))
    else:
        files = job_files(tuple(span.content for span in spans))
        candidate = bytearray(files['jobs/example.sgngl'][:1024])
        struct.pack_into('<I', candidate, 536, len(stream))
        struct.pack_into('<II', candidate, 556, len(candidate) + len(stream), len(audio))
        candidate += stream + audio
    struct.pack_into('<I', candidate, 652, 0x10f0f)
    files.update({'jobs/example.sgngl': bytes(candidate),
                  'jobs/example.sgstn': files['jobs/example.sgstn'][:640] + notes[640:],
                  'jobs/example.sgxml': xml.encode(), 'jobs/example.wav': wav.read_bytes()})
    return archive.inspect_archive(zip_bytes(files))


def timing_source(tmp_path, **recording):
    from app.src.casecat import timing, codec
    bundle = audio_archive(tmp_path, **recording)
    job = codec.load_job(bundle, bundle.jobs[0])
    return timing.AudioMap.from_job(bundle, job, tmp_path/'sample.wav'), job.baseline


def test_import_uses_note_clock_and_preserves_differing_embedded_byte(tmp_path, monkeypatch):
    from app.src import documents
    from app.src.casecat.timing import AudioMap

    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path / 'assets')
    bundle = audio_archive(tmp_path, editable=True, embedded_clock_high_byte=0x6e)
    doc = documents.import_casecat(bundle)
    job = doc.native.job
    assert job.text == 'Alpha beta gamma.'
    assert job.stroke_clocks == (10600, 13200, 14000)
    playback = AudioMap.from_job(bundle, job, doc.wav_path)
    assert playback.position_ms(job.baseline, job.text.index('beta')) == 11940

    doc.native.original = job.baseline.replace(6, 10, 'second')
    target = tmp_path / 'edited.zip'
    doc.export_casecat(target, corrected_audio=False)
    restored = documents.import_casecat(target)
    assert restored.original == 'Alpha second gamma.'
    assert restored.native.job.stroke_clocks == job.stroke_clocks
    assert restored.native.job.notes_bytes == job.notes_bytes
    assert b'\x13\x01\x01' + struct.pack('<II', 1, (0x6e << 24) | 13200) in restored.native.job.native_bytes


@pytest.mark.parametrize('embedded_clock_high_byte', [0, 0x6e])
def test_casecat_export_retimes_strokes_without_changing_keys_or_wav(tmp_path, monkeypatch, embedded_clock_high_byte):
    from hashlib import sha256
    from app.src import documents
    from app.src.casecat import archive, codec
    from app.src.casecat.timing import AudioMap
    from app.src.speech_alignment import SpeechAlignment

    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path / 'assets')
    doc = documents.import_casecat(audio_archive(tmp_path, embedded_clock_high_byte=embedded_clock_high_byte))
    bundle, job = doc.native.bundle, doc.native.job
    wav = bundle.read(job.audio_member)
    doc.native.alignment = SpeechAlignment(sha256(wav).hexdigest(), 40000,
        (4000, 10000, 18000),
        (('alpha', 4000), ('beta', 10000), ('gamma', 18000)))
    target = tmp_path / 'retimed.zip'
    doc.export_casecat(target)
    restored = archive.inspect_archive(target)
    exported = codec.load_job(restored, 'jobs/example_AI')
    assert exported.text == job.text
    assert restored.read(exported.audio_member) == wav
    assert exported.notes_bytes[:640] == job.notes_bytes[:640]
    assert [key for key, _ in struct.iter_unpack('<II', exported.notes_bytes[640:])] == [1, 1, 1]
    assert exported.stroke_clocks == (10400, 13000, 13800)
    start, length = struct.unpack_from('<II', exported.native_bytes, 532)
    embedded = b''.join(raw[3:] for _, raw in codec.records(exported.native_bytes, start, start + length)
                        if raw[0] == 0x13)
    assert embedded == exported.notes_bytes[640:]
    assert AudioMap.from_job(restored, exported, tmp_path / 'sample.wav').stroke_ms == (4000, 10000, 18000)
    assert bundle.read(bundle.member(job.key + '.sgstn')) == job.notes_bytes
    assert bundle.read(bundle.member(job.key + '.sgngl')) == job.native_bytes


def test_export_uses_audio_for_accepted_wording_at_its_serialized_stroke(tmp_path, monkeypatch):
    from hashlib import sha256
    from app.src import documents
    from app.src.casecat import archive, codec
    from app.src.casecat.timing import AudioMap
    from app.src.speech_alignment import SpeechAlignment

    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path / 'assets')
    doc = documents.import_casecat(audio_archive(tmp_path, last='gamma delta epsilon.', editable=True))
    bundle, job = doc.native.bundle, doc.native.job
    digest = sha256(bundle.read(job.audio_member)).hexdigest()
    doc.native.alignment = SpeechAlignment(digest, 40000, (4000, 10000, 18000), (
        ('alpha', 4000), ('signed', 6000), ('beta', 10000),
        ('gamma', 18000), ('delta', 18500), ('epsilon', 19000)))
    doc.native.original = job.baseline.replace(6, 6, 'signed ')
    doc.native.incoming = job.baseline.replace(6, 6, 'pending ')
    target = tmp_path / 'retimed.zip'
    doc.export_casecat(target)
    restored = archive.inspect_archive(target)
    exported = codec.load_job(restored, 'jobs/example_AI')
    assert exported.text == 'Alpha signed beta gamma delta epsilon.'
    assert AudioMap.from_job(restored, exported, tmp_path / 'sample.wav').stroke_ms == (4000, 6000, 18000)


@pytest.mark.parametrize('copy_stroke', [False, True])
def test_casecat_export_requires_explicit_fallback_for_an_unsupported_job(tmp_path, monkeypatch, copy_stroke):
    from hashlib import sha256
    from app.src import documents
    from app.src.casecat import archive, codec
    from app.src.speech_alignment import SpeechAlignment

    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path / 'assets')
    doc = documents.import_casecat(audio_archive(tmp_path, copy_stroke=copy_stroke))
    bundle, job = doc.native.bundle, doc.native.job
    digest = sha256(bundle.read(job.audio_member)).hexdigest() if copy_stroke else 'f' * 64
    times = (4000, 10000, 14000, 18000) if copy_stroke else (4000, 10000, 18000)
    doc.native.alignment = SpeechAlignment(digest, 40000, times, (('alpha', 4000), ('beta', 10000), ('gamma', 18000)))
    target = tmp_path / 'unchanged.zip'
    with pytest.raises(ValueError, match='copied strokes' if copy_stroke else 'ZIP contains a different WAV'):
        doc.export_casecat(target)
    assert not target.exists()
    doc.export_casecat(target, corrected_audio=False)
    copied = archive.inspect_archive(target)
    assert codec.load_job(copied, 'jobs/example_AI').notes_bytes == doc.native.job.notes_bytes


@pytest.mark.parametrize('audio_view', ['gamma delta epsilon.'], indirect=True)
def test_bababui_timing_follows_review_and_survives_project_and_recovery(audio_view, tmp_path):
    from hashlib import sha256
    from pathlib import Path
    from PySide6.QtWidgets import QApplication
    from app.src import documents
    from app.src.audio_pipeline import Word
    from app.src.speech_alignment import align_speech
    from app.src.document_view import DocumentView

    view = audio_view
    doc = view.document
    digest = sha256(Path(doc.wav_path).read_bytes()).hexdigest()
    words = tuple(Word(text, 's1', start, start + .1) for text, start in
                  (('Alpha', 4), ('signed', 6), ('beta', 10), ('gamma', 16),
                   ('delta', 17), ('epsilon.', 18)))
    alignment = align_speech(doc.native.job.baseline, view.playback.timing.stroke_ms, words, 40000, digest)
    view.receive('Alpha signed beta gamma delta epsilon.', [], alignment)
    assert view.playback.timing.position_ms(doc.native.original, 6) == 10000
    signed = doc.incoming.index('signed')
    assert view.playback.timing.position_ms(doc.native.incoming, signed) == 6000
    view.inline_editor.source_activated.emit('incoming', signed)
    assert view.playback.player.position() == 5000

    for accept in (True, False):
        view._start_review(0, accept)
        if view._review_worker is not None:
            assert view._review_worker.wait(5000)
            QApplication.processEvents()
        side = doc.native.original if accept else doc.native.incoming
        assert ('signed' in side.text) is accept
        if accept:
            assert view.playback.timing.position_ms(side, signed) == 6000
        view.undo_review()
        assert view.playback.timing.position_ms(doc.native.incoming, signed) == 6000

    project, session = tmp_path / 'speech.bababui', tmp_path / 'session.json'
    documents.save_document(doc, project)
    documents.save_session(session, [doc], doc.id)
    for restored in (documents.open_document(project), documents.load_session(session)[0][0], doc.duplicate()):
        restored_view = DocumentView(restored)
        assert restored_view.playback.timing.position_ms(restored.native.incoming, signed) == 6000
        restored_view.close()

    different_wav = tmp_path / 'different.wav'
    different_wav.write_bytes(Path(doc.wav_path).read_bytes() + b'trailer')
    doc.audio_override = doc.wav_path = str(different_wav)
    different_view = DocumentView(doc)
    assert doc.native.alignment is None
    assert different_view.playback.timing.position_ms(doc.native.original, 6) == 11940
    different_view.close()


def test_native_clock_removes_pauses_and_corrects_pcm_drift(tmp_path):
    times, revision = timing_source(tmp_path)
    assert times.position_ms(revision, 2) == 5940
    assert times.position_ms(revision, 8) == 11940
    assert times.elapsed_centiseconds(12000) is None
    assert times.elapsed_centiseconds(13200) == 1200
    assert times.duration_ms == 40000


def test_attached_second_recording_does_not_use_the_bundled_recording_clock(audio_view, tmp_path):
    from app.src.document_view import DocumentView

    doc = audio_view.document
    external = tmp_path / 'second-recorder.wav'
    with wave.open(str(external), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\x01\x00' * (16000 * 40))
    doc.audio_override = doc.wav_path = str(external)
    view = DocumentView(doc)
    try:
        assert view.playback is not None
        assert view.playback.timing is None
    finally:
        view.close()


@pytest.mark.parametrize('previous_alignment', [False, True], ids=['use-native-timing', 'keep-speech-timing'])
def test_untimed_rerun_keeps_working_playback_on_original(audio_view, previous_alignment):
    from hashlib import sha256
    from pathlib import Path
    from app.src.speech_alignment import NO_TIMESTAMPS, SpeechAlignment

    doc = audio_view.document
    if previous_alignment:
        digest = sha256(Path(doc.wav_path).read_bytes()).hexdigest()
        alignment = SpeechAlignment(digest, 40000, (4000, 10000, 16000),
                                    (('alpha', 4000), ('beta', 10000), ('gamma', 16000)))
        audio_view.receive(doc.original, [], alignment)

    audio_view.receive(doc.original, [NO_TIMESTAMPS])

    expected = 10000 if previous_alignment else 11940
    assert audio_view.playback.timing.position_ms(doc.native.original, doc.original.index('beta')) == expected
    source = 'saved speech timing' if previous_alignment else 'CaseCAT recording times'
    assert any(source in warning for warning in doc.warnings)


@pytest.mark.parametrize('resume_clock', [10997, 11000])
def test_overlapping_pause_and_resume_keep_transcript_in_sync(tmp_path, resume_clock):
    times, revision = timing_source(
        tmp_path, resume_clock=resume_clock, stop_elapsed=1000 + 16000 - resume_clock)
    assert times.position_ms(revision, 2) == 5940
    assert times.position_ms(revision, 8) == 11300
    assert times.elapsed_centiseconds(resume_clock - 1) == resume_clock - 1 - 10000
    assert times.elapsed_centiseconds(resume_clock) == 1000
    assert times.elapsed_centiseconds(resume_clock + 5) == 1005


def test_large_pause_overlap_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='Inconsistent recording events'):
        timing_source(tmp_path, resume_clock=10996, stop_elapsed=6004)


def test_replacement_and_insertions_use_the_exported_passage_anchor(tmp_path):
    times, revision = timing_source(tmp_path)
    edited = revision.replace(0, 10, 'Changed passage ')
    assert times.position_ms(edited, 3) == times.position_ms(revision, 8)
    assert times.position_ms(edited, len('Changed passage ')+2) == times.position_ms(revision, 13)
    assert times.position_ms(revision.replace(6, 6, 'new '), 7) == times.position_ms(revision, 8)
    assert times.position_ms(revision.replace(0, len(revision.text), ''), 0) is None


def test_highlight_ranges_follow_source_time_without_word_interpolation(tmp_path):
    times, revision = timing_source(tmp_path)
    assert times.range_at(revision, 6000) == (0, 6)
    assert times.range_at(revision, 12000) == (6, 11)
    assert times.range_at(revision, 100) is None
    edited = revision.replace(0, 1, 'Edited')
    assert times.range_at(edited, 6000) == (0, 11)


def test_missing_or_inconsistent_metadata_disables_timed_playback(tmp_path):
    from app.src.casecat.timing import recording_events
    with pytest.raises(ValueError, match='recording'):
        recording_events(b'<JobHistory/>')
    with pytest.raises(ValueError, match='recording'):
        recording_events(b'<Read-Settings><Read-Audio-Timestamp-0 sgpref-val="0"/></Read-Settings>')


def test_playback_controls_seek_without_changing_text_or_undo(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QTextEdit
    from app.src.playback import PlaybackBar
    app = QApplication.instance() or QApplication([])
    times, revision = timing_source(tmp_path)
    editor = QTextEdit()
    editor.setPlainText(revision.text)
    cursor = editor.textCursor()
    cursor.setPosition(8)
    editor.setTextCursor(cursor)
    bar = PlaybackBar(tmp_path/'sample.wav', times, lambda: (editor, revision))
    assert bar.cursor_position_ms() == 11940
    before = editor.document().availableUndoSteps()
    bar.show_position(12000)
    assert editor.toPlainText() == revision.text
    assert editor.textCursor().position() == 8
    assert editor.document().availableUndoSteps() == before
    assert editor.extraSelections()[0].cursor.selectedText() == 'beta '
    bar.stop()
    assert not editor.extraSelections()
    bar.close()


def test_audio_slider_keyboard_and_page_steps_seek_the_player(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QTextEdit
    from app.src.playback import PlaybackBar
    app = QApplication.instance() or QApplication([])
    times, revision = timing_source(tmp_path)
    editor = QTextEdit(revision.text)
    bar = PlaybackBar(tmp_path/'sample.wav', times, lambda: (editor, revision))
    for _ in range(100):
        app.processEvents()
        if bar.player.isSeekable():
            break
        QTest.qWait(10)
    assert bar.player.isSeekable()
    bar.player.setPosition(5000)
    QTest.keyClick(bar.slider, Qt.Key_Right)
    assert bar.player.position() == bar.slider.value() == 5001
    QTest.keyClick(bar.slider, Qt.Key_PageUp)
    assert bar.player.position() == bar.slider.value() > 5001
    bar.stop()
    bar.close()


@pytest.fixture
def audio_view(tmp_path, monkeypatch, request):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QUrl
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.src import documents
    from app.src.document_view import DocumentView
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path/'assets')
    view = DocumentView(documents.import_casecat(audio_archive(tmp_path, last=getattr(request, 'param', 'gamma.'))))
    view.resize(1050, 650)
    view.show()
    for _ in range(100):
        app.processEvents()
        if view.playback.player.isSeekable():
            break
        QTest.qWait(10)
    assert view.playback.player.isSeekable()
    yield view
    view.playback.player.setSource(QUrl())
    view.close()
    view.deleteLater()
    app.processEvents()


def set_playback_state(player, state):
    if state == 'playing':
        player.play()
    elif state == 'paused':
        player.play()
        player.pause()
    else:
        player.stop()
    return player.playbackState()


def test_replacing_notice_view_while_audio_is_loading_does_not_stop_the_decoder():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PySide6.QtMultimedia import QMediaPlayer
    from app.src.playback import PlaybackBar
    player = Mock()
    player.playbackState.return_value = QMediaPlayer.StoppedState
    player.position.return_value = 0
    bar = SimpleNamespace(player=player, clear_highlight=Mock(), _pending_seek=2200)
    PlaybackBar.stop(bar)
    player.stop.assert_not_called()
    assert bar._pending_seek is None
    bar.clear_highlight.assert_called_once()
    player.position.return_value = 2200
    PlaybackBar.stop(bar)
    player.stop.assert_called_once()


@pytest.mark.parametrize('decision', ['Accept', 'Reject'])
@pytest.mark.parametrize('state', ['paused', 'playing'])
@pytest.mark.parametrize('remaining', [True, False])
@pytest.mark.parametrize('side', ['original', 'incoming'])
def test_review_decisions_seek_without_changing_playback_state(audio_view, decision, state, remaining, side):
    from PySide6.QtCore import Qt
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton

    view = audio_view
    revision = view.document.native.original.revise('Alpha \nAn unchanged sentence.\nbeta \ngamma.')
    view.document.set_text('original', revision.text, revision=revision)
    view.document.set_text('incoming', revision.text, revision=revision)
    incoming = revision.text.replace('beta', 'copper')
    if remaining:
        incoming = incoming.replace('Alpha', 'Orange')
    view.receive(incoming, [])
    view.stack.setCurrentIndex(int(side == 'incoming'))
    view.activateWindow()
    QTest.qWait(1)
    assert len(view.diff_view.changes) == (2 if remaining else 1)
    button = next(button for button in view.diff_view.findChildren(QPushButton)
                  if button.text() == decision)
    player = view.playback.player
    before = set_playback_state(player, state)
    expected = QMediaPlayer.PausedState if state == 'playing' else QMediaPlayer.PlayingState
    player.setPosition(1000)
    button.setFocus()
    QTest.mouseClick(button, Qt.LeftButton)
    assert view.document.busy
    if remaining:
        assert abs(player.position() - 10940) < 100
        player.setPosition(15000)
    QTest.keyClick(QApplication.focusWidget() or view, Qt.Key_Space)
    assert player.playbackState() == expected
    QTest.keyClick(QApplication.focusWidget() or view, Qt.Key_Space)
    assert player.playbackState() == before
    for _ in range(100):
        if not view.document.busy:
            break
        QTest.qWait(10)
    assert not view.document.busy
    assert len(view.diff_view.changes) == int(remaining)
    assert player.playbackState() == before

    # Finishing the update must not rewind audio after the initial jump.
    assert abs(player.position() - (15000 if remaining else 10940)) < 100
    QTest.keyClick(QApplication.focusWidget() or view, Qt.Key_Space)
    assert player.playbackState() == expected
    QTest.keyClick(QApplication.focusWidget() or view, Qt.Key_Space)
    assert player.playbackState() == before


@pytest.mark.parametrize('side', ['original', 'incoming'])
def test_review_navigation_seeks_one_second_before_the_selected_edit(audio_view, side):
    from PySide6.QtWidgets import QPushButton

    view = audio_view
    revision = view.document.native.original.revise('Alpha \nAn unchanged sentence.\nbeta \ngamma.')
    view.document.set_text('original', revision.text, revision=revision)
    view.document.set_text('incoming', revision.text, revision=revision)
    view.receive(revision.text.replace('Alpha', 'Orange').replace('beta', 'copper'), [])
    view.stack.setCurrentIndex(int(side == 'incoming'))
    player = view.playback.player
    before = set_playback_state(player, 'paused')
    player.setPosition(1000)
    buttons = {button.text(): button for button in view.diff_view.findChildren(QPushButton)}
    buttons['Next'].click()
    assert view.diff_view.current == 1
    assert player.position() == 10940
    buttons['Previous'].click()
    assert view.diff_view.current == 0
    assert player.position() == 4940
    assert player.playbackState() == before


def test_space_types_in_editable_transcript(audio_view):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = audio_view
    view.activateWindow()
    view.original_page.setFocus()
    view.editor.setFocus()
    QTest.qWait(1)
    cursor = view.editor.textCursor()
    cursor.setPosition(2)
    view.editor.setTextCursor(cursor)
    QTest.keyClick(view.editor, Qt.Key_Space)
    assert view.document.original == 'Al pha beta gamma.'
    assert not view.playback.player.isPlaying()


@pytest.mark.parametrize('state', ['stopped', 'paused', 'playing'])
@pytest.mark.parametrize('side', ['original', 'incoming'])
def test_transcript_mouse_click_seeks_source_passage_without_changing_play_state(audio_view, state, side):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    view = audio_view
    if side == 'incoming':
        view.receive('Alpha new beta gamma.', [])
        view.stack.setCurrentIndex(1)
        QApplication.processEvents()
    editor = view.incoming_editor if side == 'incoming' else view.editor
    cursor = editor.textCursor()
    cursor.setPosition(editor.toPlainText().index('beta') + 2)
    point = editor.cursorRect(cursor).center()
    player = view.playback.player
    before = set_playback_state(player, state)
    player.setPosition(1000)
    revision = getattr(view.document.native, side)
    undo_steps = editor.document().availableUndoSteps()
    view.document.dirty = False
    QTest.mouseClick(editor.viewport(), Qt.LeftButton, pos=point)
    assert abs(player.position() - 10940) < 50
    assert player.playbackState() == before
    assert getattr(view.document.native, side) == revision
    assert not view.document.dirty
    assert editor.document().availableUndoSteps() == undo_steps


def test_typing_and_programmatic_cursor_moves_do_not_seek(audio_view):
    from PySide6.QtTest import QTest
    editor, player = audio_view.editor, audio_view.playback.player
    player.setPosition(2000)
    cursor = editor.textCursor()
    cursor.setPosition(8)
    editor.setTextCursor(cursor)
    QTest.keyClicks(editor, 'new')
    assert player.position() == 2000
    assert audio_view.document.original == 'Alpha benewta gamma.'


@pytest.mark.parametrize('state', ['stopped', 'paused', 'playing'])
def test_skip_buttons_seek_five_seconds_and_clamp_to_recording(audio_view, state):
    bar = audio_view.playback
    before = set_playback_state(bar.player, state)
    bar.player.setPosition(12000)
    bar.back_button.click()
    assert abs(bar.player.position() - 7000) < 50
    bar.forward_button.click()
    assert abs(bar.player.position() - 12000) < 50
    bar.player.setPosition(2000)
    bar.back_button.click()
    assert bar.player.position() < 50
    bar.player.setPosition(39000)
    bar.forward_button.click()
    assert bar.player.position() == 40000
    assert bar.player.playbackState() == before


@pytest.mark.parametrize('state', ['stopped', 'paused', 'playing'])
def test_progress_bar_click_seeks_early_and_drag_seeks_precisely(audio_view, state):
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtTest import QTest
    bar = audio_view.playback
    before = set_playback_state(bar.player, state)
    bar.player.setPosition(1000)
    mid = QPoint(bar.slider.width() // 2, bar.slider.height() // 2)
    QTest.mouseClick(bar.slider, Qt.LeftButton, pos=mid)
    assert abs(bar.player.position() - 19000) < 200
    QTest.mousePress(bar.slider, Qt.LeftButton, pos=mid)
    QTest.mouseMove(bar.slider, QPoint(bar.slider.width() - 1, mid.y()))
    QTest.mouseRelease(bar.slider, Qt.LeftButton, pos=QPoint(bar.slider.width() - 1, mid.y()))
    assert bar.player.position() == 40000
    near_start = QPoint(bar.slider.width() // 40, mid.y())
    QTest.mouseClick(bar.slider, Qt.LeftButton, pos=near_start)
    assert bar.player.position() < 50
    assert bar.player.playbackState() == before


@pytest.mark.parametrize('row_text, expected', [('Alpha', 4940), ('beta', 10940), ('beta changed', 10940)])
def test_review_clicks_seek_equal_original_and_incoming_passages(audio_view, row_text, expected):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPlainTextEdit
    view = audio_view
    revision = view.document.native.original.revise('Alpha \nbeta \ngamma.')
    view.document.set_text('original', revision.text, revision=revision)
    view.document.set_text('incoming', revision.text, revision=revision)
    view.refresh()
    view.receive('Alpha \nbeta changed \ngamma.', [])
    QApplication.processEvents()
    side = 'incoming' if 'changed' in row_text else 'original'
    text = getattr(view.document, side)
    view._seek_review_passage(side, text.index(row_text))
    assert view.playback.player.position() == expected


def receive_timed_proposal(view, proposal, times):
    from hashlib import sha256
    from pathlib import Path
    from app.src.audio_pipeline import Word
    from app.src.speech_alignment import align_speech

    doc = view.document
    words = tuple(Word(text, 'speaker', start, start + .1)
                  for text, start in zip(proposal.split(), times, strict=True))
    digest = sha256(Path(doc.wav_path).read_bytes()).hexdigest()
    alignment = align_speech(doc.native.original, view.playback.timing.stroke_ms, words, 40000, digest)
    assert alignment is not None
    view.receive(proposal, [], alignment)


@pytest.fixture
def timed_incoming_passage(audio_view):
    audio_view.editor.setPlainText('Alpha beta gamma delta epsilon.')
    receive_timed_proposal(audio_view, 'Alpha please bring the signed copy beta gamma delta epsilon.',
                           (2, 4, 5, 7, 9, 11, 12, 13, 14, 15))
    return audio_view


@pytest.mark.parametrize('surface', ['incoming', 'inline', 'preview'])
def test_click_inside_incoming_change_seeks_the_clicked_word(timed_incoming_passage, surface):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    view = timed_incoming_passage
    if surface == 'incoming':
        view.stack.setCurrentIndex(1)
    elif surface == 'preview':
        view.set_accept_all_preview(True)
        for _ in range(100):
            if view.active_view() is view.preview_editor:
                break
            QTest.qWait(10)
        assert view.active_view() is view.preview_editor
    QApplication.processEvents()
    editor = view.active_view()
    player = view.playback.player
    before = set_playback_state(player, 'paused')
    for word, expected in [('signed', 8000), ('bring', 4000), ('beta', 11000)]:
        position = view.document.incoming.index(word) + 2
        cursor = editor.textCursor()
        cursor.setPosition(editor.display_position('incoming', position) if surface == 'inline' else position)
        QTest.mouseClick(editor.viewport(), Qt.LeftButton, pos=editor.cursorRect(cursor).center())
        assert player.position() == expected
        assert player.playbackState() == before


def test_clicks_on_wrapped_incoming_rows_follow_a_pause_in_the_recording(audio_view):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    view = audio_view
    doc = view.document
    view.editor.setPlainText('Alpha beta agreed. Gamma delta epsilon.')
    first = 'Before the break we reviewed the signed inspection report and compared each entry with the original notes.'
    second = 'After lunch the clerk opened the blue binder and read the closing statement into the record.'
    proposal = f'Alpha beta agreed. {first} {second} Gamma delta epsilon.'
    times = [1, 2, 3, *(4 + i * .4 for i in range(len(first.split()))),
             *(24 + i * .5 for i in range(len(second.split()))), 37, 38, 39]
    receive_timed_proposal(view, proposal, times)
    QApplication.processEvents()
    editor = view.inline_editor
    rows = []
    for word, expected in [('Before', 3000), ('clerk', 24500)]:
        position = doc.incoming.index(word) + 2
        editor.scroll_to_source_position('incoming', position)
        cursor = editor.textCursor()
        cursor.setPosition(editor.display_position('incoming', position))
        rows.append(cursor.blockNumber())
        QTest.mouseClick(editor.viewport(), Qt.LeftButton, pos=editor.cursorRect(cursor).center())
        assert view.playback.player.position() == expected
    assert rows[1] > rows[0]


def test_activating_incoming_suggestion_seeks_its_first_spoken_word(timed_incoming_passage):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = timed_incoming_passage
    player = view.playback.player
    before = set_playback_state(player, 'paused')
    player.setPosition(20000)
    QTest.mouseClick(view.diff_view.cards[0].heading, Qt.LeftButton)
    assert player.position() == 3000
    assert player.playbackState() == before
    player.setPosition(20000)
    view.replay_current_edit()
    assert abs(player.position() - 3000) < 100
    assert player.isPlaying()


def test_clicking_a_changed_word_in_the_review_card_seeks_that_word(timed_incoming_passage):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QTextDocument
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel

    view = timed_incoming_passage
    view.resize(1600, 650)
    view.review_splitter.setSizes([700, 900])
    QApplication.processEvents()
    label = view.diff_view.cards[0].findChild(QLabel, 'comparison')
    text = QTextDocument()
    text.setDefaultFont(label.font())
    text.setDocumentMargin(0)
    text.setHtml(label.text())
    text.setTextWidth(label.contentsRect().width())
    cursor = text.find('signed')
    block = cursor.block()
    text.documentLayout().blockBoundingRect(block)
    line = block.layout().lineForTextPosition(cursor.selectionStart() - block.position())
    assert line.isValid()
    x = line.cursorToX(cursor.selectionStart() - block.position() + 2)[0]
    point = QPoint(label.contentsRect().left() + round(x), label.contentsRect().center().y())
    QTest.mouseClick(label, Qt.LeftButton, pos=point)
    assert view.playback.player.position() == 8000
    assert view.inline_editor.source_position() == ('incoming', view.document.incoming.index('signed'))


def test_accepting_last_incoming_passage_seeks_the_accepted_words(timed_incoming_passage):
    view = timed_incoming_passage
    view.review(0, True)
    assert view.document.original == view.document.incoming
    assert view.playback.player.position() == 3000


def test_navigating_to_a_replacement_follows_the_timed_incoming_side(timed_incoming_passage):
    view = timed_incoming_passage
    view.editor.setPlainText('First heading.\nAlpha beta gamma delta epsilon.')
    view.receive('Second heading.\nAlpha please bring the signed copy gamma delta epsilon.', [])
    panel = view.diff_view
    assert len(panel.changes) == 2
    panel.select(0)
    panel.navigate(1)
    assert view.playback.player.position() == 3000
    assert view.inline_editor.source_position()[0] == 'incoming'


def test_transcript_click_maps_utf16_offsets_to_native_anchors(audio_view):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    view = audio_view
    # Supplementary characters may be present while editing even though the
    # native writer rejects text outside the target's Windows-1252 encoding.
    view.receive('Alpha ' + '\U0001f600' * 8 + ' beta gamma.', [])
    view.stack.setCurrentIndex(1)
    QApplication.processEvents()
    editor = view.incoming_editor
    text = editor.toPlainText()
    cursor = editor.textCursor()
    cursor.setPosition(len(text[:text.index('beta') + 1].encode('utf-16-le')) // 2)
    QTest.mouseClick(editor.viewport(), Qt.LeftButton, pos=editor.cursorRect(cursor).center())
    assert view.playback.player.position() == 10940
