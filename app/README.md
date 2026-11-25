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

## Audio workflow

The fixed toolbar contains File, Edit, and Settings on the left, and BABABUI
and Show Incoming on the right. These controls act on the selected tab.

Create a tab with **Ctrl+T** or **+**. Click the empty tab or drop a Case CATalyst
ZIP onto it. The editor uses the WAV in the job. You can also attach a WAV after
import. Duplicating a tab keeps its transcript, pending revisions, audio, notice,
and model settings.

BABABUI transcribes the WAV with Gemini 3.5 Transcribe and saves the results in
a folder named after the imported ZIP under `app/data/transcriptions/`. For
`Hearing.zip`, `Hearing/Hearing.txt` contains the combined speaker transcript.
`Hearing - chunk 1.json` contains parsed words and timestamps. Each full Gemini
reply is saved as JSON, with its chunk, continuation, fallback, retry, timing
clip, or vocabulary window identified in the filename.

Each transcription run gets a separate folder. Repeated names get ` (2)`, ` (3)`, and so on.
The tab status shows the folder path. Cached runs copy the available files.
The combined transcript is saved before formatting, so it is available if the
editing model fails. BABABUI then formats the transcription and writes the
result to Incoming. The current
transcript is never sent to the model and stays unchanged until revisions are
accepted. Only that tab is locked during processing; scrolling and view switching
remain available. BABABUI becomes a loading bar, with the current stage in the
header. Other tabs can edit and process concurrently. Simultaneous requests
for identical audio share transcription, then format independently. Background
results and warnings stay in their own tabs. Wait for a tab to finish before
closing it, and for all requests to finish before exiting.

Press **BABABUI** again to open the rerun menu. **Clean fresh rerun** is selected
by default. It clears the recording's cached files and runs all three steps.
**Choose steps** lets you select the steps to rerun. **Cancel** closes the menu.
[View the rerun menu](screenshots/rerun-menu.png)

- **Transcription** transcribes the WAV again and saves a new raw transcript.
- **Formatting** turns the new or previously saved raw transcript into Incoming
  and always runs automated review on the new result.
- **Automated review** applies the enabled edit rules to Incoming and uses the
  AI review model when enabled in Settings.

WAVs can be up to 1 hour 57 minutes long. Speaker labels and word timing use up
to four 30-minute chunks starting at minutes 0, 29, 58, and 87. With confirmed
notice names, custom vocabulary uses up to two independent 60-minute chunks,
starting at minutes 0 and 59. A 60-minute recording needs one vocabulary
request. Both schedules overlap by one minute.
If a transcription request returns HTTP 429, the app waits 60 seconds and retries
that request once. If Gemini returns an incomplete timed transcript, the app
retries the remainder once, starting one minute before the end of the last fully
timed word. If it cannot resume, it requests the full chunk with speaker labels
only and recovers word times from matching phrases in the earlier responses.
At each join, the app uses word times and shared wording to match speakers and
remove repeated words. An unmatched speaker receives a new label.
If the wording differs but both chunks have timed words in the overlap, the app
uses the midpoint as a fallback. Review the warnings and resulting transcript.
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

## How review edits are grouped

Each suggestion owns one or more exact ranges in Original and Incoming. Accept
and Reject apply to those ranges. Several suggestions can appear on the same
printed line or in one red/green passage.

| What changed | How the editor groups it |
| --- | --- |
| Words or punctuation | The character diff finds local replacements and can join neighboring changes separated by very little matching text. Shared letters can be highlighted to show a whole word. A surviving sentence keeps its own punctuation edit when nearby turns are added or removed. [Character diff](src/advanced_diff.py) · [Boundary rules](src/diff_heuristics.py) |
| Speaker tags and Q/A | The editor uses ordered phrases from the testimony to find corresponding turns across headings, interruptions, splits and joins. A complete named label changing to Q or A gets one decision. Changes inside the matched speech get separate decisions. Repeated replies use surrounding turns and surviving labels for context. Off-record notes bound the search. [Spoken alignment](src/spoken_edits.py) |
| Inserted or deleted dialogue | Consecutive unmatched dialogue can stay in one section, including a new sentence at the end of a matched turn. The next confidently matched turn starts its own comparison. An unambiguous relocated examiner byline gets one decision with a removal and an insertion. Repeated candidates and conflicting native speaker fields keep separate decisions. [Turn and byline rules](src/spoken_edits.py) |
| Attribution and native fields | A speaker reassignment belongs to that occurrence. A rename of a shared native field belongs to all linked occurrences. Fields and generated labels stay whole. A difference confined to native metadata has its own card. [Speaker matching](src/suggestion_filter.py) · [Decision construction](src/suggestions.py) |
| Word joins and quotation marks | The space in a joined or split word groups with dependent spelling changes to that word. Paired opening and closing quotation marks form one decision, including an attached endpoint correction. Independent edits inside the quotation keep their own controls. [Word and quote rules](src/suggestions.py) |
| Inline display | A paired quotation shows the affected Original lines together, followed by the Incoming lines. A unique adjacent deletion and addition can also share visual context when enough spoken words match. Native page boundaries and line wrapping determine where rows print. [Display sections](src/review_model.py) · [Related passages](src/related_suggestions.py) |
| Filters and saved decisions | Enabled automatic rules evaluate complete eligible wording edits. An ordinary period or question mark can qualify on its own. On reopening an older filtered review, the editor repairs generated groups, preserves custom ranges and highlights, and records newly accepted punctuation in one undoable batch. [Automatic rules](src/suggestion_filter.py) · [Saved review upgrades](src/review_upgrade.py) · [Manual decisions](src/review_editing.py) |

For a shared inline passage, the adjacent deletion and addition must be each
other's only match. They need at least five shared words, four distinct shared
words, a run of four in order, and 70% coverage of the shorter side. Each edit
must gain or lose at least five words and fit within 150 words and six paragraph
breaks per side. A gap with testimony, an off-record note, or more than 160
characters on either side separates the passages. [Display pairing rules](src/related_suggestions.py)

For automatic speaker identification, an unnamed speaker needs at least two
votes and a strict majority from uniquely aligned named turns. Reviewers can
resolve ties and ambiguous native identities. The wording filters cover
punctuation, capitalization, equivalent contractions, short/common words,
ordinal suffixes, positive confirmations and number forms. Numeric punctuation,
negation and native label boundaries have additional guards. Trailing whitespace
and off-record discussion have their own rules. [Filter and speaker rules](src/suggestion_filter.py) · [Off-record matching](src/off_record.py)

## Saving and recovery

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
- `data/transcriptions/` holds named transcription runs.
- `data/transcription-cache/` holds reusable word annotations and Gemini responses keyed by WAV content and model.
  A clean rerun clears speaker chunks, timing clips, responses and vocabulary
  entries for the recording. Older vocabulary entries with unindexed names are
  discarded when those names are next used. Gemini automatically
  deletes uploaded audio after 48 hours. Local caches contain transcript data
  and can be deleted when unused.

Secrets, working transcripts, and caches are excluded from Git. Test with:

```powershell
& .\evaluation\.venv\Scripts\python.exe -m pytest app/tests evaluation/tests -q
```

Tests use fake API clients and temporary data, without paid requests.
