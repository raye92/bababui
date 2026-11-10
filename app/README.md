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

The fixed toolbar contains Manual and Settings on the left, a centered WAV input,
and BABABUI and Show Incoming on the right. Drop one local WAV onto the input,
or click it to open File Explorer. The selected filename appears in the input.

BABABUI validates the WAV, transcribes it with Gemini 3.5 Transcribe and speaker
tags, formats that transcription, and writes the result to Incoming. The current
transcript is never sent to the model and stays unchanged until revisions are
accepted. Editing is temporarily locked during processing; scrolling and view
switching remain available. Wait for processing to finish before closing.

WAVs must be no longer than 59 minutes. Recordings longer than 30 minutes use
chunks 0:00-30:00 and 29:00-end. Word timestamps and tolerant text alignment match
speakers and remove the repeated minute. Matching is best effort: an unmatched
speaker receives a new label, and an uncertain join falls back to 29:30. Review
the warnings and resulting transcript, especially speakers absent from the
overlap. Timestamps are used internally and do not appear in Incoming.

Settings remembers the processing model: Gemini 3.8 Flash (default), Gemini 4
Argon, DeepSeek V4 (`deepseek-flash`), or DeepSeek V4 Pro. The transcription model
is Gemini 3.5 Transcribe. Manual contains Strip Formatting, Apply Standards,
Insert Sample, and Batch Strip.

Edit `src/bababui_prompt.md` to replace the basic formatting placeholder. This
is the only editor formatting prompt. Evaluation keeps its own saved prompts.

## Local files

- `src/original.txt` and `src/incoming.txt`: working transcripts.
- `src/original/` and `src/stripped/`: batch formatting files.
- `data/transcriptions/`: cached word annotations, keyed by WAV content and model.
  Retrying formatting reuses completed transcription chunks. Remote uploads are
  deleted after transcription; failed cleanup is retried on the next run for that
  recording. Local caches contain transcript data and can be deleted when unused.
- Model preferences use Qt's local application settings.

Secrets, working transcripts, and caches are excluded from Git. Test with:

```powershell
& .\evaluation\.venv\Scripts\python.exe -m pytest app/tests evaluation/tests -q
```

Tests use fake API clients and temporary data, without paid requests.
