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
Set `TESTING=TRUE` to save Gemini transcription responses and AI review logs,
including the speaker, house spelling and spelling reviews, in the system temp folder under
`bababui-transcriptions`. The default is `FALSE`.

## Audio workflow

The fixed toolbar contains File, Edit, and Settings on the left, and BABABUI
and Show Incoming on the right. These controls act on the selected tab.

Create a tab with **Ctrl+T** or **+**. Click the empty tab or drop a Case CATalyst
ZIP onto it. The editor uses the WAV in the job. You can also attach a WAV after
import. Duplicating a tab keeps its transcript, pending revisions, audio, notice,
and model settings.

A CaseCAT date field, such as the date after "Dated this" in a certificate,
shows as a date like November 19, 2026. CaseCAT keeps its own date format,
and the field goes back into the ZIP unchanged. A field type Bababui cannot
read stops the import and names its byte position.

BABABUI validates the WAV, transcribes it with Gemini 3.5 Transcribe and speaker
tags, and automatically saves the raw speaker-labeled text beside the WAV as
`<wav-name>.raw.txt` before calling the editing model. This file is also written
when cached transcription is reused, and remains available if editing fails.
Each run replaces this raw export; save review edits in a separate file. The WAV
folder must be writable.

With AI-assisted review on, the AI review model then checks speaker attribution
and turn boundaries on the stitched Gemini transcript, before Q/A and colloquy
formatting. It reviews every turn, using introductions, the current examiner, who
is addressed, the preceding question, the following response, and the confirmed
notice. It proposes a split at the first word the next person speaks, or a new
label when the exchange identifies one participant. Words, their order and their
audio times never change, and the raw export stays Gemini's own transcript.

Every proposed change keeps Gemini's label, the proposed label and the reason.
A proposal is checked before it is applied. It conflicts with the exchange when
the turn speaks directly to the proposed speaker ("Doctor, when you ..." is not
said by the doctor), when it gives the witness an objection, or when it rests on
a bare courtesy such as "Thank you". It also conflicts when the reporter's rough
attributes the words to Gemini's speaker. Each rough speaker's Gemini label is
learned only from turns where the review kept Gemini's label, so a job where
Gemini mixed up two voices cannot turn the rough against a correct fix. A
conflicting proposal goes to Gemini
with the audio of that turn and the turns immediately before and after it. If
the voice confirms the proposal, it is applied; if it confirms Gemini's label,
the proposal is dropped. Otherwise Gemini's label stays, the turn is formatted
by that speaker's role and flagged, and a warning gives its audio time. A
suggestion that changes the label of a flagged turn says Needs review, and
Accept All asks before accepting it. When the
exchange establishes only a role, such as an objection that either of two
attorneys could have made, Gemini's label stays and the turn is flagged too.
The audio check hears up to two turns before and after the disputed turn, so
it can tell who was addressed, who answered, and who resumed.

Before the speaker review, each voice keeps one label for the whole job. Gemini
numbers the voices afresh in every chunk. Each chunk's voices are matched in
the minute it shares with the previous chunk, against that chunk's job-wide
labels: by 5 shared words, or by 2 that are the same word at the same moment of
the WAV, such as "Okay. Now," before a new question. When Gemini put two voices
under one number in the earlier chunk, only the better match keeps the label.
A voice that did not speak in the shared minute gets a new, provisional label.
It may be an attorney returning from an earlier chunk. Gemini compares the
clearest clips of that voice with a clip of every earlier voice. When both of
its clips match one earlier voice, its turns take that label. A voice is never
matched because one label is left over. Recovery clips are matched the same
way. A voice that stays unresolved is asked about once (see Speaker decisions).
When the review gives such a label back to an earlier speaker by the exchange,
that is renumbering, and it is not highlighted.

