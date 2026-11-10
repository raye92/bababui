# Transcript content diff implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Review changes to transcript content without numbering, whitespace, or wrapping changes.

**Architecture:** Parse display text into logical blocks with physical source locations. Align unchanged anchors and then similar blocks in sequence, highlight word edits, and resolve content before regenerating formatted output.

**Tech Stack:** Python, difflib, PySide6, existing TranscriptFormatter, pytest.

**Spec:** The user approved approach 2 in this chat and explicitly requested implementation with no formatting-only review mode.

## Global constraints

- Work in the existing checkout on main. Do not commit or push.
- Preserve actual testimony numbers, punctuation, labels, and document content.
- No LLM requests or additional dependencies for diffing.
- Keep Accept/Deny and editing of unchanged content working.

## Review focus

- Repeated short answers must use surrounding question context.
- Real numeric answers must survive layout removal.
- Split or joined continuation lines must not create review items.
- Repeated Accept/Deny and live edits must not use stale block offsets.
- Formatted documents must retain valid numbering after decisions, and scroll mapping must use physical locations.

## Task 1: Content comparison

**Files:** app/src/transcript_diff.py, app/tests/test_transcript_diff.py

**Interfaces:** parse_transcript(text) returns blocks with text, kind, source_start/source_end; align_blocks(left, right) returns difflib-style opcodes; word_spans(left, right) returns changed character ranges for each side; render_blocks(blocks, formatted) serializes content.

- [x] Write failing tests for the supplied heading/name example, layout-only changes, numeric answers, repeated questions/answers, splits/joins, and word highlights.
- [x] Run the tests and confirm failure, then implement parsing, ordered alignment and serialization.
- [x] Run the targeted tests and confirm success.

## Task 2: Review UI and document integration

**Files:** app/src/diff_view.py, app/src/document_view.py, app/tests/test_diff_view.py

- [x] Write failing tests for separate review controls, content-only equality, Accept/Deny in different orders, unchanged-block editing and formatted output.
- [x] Render logical blocks, highlight word changes, and resolve using mutable block ranges instead of stale physical line offsets.
- [x] Keep plain documents plain; regenerate formatted documents with TranscriptFormatter. Treat content-equivalent incoming text as resolved.
- [x] Run app/tests and evaluation/tests and inspect a rendered offscreen example.
- [x] Review the final change independently and address substantive findings.

## Progress

- Initial checkout was clean. User's direct implementation instruction supplies authorization; no additional approval gate or branch is needed.

- Task 1 complete: parsing/alignment regressions verified, including printed numeric wraps, repeated answers, and long paragraph splits.
- Task 2 complete: separate review controls, word highlights, live edits, mouse acceptance, resizing, and content-only equality verified.
- Independent review findings fixed: keep answers with their questions, coalesce adjacent unchanged regions, partition large changed ranges using strong shared-word anchors, and avoid rerunning alignment during each live edit.
- Ruling: preserve explicit Q/A boundaries when an unindented printed line is ambiguous; identical joined content is treated as layout-equivalent during matching.
- Verification: 212 tests passed with `evaluation/.venv/Scripts/python.exe -m pytest app/tests evaluation/tests -q`; `git diff --check` passed.
- Visual verification: inspected an offscreen render with real Windows fonts. Long paragraphs wrap without clipping and changed words are highlighted.
- Read-only check of the saved Goebel example produced heading insertion, examiner replacement, and opening-question replacement as separate regions in 0.01 seconds.
- Performance check: 1,000 changed questions with answers improved from 3.895 seconds to 0.030 seconds on this checkout.
- No commits, pushes, or user transcript/session edits were made.
