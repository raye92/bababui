# Transcript evaluation

A separate local browser app for comparing prompt versions against reviewed
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
2. **Prompt versions:** copy a saved version, edit instructions and rules, preview
   the combined system prompt, and save a new immutable version.
3. **Runs and comparisons:** choose a dataset revision, split, and prompt versions.
   Review the API-call count, then start. Calls run sequentially at temperature zero.
4. Inspect input/expected/generated text and whitespace-visible diffs. Compare
   complete runs on matching data, or export CSV summaries and full JSON records.

### JSONL import

One object per line, with `id`, `input`, and `output` strings:

```json
{"id":"excerpt-01","input":"     A    yes","output":"     A    Yes.","split":"development"}
```

Use JSON escapes for newlines and tabs. `split` is optional and defaults to
`development`; the other allowed value is `holdout`. IDs must be unique within
the dataset. Text is UTF-8, must contain non-whitespace characters, and cannot
contain control characters other than tab, CR, and LF. Spaces and line endings
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

CRLF and CR are normalized to LF for scoring. All other characters count,
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
case IDs, and scoring version. Model settings are visible in saved metadata;
keep them fixed when attributing a change to a prompt. Development is selected by
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