A review card that gives words to a different speaker, such as Q to THE WITNESS:
or a split that moves words from a Q to an A, is titled Speaker. When the speaker
review made the change, the card shows Gemini's label, the proposed label, the
reason and the checks. A corrected speaker label is yellow in Incoming, the inline
view and the Accept All preview, even inside a green wording edit, and only on the
reassigned part of a split turn. Converting a correct label to Q or A adds no
highlight.

After the speaker review and before formatting, BABABUI applies the house
spelling reference, `app/assets/Spelling and Terminology.csv`. It is the only
word list, and it ships with the app. To add or change a word, edit a row in the
CSV and save it; the next run reads it again, with no code change. The House
form column is the approved spelling, capitalization, hyphenation and spacing,
and it wins over any other dictionary variant. Rows marked Whole-word spelling
change a complete matching word or phrase automatically, such as xrays to
X-rays. For rows marked Context, the review model reads each sentence with the
row's example and scope and decides: "a follow up visit" becomes "a follow-up
visit", but "I asked him to follow up" stays. Without AI review, the formatting
model decides. A change keeps a plural or tense ending, a capital at the start
of a sentence and an all-caps heading. Quoted words, a spelling given letter by
letter on the record and a capitalized official name are not changed. The
Candidate column's other forms are matched, and a phrase there such as "back up
the file" contributes only the words that spell the house form. Notes and examples are
instructions, never words to swap in. A word that already has the house form
gets no edit and no highlight, and no dictionary is looked up. The formatting
prompt has style rules of its own, such as X ray for the noun, so after
formatting the Whole-word rows are applied again, without a model call, and the
CSV has the last word. Speaker labels and BY lines are left alone, and Context
rows are not asked again. The job summary counts these as restored after
formatting. In the editor, a change to a house form stays a suggestion, green
on the changed term only:
automatic rules and the AI wording review leave it for you to accept. Words that
are not in the CSV go through the review as before.

After formatting, the AI review model also checks spellings. It reads the
reporter's rough and every AI edit, with the confirmed notice names, the job
vocabulary and the rough's named speakers. A word gets an orange wavy underline
only when its exact spelling needs your judgment: several spellings fit what was
said and nothing settles the choice, or the spelling conflicts with a reliable
source for that person, organization or term. It checks people's names, including
a surname used alone, organizations, facilities, locations, case names, named
tests, medications, brands, acronyms and specialized terms. Being a name or a
technical term is never enough, and neither is a missing dictionary entry. A
spelling that the notice, the job vocabulary or a letter-by-letter spelling in
the testimony confirms stays unmarked, and so does every word in the house
spelling reference. A capitalized word that nearly matches a
confirmed name, such as Meyer where the notice has Meier, is underlined even if
the model missed it. Only the uncertain word is marked, so in Pacific
Orthopaedic Associates only Orthopaedic is underlined when that is the only
question.

The same words are underlined in Original, Incoming, the inline view and the
Accept All preview. Hover over an underlined word to see the other spellings and
the reason. The underline stays visible over green, red and yellow edit colors.
It never changes the transcript, and it is not copied, saved into the text or
exported. The words to check stay with the tab after the review ends and while
you edit, and an underline goes away when you change that word. If the check
fails, the draft still arrives and the status says the spelling review could not
run.

BABABUI then formats the transcription and writes the
result to Incoming. The current
transcript is never sent to the model and stays unchanged until revisions are
accepted. Only that tab is locked during processing; scrolling and view switching
remain available. BABABUI becomes a loading bar, with the current stage in the
header. Other tabs can edit and process concurrently. Simultaneous requests
for identical audio share transcription, then format independently. Background
results and warnings stay in their own tabs. Wait for a tab to finish before
closing it, and for all requests to finish before exiting.

