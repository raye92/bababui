# Transcript editor

The desktop editor compares the current transcript with an Incoming version.
Accept or reject revisions in the inline diff.

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
Set `TESTING=TRUE` to save Gemini transcription responses and AI review logs in
the system temp folder under `bababui-transcriptions`. The default is `FALSE`.

## Audio workflow

The fixed toolbar contains File, Edit, and Settings on the left, and BABABUI
and Show Incoming on the right. These controls act on the selected tab.

Create a tab with **Ctrl+T** or **+**. Click the empty tab or drop a Case CATalyst
ZIP onto it. The editor uses the WAV in the job. You can also attach a WAV after
import. Duplicating a tab keeps its transcript, pending revisions, audio, notice,
and model settings.

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

WAVs can be up to 1 hour 57 minutes long. Speaker labels and word timing use up
to four 30-minute chunks starting at minutes 0, 29, 58, and 87. With confirmed
notice names, custom vocabulary uses up to two independent 60-minute chunks,
starting at minutes 0 and 59. A 60-minute recording needs one vocabulary
request. Both schedules overlap by one minute.
If a transcription request returns HTTP 429, the app waits 60 seconds and retries
that chunk once. Word timestamps and tolerant text alignment match speakers and
remove repeated words at each join. An unmatched speaker receives a new label.
If alignment is uncertain and both chunks have timestamps, the app joins them
at the midpoint of the overlap. Review the warnings and resulting transcript.
Timestamps are used internally and do not appear in Incoming.

## Notice PDFs

After importing a Case CATalyst ZIP, choose **Upload notice PDF** or **Skip**.
Use **Edit > Attach or replace notice PDF** to add a notice later. The editor
reads text, annotations, and scanned pages locally. Review the caption and file
number, taking side and recording time, appearances, and examiner names.
Settings can prefill the file number from a filename such as
`261110thaler 1757905.pdf`. This setting is off by default.

Applying a notice fills the native cover and keeps manual examination page
numbers and exhibit entries. Testimony begins on page 5, line 11. The working
project and session recovery retain the notice. Confirmed names help the audio model recognize
the participants, firms, witness and caption parties. The speaker-labeled raw
export and formatting use the reconciled spellings.

Each tab remembers its processing model: Gemini 4 Argon (default), Gemini 3.8
Flash, DeepSeek V4 (`deepseek-flash`), or DeepSeek V4 Pro. The transcription model
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
paired passages. Accept and Reject apply to those passages. Numbered documents
are wrapped and numbered again after each decision. Formatting alone does not
create a pending change.

Open the Settings tab for automated edits, AI models, and the Hotkeys reference.
While reviewing a suggestion, **A** accepts it and **D** rejects it. With audio
timing, **W** starts playback one second before the edit. **S** skips forward
five seconds by default. Change the skip interval under Hotkeys.

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
  Retrying formatting reuses completed transcription chunks. Gemini automatically
  deletes uploaded audio after 48 hours. Local caches contain transcript data
  and can be deleted when unused.

Secrets, working transcripts, and caches are excluded from Git. Test with:

```powershell
& .\evaluation\.venv\Scripts\python.exe -m pytest app/tests evaluation/tests -q
```

Tests use fake API clients and temporary data, without paid requests.
