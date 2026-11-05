# Transcript evaluation

A separate local browser app for comparing evaluation setups against reviewed
rough/expected transcript pairs. The transcript editor remains in `../app`.

## Start

From the repository root, on Windows:

```powershell
python -m venv evaluation/.venv
evaluation/.venv/Scripts/python.exe -m pip install -r evaluation/requirements.txt
Copy-Item evaluation/.env.example evaluation/.env
# Edit evaluation/.env and add your DeepSeek API key.
evaluation/.venv/Scripts/python.exe -m streamlit run evaluation/main.py
```

With dependencies installed in your active Python environment, the launch command
is `python -m streamlit run evaluation/main.py`. Open http://127.0.0.1:8501.
The repository and evaluation `.streamlit/config.toml` files bind the server to
localhost and disable usage telemetry. If launching from a different working
directory, add `--server.address 127.0.0.1 --browser.gatherUsageStats false`.

The app starts with no datasets or runs. On first launch it copies the editor's
two prompt documents into a saved **Editor baseline** version. It does not import
editor code, read its `.env`, or change its prompts or transcripts. API settings
come from `evaluation/.env`; explicitly set environment variables take precedence.
An API key is only needed to run evaluations, not to manage data or view results.

## Workflow

1. **Datasets:** import reviewed pairs or add them manually. Each pair is a
   self-contained excerpt. Use **Update** to save edits to the selected dataset. Use **Save as new dataset** at the bottom to create a separate copy, including the current edits. Existing run snapshots remain unchanged.
2. In **Evaluation Setup**, copy a saved setup, choose a model and filters, and
   edit the instructions and court-reporting rules. Save the result under a new name.
   New setups default to DeepSeek V4 Pro. DeepSeek Flash is also available.
3. In **Results**, choose a dataset revision, split, and one or more setups.
   Review the API-call count, then start. Calls run sequentially at temperature zero.
4. Inspect the original input, filtered model input, raw reply, and graded diff.
   Download the numbered transcript, CSV summaries, or a full run as JSON.

**Strip formatting** starts on. It removes transcript numbering and page formatting
from the input before the model sees it. The same formatter strips the reply,
reviewed output, and original input baseline for scoring. With the toggle off,
numbering and spacing count in the score. Display and export apply standard
numbering after grading in both modes.

The `/#*…` input filter starts on and removes tokens such as `/#*abc`. The broader
`/…` filter starts off. When on, it removes a slash and everything after it up
to the next whitespace, including `/#*abc`. Neither filter changes the reviewed
output or the baseline. Older prompt files use the new defaults for new runs.
Existing runs keep their recorded scores and use their original settings on retry.

### JSONL import

One object per line, with `id`, `input`, and `output` strings:

```json
{"id":"excerpt-01","input":"     A    yes","output":"     A    Yes.","split":"development"}
```

Use JSON escapes for newlines and tabs. `split` is optional and defaults to
`development`; the other allowed value is `holdout`. IDs must be unique within
the dataset. Text is UTF-8, must contain non-whitespace characters, and cannot
contain control characters other than tab, CR, LF, and form feed in transcripts. Spaces and line endings
are retained in stored snapshots. UTF-8 file BOMs are accepted.

### Text-file import

Upload both `<id>.input.txt` and `<id>.output.txt` for every excerpt. Every file
must have a matching partner. Imported text pairs default to development; change
the split using the pair editor and click Update.

`fixtures/` contains synthetic examples and import templates. They are not loaded
automatically and are not reviewed benchmark data. The legacy `example1.json`
and `example1.jsonl` files are preserved for reference; they are not in this app's
dataset format. Convert verified source material to the documented format before
importing it.

## Scoring

Primary **character similarity** is:

```text
100 × (1 − Levenshtein distance / max(generated length, expected length))
```

CRLF and CR are normalized to LF for scoring. After any selected formatting
removal, all other characters count,
including indentation, trailing newlines, capitalization, and punctuation.
Two empty strings score 100; one empty string scores zero. Empty imported excerpts
and empty API responses are rejected rather than treated as successful cases.

- **Baseline:** the same similarity formula applied to unchanged rough input.
- **Improvement:** generated similarity minus baseline, in percentage points.
- **Exact-match rate:** percentage of cases matching after line-ending normalization.
- **Normalized similarity:** secondary diagnostic that collapses whitespace and
  strips surrounding whitespace. It still counts punctuation and capitalization.

Run metrics are equal-weight averages across cases, not weighted by excerpt
length. No aggregate score is assigned until all cases succeed. A high similarity
score does not establish correctness; inspect the baseline and actual differences.
These metrics do not claim to classify individual edits as correct or incorrect.

Comparisons require identical full dataset content snapshots, ordered selected
case IDs, scoring version, and grading mode. Results show the model and marker
filters alongside each run's scores. Development is selected by
default. Holdout evaluation requires explicit selection and should be reserved
for a final check after tuning. Temperature zero reduces variation but does not
guarantee deterministic model responses.

## Persistence and retries

`data/` holds datasets, prompt versions, and runs as UTF-8 JSON with generated
internal IDs. Writes use an atomic replacement. Run records contain dataset and
prompt snapshots, SHA-256 hashes, scoring version, settings, responses, timing,
and attempt history. Credentials are never included. Back up this folder to
preserve your work. It and `.env` are excluded from Git.

Each case is marked running before the request and saved immediately afterward.
Failures remain visible. **Retry or resume** skips successful cases and uses the
run's saved model settings with the current API key. An OS lock prevents the same
run from executing concurrently in two sessions. Page loads and rerenders do not
start requests. Clicking **Start evaluation** explicitly creates new runs.

After a process crash, in-flight requests may have reached the provider even if
their responses were not saved. Explicit retry can make another paid request.
No automatic retry is performed. Truncated and empty responses count as failures.

For isolated tests or a separate local storage folder, set `EVALUATION_DATA_DIR`.
Do not put sensitive data in a Git-tracked location. CSV exports prefix text
starting with spreadsheet formula characters with an apostrophe for safe opening.

## Verification

```powershell
evaluation/.venv/Scripts/python.exe -m pytest evaluation/tests -q
```

Tests cover scoring, validation, snapshots, retries, imports, exports, API payloads,
and Streamlit screens. Network calls use fake transports; tests do not consume API
credits. No reviewed transcript data or API key is required.