After formatting, BABABUI checks whom each turn addressed. It knows who spoke
each turn from the labels the formatter was given, after the speaker review. It
corrects a Q/A or colloquy label where a later reply settles whom a question was
for. When the witness asks "Are you asking me or counsel?" and the examiner
answers "Counsel, I'm sorry.", the question, the witness's question and the
answer are colloquy under each speaker's label. Colloquy continues while the
examiner addresses counsel. The first turn that addresses the witness, or that
the witness answers, becomes Q after a BY line. A turn that thanks counsel and
then addresses the witness is split at that sentence. When the answer names the
witness, as in "You, Doctor.", the exchange is Q and A. Only labels and BY lines
change. A revision that would change a word is discarded. In the editor, each
corrected label is its own card titled **Q/A or colloquy**, with the reason.
Accepting it leaves nearby wording suggestions pending. The status line counts
the revised labels.

WAVs can be up to 1 hour 57 minutes long. Speaker labels and word timing use up
to four 30-minute chunks starting at minutes 0, 29, 58, and 87. With confirmed
notice names, custom vocabulary uses up to two independent 60-minute chunks,
starting at minutes 0 and 59. A 60-minute recording needs one vocabulary
request. Both schedules overlap by one minute.
If a transcription request returns HTTP 429, the app waits 60 seconds and retries
that chunk once. Word timestamps and tolerant text alignment match speakers and
remove repeated words at each join. A speaker who does not speak in the shared
minute receives a new, provisional label that the voice check resolves.
If alignment is uncertain and both chunks have timestamps, the app joins them
at the midpoint of the overlap. If a chunk's words end before that point, the
next chunk is kept from where they end, and a warning names the gap.
Review the warnings and resulting transcript.
Gemini sometimes stops a chunk early or skips part of it. When steady speech is
followed by more than 45 seconds with no words, the app transcribes that part
again, from a minute before the gap, and joins it once. This covers the last
chunk and gaps in the middle of a chunk. A pause announced as going off the
record, a recess or a break is left alone. The extra request is cached with the
chunk, and a warning names the part to review.
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

When only the AI speaker tag disagrees with an existing speaker label, BABABUI
checks two more sources. The voice check compares the turn's pitch with this
job's own speakers, and the wording check uses reliable cues such as an
objection or a turn that addresses counsel. If either supports the existing
label, the label stays and no change appears. If either agrees with the AI tag,
the change is suggested. Otherwise the card says Needs review, and Accept All
asks before accepting it.

### Speaker decisions

The speaker list asks only what remains uncertain, one question per identity,
with separate counts of unresolved identities and the turns they affect.
Resolved speakers are collapsed under **Resolved speakers**.

- **Unresolved voice** asks once about a voice with several turns. It shows the
  clearest identifying sentence, the suggested participant when the rough
  supports one, and how many turns are linked. Turns are linked only when the
  voice check matched them to the identifying clip, or when Gemini grouped many
  turns of one established voice. A shared Gemini number alone links nothing:
  a turn by another voice under the same number is asked separately.
- **Who said this?** asks about one turn, such as an "Okay." the audio check
  could not attribute.

Choose a participant, then **Assign this turn** or **Assign all N linked
turns**. An assignment changes only the labels. The same label change is
accepted into Original, and every wording change nearby stays pending. When
the rough gives that turn to the same person, the turn takes the rough's form:
Q, A or colloquy. Otherwise, a turn that follows a Q, an A or a BY line shows
as Q for the examiner on the BY line and A for the witness, and any other turn
is colloquy under the participant's name. **Review** goes to the identifying turn and plays
it from four seconds earlier. **Undo** reverses the last assignment.

Assignments are saved with the job and its WAV times. When the same job is
processed again, each new turn whose audio overlaps an assigned turn gets that
name, so a changed Gemini number cannot move a name to a different person. A
review saved before voices were checked groups turns by Gemini's number and
says so; process the job again to check the voices.

A card titled **Missing from AI draft** marks a passage of at least 25 words
that the AI draft lacks. The transcription probably missed that audio, so
listen before accepting it. Accept All and its preview keep your text there and
leave the card pending. A passage the draft only moved is not marked.

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
