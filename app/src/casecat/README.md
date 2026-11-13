# Native CaseCAT editing

The app imports CaseCAT ZIPs, keeps native Original and Incoming revisions, saves
portable `.bababui` projects, and exports reviewed Original text. The validated
target is CaseCAT 22.1.5.46514. No CaseCAT, REA, or Ghidra runtime is required.

## Code boundaries

This package contains archive handling, native structures, revision associations,
layout projection, timing, and project persistence. UI widgets live beside it:
`app/src/native_editor.py`, `native_dialogs.py`, `playback.py`, and `review_view.py`.

The editor displays native page margins, paragraph styles, fonts, spacing, and
page/line numbers using the existing application palette. Page decorations and
wrapping never become stored text. A review panel sits beside the pages; red/green
highlights and insertion markers show individual wording changes. Show, Previous,
and Next navigate between suggestions. Clicking changed text selects its card.

## Workflow

- File > Import CaseCAT ZIP validates before replacement and offers Save / Replace
  / Cancel when text already exists. Multiple jobs use a picker.
- Source ZIP, steno, WAV, and companion assets remain immutable.
- Actual edit ranges, whole-text proposals, review, and undo retain source anchors.
  Deleted anchors remain present. New wording inherits source passage timing.
- Save creates a movable working project containing the source ZIP and both revisions.
- File > Export CaseCAT ZIP defaults to `<source>_AI.zip`. It exports Original,
  preserving other jobs and companions. Pending Incoming stays in the project.
- Unedited export is the exact original ZIP. Edited export validates the rebuilt
  native transcript and every companion before atomic publication.
- Original and Incoming pages are read-only while reviewing pending proposals.

## Name fields and paragraph symbols

Edit > Insert > Field opens a persistent Field Name / Field Value list, matching
the CaseCAT workflow. New Field creates an empty definition and lets you name it
in the list. Fill In Field edits its value without inserting text. Insert places
a reference at the editor cursor. The list stays open unless Close dialog after
inserting field is checked. Uninserted definitions are saved and exported too.

Double-click a displayed name, or use Fill In Field from the Edit or context menu,
to update every linked occurrence in that revision. Names and Q/A spacing are
atomic cursor steps. Arrow selection, Delete, Backspace, and word deletion operate
on whole elements. Typing over a selected field replaces that occurrence with
ordinary text; changing its linked value uses Fill In Field. Field names appear
in amber and paragraph symbols in blue.

Edit > Insert > Insert Format Symbols opens the supported paragraph-symbol list.
Press q for Question, a for Answer, or m for By-line, then Enter to insert.
Use Change Format Symbol with an existing symbol selected to replace it.
A By-line retains its native style and orphan control separately from its speaker
field. These commands are also available in the editor's context menu.

Original and Incoming keep independent definitions. Changes that have identical
displayed text, such as an unused field definition, appear in the same review panel. Undo, redo, project saves, and copying complete
elements within the app retain their identities. Copying to another application
also supplies plain text. The field list closes when its editor enters review or
becomes read-only.
Original remains read-only while those Incoming changes await acceptance or rejection.

Export updates the native field-definition table and matching EZ Speaker XML
preferences. It preserves field references rather than replacing them with names
as literal text. New definitions use the native name identifier and descriptor
layout observed in controlled CaseCAT saves. Empty definitions retain an editable
`[!FIELD NAME]` placeholder. All-caps jobs retain their display setting.

## Audio playback

Native tabs with WAV audio have back/forward five seconds, Play/Pause, and a
clickable, draggable progress bar below the editor. Clicking transcript text in
Original, Incoming, or the review view seeks to its source passage. Seeking keeps
the current playing or paused state. Shift+F9 seeks to the editor cursor; Ctrl+F9 stops.
Playback highlights source passages without changing text, caret, or undo state.
Changing tabs or hiding the playback bar stops playback.

`timing.py` maps original stroke clocks through recording pause/resume metadata
and applies PCM drift correction using inline audio markers. Insertions and
replacements use the writer's source-group associations. No individual word times
are invented. Unsupported or missing timing disables cursor seeking while plain
WAV playback remains available. Missing WAV permits transcript editing.

