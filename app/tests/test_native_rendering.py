import re
from pathlib import Path
import struct

import pytest

from app.src.casecat.archive import inspect_archive
from app.src.casecat.codec import load_job
from app.tests.test_native_casecat import job_files, zip_bytes


def native_stream(payload):
    files = job_files(words=('',))
    native = bytearray(files['jobs/example.sgngl'])
    native += payload
    struct.pack_into('<I', native, 536, len(native) - 1024)
    files['jobs/example.sgngl'] = bytes(native)
    bundle = inspect_archive(zip_bytes(files))
    return load_job(bundle, bundle.jobs[0])


def test_sentence_capitalization_preserves_internal_case_and_original_bytes():
    payload = b'\x16\x02\x00good morning.  my name is Ana.\x16\x03\x00yes, on may 21.'
    job = native_stream(payload)
    assert job.text == '     Q    Good morning.  My name is Ana.\n     A    Yes, on may 21.'
    assert job.native_bytes.endswith(payload)


def test_conflict_alternatives_keep_their_visible_separators():
    job = native_stream(b'he said \x02he also\x02else\x03 today.')
    assert job.text == 'He said ^ he also ^ else today.'


def test_explicit_case_controls_override_automatic_capitalization():
    job = native_stream(b'\x16\x02\x00\x12\x8egood. \x12\x8eanother. \x12\x0eagain.')
    assert job.text == '     Q    good. another. Again.'


def test_public_reference_matches_all_words_in_native_import():
    # Private validation runs locally. Synthetic tests above remain portable.
    source = Path('C:/Users/caray/Downloads/261109walth.zip')
    reference = Path('C:/Users/caray/Downloads/261109walthxd/261109walth.txt')
    if not source.exists() or not reference.exists():
        pytest.skip('Private native job and reporter export are not distributed.')
    bundle = inspect_archive(source)
    job = load_job(bundle, bundle.jobs[0])
    printed = reference.read_text(encoding='utf-8-sig')
    lines = [match[1] for line in printed.splitlines()
             if (match := re.match(r'^\s{8,}\d{1,2} {4}(.*)', line))]
    assert job.text.split() == ' '.join(lines).split()
