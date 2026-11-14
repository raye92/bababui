# Transcript editor

The desktop editor compares the current transcript with an Incoming version.
Accept or deny revisions in the inline diff.

## Run

From the repository root, reuse `evaluation/.venv`:

```powershell
& .\evaluation\.venv\Scripts\python.exe -m pip install -r app/requirements.txt -r evaluation/requirements.txt
& .\evaluation\.venv\Scripts\python.exe app/src/main.py
```

Install FFmpeg and FFprobe on PATH, or set `FFMPEG_PATH` and `FFPROBE_PATH`.
Copy `.env.example` to `.env` if needed. Set `GEMINI_API_KEY` for transcription
and Gemini formatting; set `DEEPSEEK_API_KEY` for DeepSeek formatting.
Environment variables take precedence over `app/.env`.

## Audio workflow

The fixed toolbar contains File, Manual, and Settings on the left, and BABABUI
and Show Incoming on the right. These controls act on the selected tab.

Create a tab with **Ctrl+T** or **+**. A tab without audio has a dotted outline:
click its header to open File Explorer, or drop one WAV onto it. Its title becomes
the WAV filename until saved. Right-click a tab to duplicate it, replace its WAV,
or close it. Duplicates keep the text, pending revisions, WAV, and model settings,
but start as unsaved versions with no running request.

BABABUI validates the WAV, transcribes it with Gemini 3.5 Transcribe and speaker
tags, and automatically saves the raw speaker-labeled text beside the WAV as
`<wav-name>.raw.txt` before calling the editing model. This file is also written
when cached transcription is reused, and remains available if editing fails.
Each run replaces this raw export; save review edits in a separate file. The WAV
folder must be writable. BABABUI then formats the transcription and writes the
result to Incoming. The current
transcript is never sent to the model and stays unchanged until revisions are
accepted. Only that tab is locked during processing; scrolling and view switching
remain available. BABABUI becomes a loading bar, with the current stage in the
header. Other tabs can edit and process concurrently. Simultaneous requests
for identical audio share transcription, then format independently. Background
results and warnings stay in their own tabs. Wait for a tab to finish before
closing it, and for all requests to finish before exiting.

WAVs must be no longer than 59 minutes. Recordings longer than 30 minutes use
chunks 0:00-30:00 and 29:00-end. Word timestamps and tolerant text alignment match
speakers and remove the repeated minute. Matching is best effort: an unmatched
speaker receives a new label, and an uncertain join falls back to 29:30. Review
the warnings and resulting transcript, especially speakers absent from the
overlap. Timestamps are used internally and do not appear in Incoming.

Each tab remembers its processing model: Gemini 3.8 Flash (default), Gemini 4
Argon, DeepSeek V4 (`deepseek-flash`), or DeepSeek V4 Pro. The transcription model
is Gemini 3.5 Transcribe. Manual contains Strip Formatting, Apply Standards,
Insert Sample, and Batch Strip.
Batch Strip lets you choose a folder and writes results into its `stripped`
subfolder. It starts from the selected document's folder when available.

`src/bababui_prompt.md` contains the transcript-editing instructions and the cleaned
rules, examples, and explanations from `MWW SUMMARY - smileys fixed.pdf`. Edit the
`# Task` section at the top to update the instructions. The task instructions
convert speaker labels into examination headings, Q/A, and speaker-tagged colloquy,
preserving speaker numbers, order, and testimony. The model returns one logical
line per paragraph, with labels and paragraph indentation. Before sending the
response to Incoming, the shared transcript formatter wraps at
56 characters, including indentation and labels but excluding the line-number
gutter. Continuation lines start flush left. Words and hyphenated terms are never
split; a single longer token may exceed the width. It then adds numbered,
25-line pages, just like Manual > Apply Standards. Reapplying standards removes
existing numbering and wrapping first.

Strip Formatting and Batch Strip remove numbering and join recognized wrapped
continuations, including across page breaks, with one space. Speaker turns,
indented topic paragraphs, headings, and procedural notations remain separate.
Ambiguous line breaks and standalone numeric answers are preserved. Other
spacing within paragraphs stays unchanged. A continuation is joined only when
its first word would not fit on the preceding physical line with one space.

Book navigation and the duplicate page are removed. Clear OCR errors are repaired,
and correct/incorrect example markers are written as text.
The button reloads this file on each run. This is the only editor formatting
prompt. Evaluation keeps its own saved prompts.

## Saving and recovery

The inline diff compares transcript content, without printed line numbers,
page layout, or wrapping. Headings, examiner labels, questions, answers, and
speaker turns are matched in order. Changed words are highlighted inside
paired passages. Accept and Deny apply to those passages; numbered documents
are wrapped and numbered again after each decision. Formatting alone does not
create a pending change.

- **Ctrl+S** saves the reviewed Original text to `.txt`, even when viewing
  Incoming. The companion `<filename>.txt.bababui.json` keeps pending Incoming
  revisions, the WAV path, and model selections. Keep both files together.
- **Ctrl+Shift+S** saves a new version. New saves require unique text and companion
  filenames; existing files are never silently replaced. Subsequent Ctrl+S
  updates the file already owned by that tab.
- **Ctrl+O** opens text and its companion. Plain text opens without an audio link.
  Missing WAVs do not prevent editing; use Replace WAV before processing.
- A dot indicates unsaved changes. Closing a dirty tab (**Ctrl+W**) offers Save,
  Discard, or Cancel. Reopening an already-open path selects its existing tab.
- Open tabs, unsaved changes, pending revisions, and view state are recovered
  automatically after restart. Recovery does not clear the unsaved dot or write
  your text files. Interrupted requests never restart automatically.
- On the first launch, the previous `src/original.txt` and `src/incoming.txt`
  pair is imported into an unsaved tab. The old files remain untouched.
- Incomplete saves and mismatched companion files produce a warning instead of
  applying potentially unrelated revisions.

## Local app data

- `data/session.json`: local recovery for all open tabs, including unsaved text.
- `data/save-locks/`: locks protecting document saves across app instances.
- `data/transcriptions/`: cached word annotations, keyed by WAV content and model.
  Retrying formatting reuses completed transcription chunks. Remote uploads are
  deleted after transcription; failed cleanup is retried on the next run for that
  recording. Local caches contain transcript data and can be deleted when unused.

Secrets, working transcripts, and caches are excluded from Git. Test with:

```powershell
& .\evaluation\.venv\Scripts\python.exe -m pytest app/tests evaluation/tests -q
```

Tests use fake API clients and temporary data, without paid requests.