Import accepts an extra embedded stroke only when its complete eight-byte record
matches a previously consumed original note. Every original note must still be
covered in order. Each embedded occurrence has a separate editorial reference,
so editing a repeated stroke's text cannot move it to the earlier occurrence.
For playback in this app, repeats inherit the preceding occurrence's effective
clock before pause and PCM drift correction. This is passage timing, not a
measured word timestamp. Projects reconstruct the same clocks from the source.
Original steno, timestamps, and audio records remain byte-identical on export;
this playback adjustment does not rewrite CaseCAT's own timing behavior.

## Verification and limits

The supplied transcript's 12 pages and 277 nonblank lines were compared against
CaseCAT's printed output from the same ZIP. Wording, wrapping, paragraph indents,
centering, and blank lines matched. Text positions were within half a printed
point; all 300 line numbers and 12 page numbers were within one point. The
renderer uses the embedded gutter position and supported right-footer page
number position/font, and keeps the full final page scrollable. Courier New
uses fractional advances with measured native tracking to preserve line width.
These measurements allow for differences in Qt and Windows printer rasterization.
Edited copies opened, saved, and reopened in CaseCAT. A further
four-edit Qt/project/ZIP/native-save round trip retained the expected text and
exact original steno/WAV bytes.

Five checked native seeks matched before and after export: beginning, middle,
end, and both sides of a recording pause. Local captured playback matched the
source WAV at all five positions. The app's timing calculation matched the
measured native centiseconds, and live in-app playback was captured and checked.

These are measured sample results, not universal compatibility or a guarantee
about sound-device latency. Text uses Windows-1252. Unknown structural forms are
rejected. Custom headers/footers, varying section geometry, and custom page
numbering are not fully rendered. See
`C:/Users/caray/Documents/Code/REA/research/casecat_native/current-status.md`
for exact evidence and boundaries.

The field/symbol check opened an exported sample in CaseCAT 22.1. Its Fill In Field
dialog recognized both renamed and newly inserted EZ Speaker fields. Reveal Codes
showed the inserted By-line, Orphan Control 2 lines, Field, and Question records.
After a native save, reimport retained identical text, field/symbol identities, and
steno bytes. Synthetic tests also cover generic name fields, linked edits, clipboard
operations, empty values, all-caps display, partial review, and project restoration.
Field values containing embedded native formatting have not been fully mapped;
this implementation supports single-line Windows-1252 name values.
The mirrored dialogs cover name-field creation, filling and insertion, plus
Question, Answer, and By-line symbols. CaseCAT field-list groups, formulas,
scopes, embedded formatting, and its other format symbols are not implemented.

## Python entry points

- `archive.inspect_archive(path_or_bytes)`: validate and enumerate native jobs.
- `codec.load_job(bundle, job_key)`: load native text and stable source anchors.
- `Revision.replace`, `replace_utf16`, `revise`, `adopt`: native edit/review transactions.
- `Revision.define_field`, `set_field`, `insert_field`: definition creation,
  linked value editing, and insertion of references.
- `codec.validate_job`: verify source bytes and source-anchor integrity.
- `codec.serialize_native`: serialize supported native revisions.
- `archive.export_zip`: validate and atomically publish the archive.
- `AudioMap.from_job`, `position_ms`, `range_at`: native PCM playback associations.
- `documents.import_casecat`, `save_document`, `open_document`: app persistence.

Private source evidence stays under the Git-ignored native research evidence
directory. Temporary field/symbol verification copies and the measured result
are in `C:/temp/bababui-field-parity-final-20261111/verification.json`.


## Unified editor and review

All editable documents originate in a CaseCAT ZIP. Empty tabs are import screens.
Structured original/incoming revisions own the text, fields, and associations;
displayed text is derived, and projects/recovery version 2 omit duplicate text.
Version 1 CaseCAT projects remain readable. Plaintext files remain untouched but
are no longer opened as editable documents. Legacy recovery is backed up.

The Manual menu is retired. `transcript_formatting.py` and the formatter wrapper
remain reference material and evaluation support, not an editor processing path.
AI proposals retain paragraph indentation and Q/A spacing from matched source
paragraphs. Review decisions operate on exact word/phrase ranges, with linked
fields grouped atomically. The panel offers independent Accept/Reject decisions;
Edit > Undo review / Redo review restores both revisions together.
