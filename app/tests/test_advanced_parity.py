"""Frozen upstream-V8 results verify the Python port without a JS runtime."""
import hashlib
import json
from pathlib import Path

import pytest

from app.src.advanced_diff import UPSTREAM_REVISION, _diff_lines, _normalized, text_edits


FIXTURES = Path(__file__).parent / 'fixtures'
REFERENCE = json.loads((FIXTURES / 'advanced-parity.json').read_text(encoding='utf-8'))


def sources(case):
    return tuple(case[side] if side in case else
                 (FIXTURES / case[side + '_file']).read_text(encoding='utf-8')
                 for side in ('original', 'incoming'))


def test_reference_is_pinned_to_the_ported_upstream_version():
    assert REFERENCE['upstream_commit'] == UPSTREAM_REVISION
    assert REFERENCE['options'] == {'ignoreTrimWhitespace': False, 'maxComputationTimeMs': 0,
                                    'computeMoves': False, 'extendToSubwords': False}


@pytest.mark.parametrize('case', REFERENCE['cases'], ids=lambda case: case['name'])
def test_python_port_matches_frozen_upstream_inner_changes_and_exact_offsets(case):
    original, incoming = sources(case)
    assert hashlib.sha256(original.encode('utf-8')).hexdigest() == case['original_sha256']
    assert hashlib.sha256(incoming.encode('utf-8')).hexdigest() == case['incoming_sha256']
    old, _ = _normalized(original)
    new, _ = _normalized(incoming)
    assert _diff_lines(tuple(old.split('\n')), tuple(new.split('\n'))) == tuple(
        tuple(span) for span in case['inner_changes'])
    edits = text_edits(original, incoming)
    assert edits == [tuple(span) for span in case['edits']]
    accepted = original
    rejected = incoming
    for a, b, c, d in reversed(edits):
        accepted = accepted[:a] + incoming[c:d] + accepted[b:]
        rejected = rejected[:c] + original[a:b] + rejected[d:]
    assert accepted == incoming
    assert rejected == original
