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

On first launch, create an evaluation setup with your own instructions and rules.
Existing saved setups remain unchanged. The apps share transcript formatting
code and use separate configuration and data.
Text evaluations require `DEEPSEEK_API_KEY` in `evaluation/.env` or in the
environment. Environment variables take precedence. You can manage data and
view results without a key.

## Workflow

1. **Datasets:** import original/scoped/WAV groups from uploads or a local folder,
   or add cases manually with a matching WAV. Each pair is a
   self-contained excerpt. Use **Update** to save edits to the selected dataset. Use **Save as new dataset** at the bottom to create a separate copy, including the current edits. Existing run snapshots remain unchanged.
2. In **Evaluation Setup**, copy a saved setup, choose a model and filters, and
   edit the instructions and court-reporting rules. Save the result under a new name.
   New setups default to DeepSeek V4 Pro. DeepSeek Flash is also available.
3. In **Results**, choose a dataset revision, split, and one or more setups.
   Review the separate transcription and editing-call counts, then start.
   Editing calls run sequentially at temperature zero.
4. Inspect the original input, filtered model input, raw reply, and graded diff.
   Download the numbered transcript, CSV summaries, or a full run as JSON.

The **Google AI Studio transcription model** dropdown offers
`gemini-3.5-transcribe` and `gemini-3.8-flash`. The choice is saved with each setup.
Set `GEMINI_API_KEY` in `evaluation/.env` for new transcriptions. Fully cached
evaluations do not require a Gemini key.

Use the folder buttons next to the dataset, setup, and run selectors to open
their storage folders on the machine running Streamlit.

**Strip formatting** starts on. It removes transcript numbering and page formatting
and joins recognized 56-character continuations into logical paragraphs before
the model sees the input. It preserves speaker turns, topic paragraphs, headings,
procedural notations, and ambiguous line breaks. Joined wrap boundaries become a
single space. The same formatter strips the reply,
reviewed output, and original input baseline for scoring. With the toggle off,
numbering and spacing count in the score. Display and export apply standard
56-character wrapping and numbered, 25-line pages after grading in both modes.
The width includes indentation and labels, excluding the number gutter. Continuation
lines start flush left; words and hyphenated terms are never split. A single longer
token may exceed the width. Existing saved datasets and run history are unchanged.

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

Upload one JSONL file with a matching `<id>.wav` for every case.
Use JSON escapes for newlines and tabs. `split` is optional and defaults to
`development`; the other allowed value is `holdout`. IDs must be unique within
the dataset. Text is UTF-8, must contain non-whitespace characters, and cannot
contain control characters other than tab, CR, LF, and form feed in transcripts. Spaces and line endings
are retained in stored snapshots. UTF-8 file BOMs are accepted.

### Text-file import

Each case requires three files:

```text
260901desai.txt
260901desai_Scoped.txt
260901desai.wav
```

The separator before `scoped` must be exactly one underscore, hyphen, period,
or space. Filenames match case-insensitively. Missing partners, duplicate or
ambiguous filenames, invalid text, and unreadable WAVs reject the entire import.
Folder imports scan immediate files only and ignore unrelated file types.
Every import and manual case requires audio. Imported text groups default to
development; change the split in the pair editor when needed.

WAVs are validated with FFprobe and decoded with FFmpeg, hashed once on import,
and copied to `data/audio/<sha256>.wav`. Original source files can then move.
Managed WAVs are immutable; do not edit them directly. Identical audio reuses
the same copy. New evaluation checks only that the managed file exists.

### Audio dependencies

Install FFmpeg and FFprobe and make them available on PATH. On Windows:

```powershell
winget install --id Gyan.FFmpeg --exact
```

Restart the terminal and Streamlit after installing. Alternatively, set
`FFMPEG_PATH` and `FFPROBE_PATH` environment variables to the executable paths.
The Python requirements include Google's SDK. Uploads accept up to 2 GB per
file; use local-folder import for larger WAVs.

### Audio transcription and reuse

Transcriptions live in `data/transcriptions/<model>/<audio-sha256>/`. Settings
are fixed: verbatim text without speaker labels or timestamps. Original and
reviewed text are never sent to the transcription model. Changing editing
instructions or reimporting the same WAV does not cause retranscription.

Segments last at most 30 minutes. The splitter chooses the last silence of at
least 0.5 seconds below -35 dB in the 29:30 to 30:00 window. Without suitable
silence, adjacent segments overlap by three seconds. Assembly removes only
matching normalized suffix/prefix sequences of 3 to 30 words with more than
one distinct word. Repeated single-word sequences and other uncertain joins
retain both texts and are flagged in the result inspector.

Successful segments are saved immediately. Explicit retry reuses them. OS-level
locks prevent duplicate concurrent transcription and release when a process
ends. Uploaded segments are deleted in `finally`, including failed requests.
Pending remote IDs survive interruption for cleanup on a later explicit
transcription action with credentials. Hard termination can prevent immediate
cleanup; cached evaluation never requires remote access.

The start summary counts recordings needing transcription, missing segment
requests across audio models, reusable completed transcriptions, and editing
prompt calls. A shared audio/model combination is transcribed once across
setups. Gemini credentials and FFmpeg are required only for new transcription
work. DeepSeek credentials are required for editing calls.

Editing requests send instructions and court-reporting rules as the system
message. The user message contains the labeled AI transcription reference first,
then the labeled original transcript to revise. Both transcripts are data, not
instructions. The original supplies the structure; the AI transcription is an
imperfect audio reference to help revisions. Filters apply only to original
text. Reviewed output is used only for scoring.

Saved request snapshots remain unchanged. Retrying an existing request sends its
saved messages, including the previous section order. Newly built requests use
the reference-first order.

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

- **Baseline:** similarity between the rough input and reviewed output using the
  same grading mode as the model output. The slash-marker filters apply only
  to the input sent to the model.
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
prompt snapshots, immutable transcription/request references, SHA-256 hashes,
scoring version, settings, responses, timing,
and attempt history. Credentials are never included. Back up this folder to
preserve your work, including `audio/`, `transcriptions/`, and `requests/`.
Exact submitted messages are stored once by content hash in `requests/`; run
records reference them instead of repeating long transcripts. Missing or altered
referenced artifacts block retry rather than silently regenerating content.
The data folder and `.env` are excluded from Git.

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

The default Gemini transport follows the [AI Studio transcription documentation](https://aistudio.google.com/docs/transcribe):
Files API upload, `gemini-3.5-transcribe` through the Interactions API, explicit
verbatim mode, and transcript extraction from `output_text`. Segments are at most
30 minutes, within the documented one-hour limit for plain transcription.
Tests also cover SDK payload serialization, incomplete responses, remote cleanup,
cache reuse, message ordering, and unchanged historical requests on retry.

Passing local tests does not verify live credentials, model access, or accuracy
on real recordings. A separate live acceptance check requires an explicitly
selected short recording and makes paid Gemini and DeepSeek calls. Confirm a
nonempty transcription, reference-first revision request, successful revision,
and deletion of the uploaded audio. Keep diagnostic artifacts in a temporary
folder outside `evaluation/data`. No live check was performed for this change.
