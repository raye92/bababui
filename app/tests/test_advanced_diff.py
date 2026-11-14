from app.src.advanced_diff import text_edits, paragraph_ops


def apply_edits(old, new, edits):
    for a, b, c, d in reversed(edits):
        old = old[:a] + new[c:d] + old[b:]
    return old


def test_advanced_inner_changes_separate_join_wording_and_speaker():
    from app.tests.test_advanced_review_migration import BEFORE, AFTER
    edits = text_edits(BEFORE, AFTER)
    pairs = [(BEFORE[i:j], AFTER[k:l]) for i, j, k, l in edits]
    assert pairs == [('\n', ''), ('could', 'can'), ('? ', '.'), ('MS. RIVERA', 'THE WITNESS')]
    assert not any('Yes.' in before + after for before, after in pairs)
    assert apply_edits(BEFORE, AFTER, edits) == AFTER
    assert apply_edits(AFTER, BEFORE, [(c, d, a, b) for a,b,c,d in edits]) == BEFORE


def test_paragraph_correspondence_uses_inner_matches_not_broad_hunk():
    old = ['Q First question?', 'A Yes.', 'Q Second question?', 'A No.']
    new = ['Q Changed first question?', 'A Yes.', 'Q Changed second question?', 'A No.']
    assert paragraph_ops(old, new) == [
        ('replace', 0, 1, 0, 1), ('equal', 1, 2, 1, 2),
        ('replace', 2, 3, 2, 3), ('equal', 3, 4, 3, 4)]


def test_added_turn_does_not_join_an_existing_question():
    assert paragraph_ops(['Q Did you drive?', 'Q Did you stop?'],
                         ['Q Did you drive there?', 'Q Were you alone?', 'Q Did you stop here?']) == [
        ('replace', 0, 1, 0, 1), ('insert', 1, 1, 1, 2), ('replace', 1, 2, 2, 3)]


def test_first_diff_can_start_concurrently_in_background_threads():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c', '''
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from app.src.advanced_diff import text_edits
barrier = Barrier(4)
def run(index):
    barrier.wait()
    old, new = f'Question {index}. Old answer.', f'Question {index}. New answer.'
    changes = text_edits(old, new)
    assert [(old[a:b], new[c:d]) for a,b,c,d in changes] == [('Old', 'New')]
with ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(run, range(4)))
'''], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_diff_runs_with_standard_library_only_and_no_javascript_or_subprocess():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-S', '-c', r"""
import sys

def forbid_runtime(event, args):
    if event in ('subprocess.Popen', 'os.system', 'ctypes.dlopen'):
        raise AssertionError('External runtime activity: ' + event)
    if event == 'open' and isinstance(args[0], str) and args[0].lower().endswith(('.js', '.mjs')):
        raise AssertionError('JavaScript source loaded: ' + args[0])
sys.addaudithook(forbid_runtime)
from app.src.advanced_diff import text_edits, paragraph_ops
old = 'First.\nSecond could change.\nMS. RIVERA: Yes.'
new = 'First. Second can change.\nTHE WITNESS: Yes.'
edits = text_edits(old, new)
assert [(old[a:b], new[c:d]) for a,b,c,d in edits] == [
    ('\n', ' '), ('could', 'can'), ('MS. RIVERA', 'THE WITNESS')]
assert paragraph_ops(['Same.', 'Old.'], ['Same.', 'New.']) == [
    ('equal', 0, 1, 0, 1), ('replace', 1, 2, 1, 2)]
assert not any(name.split('.')[0] in ('py_mini_racer', 'quickjs', 'PySide6') for name in sys.modules)
"""], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
