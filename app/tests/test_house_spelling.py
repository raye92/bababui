"""House spelling from the bundled Spelling and Terminology.csv."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.src import house_spelling
from app.src.house_spelling import APPLY, KEEP, FILENAME, PROMPT as HOUSE_PROMPT, load, parse, reference_path
from app.tests.test_native_editor import native_window, source_zip  # noqa: F401 (fixture)
from app.tests.test_suggestions import revision

ROOT = Path(__file__).resolve().parents[2]
SENTENCES = ['I reviewed the xrays.', 'I performed a re-evaluation.', 'I scheduled a follow up visit.',
             'I asked him to follow up.', 'I reviewed the X-rays.']
HOUSE = ['I reviewed the X-rays.', 'I performed a reevaluation.', 'I scheduled a follow-up visit.',
         'I asked him to follow up.', 'I reviewed the X-rays.']
HEADER = '"Category","Candidate forms or comparison","House form","Application","Example or contrast","Scope","Reference entry"\n'


def by_meaning(items):
    """A stand-in for the review model: the follow-up noun form fits only before a noun."""
    return [APPLY if '⟦follow up⟧ visit' in item['sentence'] else KEEP for item in items]


def applied(text, decide=by_meaning):
    return load().apply(text, decide)


def test_the_csv_is_bundled_with_the_app_and_is_the_only_word_list():
    path = reference_path()
    assert path == ROOT / 'app' / 'assets' / FILENAME and path.is_file()
    reference = load()
    assert len(reference) == 476
    entries = {e.house: e for e in reference.entries}
    assert entries['X-ray'].application == house_spelling.WHOLE
    assert entries['X-ray'].candidates == ('xray', 'x ray', 'x-ray')
    assert entries['follow-up'].application == house_spelling.CONTEXT
    # The cleaned rows: the competing form is a candidate; no instruction is.
    assert entries['nonunion'].candidates == ('non-union', 'non union') and entries['nonunion'].notes == ()
    assert entries['outpatient'].candidates == ('out patient', 'out-patient')
    assert 'preserve labor terminology as spoken' in entries['nonunion'].example


def test_notes_and_examples_are_never_replacement_candidates():
    rows = parse(HEADER + '"Context","nonunion | preserve labor terminology as spoken","nonunion","Context",'
                 '"fracture nonunion / union work","Select by meaning.",""\n'
                 '"Context","backup | back up the file","backup","Context","a backup copy / back up the file","",""\n'
                 '"Legal","adjudification","adjudication","Context","The application for adjudication was filed.","",""\n')
    nonunion, backup, adjudication = rows
    assert nonunion.candidates == () and nonunion.notes == ('preserve labor terminology as spoken',)
    # From a contrast phrase only the words that spell the house form are a candidate.
    assert backup.candidates == ('back up',)
    assert adjudication.candidates == ('adjudification',)
    text = 'Speaker 1: Please preserve labor terminology as spoken. The application for adjudication was filed.'
    result = house_spelling.Reference(rows).apply(text, lambda items: [APPLY] * len(items))
    assert result.text == text and result.changes == []


@pytest.mark.parametrize('before, after', list(zip(SENTENCES, HOUSE)))
def test_the_five_examples(before, after):
    result = applied(f'Speaker 2: {before}')
    assert result.text == f'Speaker 2: {after}'
    assert [(c.before, c.after) for c in result.changes] == (
        [] if before == after else [(b, a) for b, a in [('xrays', 'X-rays'), ('re-evaluation', 'reevaluation'),
                                                         ('follow up', 'follow-up')] if b in before])


def test_endings_capitals_quotes_names_and_spellings_on_the_record_are_kept():
    text = ('Speaker 1: Re-evaluation was done. The osteo-phytes were re-opened. AN X-RAY HEADING: XRAYS.\n'
            'Speaker 2: He wrote "re-evaluation" in quotes. She runs the Post-Operative Care Unit.\n'
            'Speaker 1: The affadavit is spelled A-F-F-A-D-A-V-I-T on the record.')
    result = applied(text, lambda items: [APPLY] * len(items))
    assert result.text == (
        'Speaker 1: Reevaluation was done. The osteophytes were reopened. AN X-RAY HEADING: X-RAYS.\n'
        'Speaker 2: He wrote "re-evaluation" in quotes. She runs the Post-Operative Care Unit.\n'
        'Speaker 1: The affadavit is spelled A-F-F-A-D-A-V-I-T on the record.')
    assert [c.after for c in result.changes] == ['Reevaluation', 'osteophytes', 'reopened', 'X-RAYS']


def test_context_entries_ask_the_model_and_keep_the_words_when_it_cannot_decide():
    asked = []

    def complete(payload, prompt):
        asked.append((json.loads(payload), prompt))
        return json.dumps({'decisions': {'1': 'apply', '2': 'keep'}})
    text = 'Speaker 2: I scheduled a follow up visit. I asked him to follow up.'
    result = load().apply(text, house_spelling.model_decisions(complete))
    assert result.text == 'Speaker 2: I scheduled a follow-up visit. I asked him to follow up.'
    (sent, prompt), = asked
    assert prompt == HOUSE_PROMPT
    assert [(i['sentence'], i['house_form']) for i in sent['items']] == [
        ('I scheduled a ⟦follow up⟧ visit.', 'follow-up'), ('I asked him to ⟦follow up⟧.', 'follow-up')]
    assert sent['items'][0]['example'] == 'a follow-up visit / please follow up'
    for broken in ('not json', json.dumps({'decisions': ['maybe']})):
        kept = load().apply(text, house_spelling.model_decisions(lambda payload, prompt: broken))
        assert kept.text == text


def test_a_row_added_to_the_csv_is_used_on_the_next_run(tmp_path):
    path = tmp_path / FILENAME
    path.write_text(HEADER + '"Closed","re-check","recheck","Whole-word spelling","","",""\n', encoding='utf-8')
    assert load(path).apply('Speaker 1: A re-check of the x-ray.').text == 'Speaker 1: A recheck of the x-ray.'
    path.write_text(path.read_text(encoding='utf-8')
                    + '"House","x-ray","X-ray","Whole-word spelling","","",""\n', encoding='utf-8')
    assert load(path).apply('Speaker 1: A re-check of the x-ray.').text == 'Speaker 1: A recheck of the X-ray.'


def run_worker(tmp_path, rough, *, review=None):
    """The normal AI-draft flow with stand-in models: speaker labels, house spelling,
    formatting, spelling review and the AI wording review."""
    from app.src.audio_pipeline import Transcription
    from app.src.ai_review import PROMPT as REVIEW_PROMPT
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    from shared.spelling_review import PROMPT as SPELLING_PROMPT
    wav = tmp_path / 'job.wav'
    wav.write_bytes(b'recording')
    gemini = '\n'.join(f'Speaker 2: {sentence}' for sentence in SENTENCES)

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            return Transcription(gemini, (), (), 9000, sha256(path.read_bytes()).hexdigest())

    calls = []

    class Processor:
        def __init__(self, config, model):
            self.model = model

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            calls.append((self.model, prompt, text))
            if prompt == HOUSE_PROMPT:
                return json.dumps({'decisions': dict(zip(
                    (item['id'] for item in json.loads(text)['items']),
                    by_meaning(json.loads(text)['items'])))})
            if prompt == SPELLING_PROMPT:
                return '{"words": []}'
            if prompt == REVIEW_PROMPT:
                # Reject every edit it is shown: house edits must never be among them.
                return json.dumps({item['id']: 'reject' for item in json.loads(text)})
            return '\n'.join('     A    ' + line.split(': ', 1)[1] for line in text.split('\n'))

    request = Request('doc', str(wav), 'formatter', 'transcribe', 'rules', {}, original=revision(rough),
                      review_model=review)
    worker = ProcessingWorker(request, TranscriptionCoordinator(), Pipeline, Processor)
    done, failed = [], []
    worker.reviewed.connect(lambda *args: done.append(args[1]))
    worker.succeeded.connect(lambda *args: done.append(args[1]))
    worker.failed.connect(lambda *args: failed.append(args))
    worker.run()
    assert not failed
    return done[0], calls


ROUGH = '\n'.join(f'     A    {sentence}' for sentence in SENTENCES)
DRAFT = '\n'.join(f'     A    {sentence}' for sentence in HOUSE)


def test_the_examples_through_the_normal_processing_flow(tmp_path):
    from app.src.ai_review import PROMPT as REVIEW_PROMPT
    from app.src.suggestions import preview_ranges, suggestions
    result, calls = run_worker(tmp_path, ROUGH, review='reviewer')
    prompts = [prompt for _, prompt, _ in calls]
    # House spellings come before formatting; the formatter receives them.
    assert prompts.index(HOUSE_PROMPT) < prompts.index('rules')
    formatter_input = next(text for _, prompt, text in calls if prompt == 'rules')
    assert formatter_input == '\n'.join(f'Speaker 2: {sentence}' for sentence in HOUSE)
    # Only the two follow up places went to the model; the whole-word rows needed no call.
    house = json.loads(next(text for _, prompt, text in calls if prompt == HOUSE_PROMPT))
    assert [item['words'] for item in house['items']] == ['follow up', 'follow up']
    original, incoming, _ = result.after_ai
    assert original.text == ROUGH and incoming.text == DRAFT
    # The AI wording review never saw a house edit, so its rejections changed nothing.
    assert REVIEW_PROMPT not in prompts
    changed = [(original.text[a:b], incoming.text[c:d])
               for change in suggestions(original, incoming) for a, b, c, d in preview_ranges(change)]
    assert changed == [('xrays', 'X-rays'), ('re-evaluation', 'reevaluation'), ('follow up', 'follow-up')]
    assert result.summary.startswith('House spelling: 3 terms changed. ')


def test_without_ai_review_whole_word_and_context_spellings_still_apply(tmp_path):
    draft, calls = run_worker(tmp_path, ROUGH)
    assert draft == DRAFT
    assert {model for model, prompt, _ in calls if prompt == HOUSE_PROMPT} == {'formatter'}


def green(editor):
    """Green additions in Incoming; the selected suggestion is a deeper green."""
    # Pages show a hyphen as a non-breaking hyphen.
    return [m.cursor.selectedText().replace('\u2011', '-') for m in editor.extraSelections()
            if m.format.background().color().name() in ('#ccffd8', '#7ee2a8')]


def test_the_editor_highlights_only_the_changed_terms_in_green(native_window, tmp_path):
    native_window.import_zip(0, source_zip(tmp_path, audio=False))
    view = native_window.current
    state = view.document.native
    rough = ROUGH + '\n     A    He has Carpal Tunnel Syndrome.'
    state.original = state.incoming = state.original.revise(rough)
    view.refresh()
    view.receive(DRAFT + '\n     A    He has carpal tunnel syndrome.', [])
    # The capitalization change is case-only, which the automatic rules would accept
    # silently. As a house spelling it stays pending and green.
    assert green(view.incoming_editor) == ['X-rays', 'reevaluation', 'follow-up', 'carpal', 'tunnel', 'syndrome']
    assert state.original.text == rough
    assert len(view.diff_view.changes) == 6


def test_house_forms_are_settled_for_the_spelling_review():
    from shared.spelling_review import review_spelling
    text = 'Speaker 1: I reviewed the X-rays and the arthrogram.'
    flagged = [{'word': 'X-rays', 'context': 'X-rays', 'category': 'term', 'alternatives': ['x-rays']},
               {'word': 'arthrogram', 'context': 'arthrogram', 'category': 'term', 'alternatives': ['arthrogramme']}]
    sources = [('house', form) for form in load().forms()]
    result = review_spelling(text, text, lambda payload, prompt: json.dumps({'words': flagged}), sources=sources)
    assert result.terms == ()


def install(tmp_path):
    """A copy of the app as it would be packaged: its code and assets, nothing else."""
    target = tmp_path / 'Bababui packaged'
    shutil.copytree(ROOT / 'app' / 'src', target / 'app' / 'src', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT / 'app' / 'assets', target / 'app' / 'assets')
    shutil.copytree(ROOT / 'shared', target / 'shared', ignore=shutil.ignore_patterns('__pycache__'))
    return target


def test_the_packaged_app_finds_the_csv_from_another_working_directory(tmp_path):
    target = install(tmp_path)
    elsewhere = tmp_path / 'somewhere else'
    elsewhere.mkdir()
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    run = subprocess.run([sys.executable, str(target / 'app' / 'src' / 'house_spelling.py'), '--check'],
                         cwd=elsewhere, env=env, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    path, count = run.stdout.strip().split('\n')
    assert Path(path) == target / 'app' / 'assets' / FILENAME
    assert count.startswith('476 entries')


def test_a_frozen_build_finds_the_csv_in_its_bundle(tmp_path, monkeypatch):
    target = install(tmp_path)
    monkeypatch.setattr(house_spelling, '__file__', str(tmp_path / 'not here' / 'app' / 'src' / 'house_spelling.py'))
    monkeypatch.setattr(sys, '_MEIPASS', str(target), raising=False)
    assert reference_path() == target / 'app' / 'assets' / FILENAME
    assert len(load()) == 476


def test_an_unreadable_reference_skips_house_spelling_with_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(house_spelling, 'reference_path', lambda: tmp_path / 'missing.csv')
    result, _ = run_worker(tmp_path, ROUGH, review='reviewer')
    # The formatter got Gemini's words unchanged, so the draft matches the rough.
    assert result.after_ai[1].text == ROUGH
    assert not result.summary.startswith('House spelling')
