# Evaluation app

Work in this folder for transcript evaluation. This is a standalone local
Streamlit app, separate from the transcript editor in ../app.

- Each dataset case is a self-contained rough input and reviewed expected output.
- Do not treat legacy example1 files or synthetic fixtures as reviewed benchmarks.
- Keep real datasets, generated responses, run history, and secrets out of Git.
- Never import editor modules or use its working transcripts. Only copy its two
  prompt documents when creating the initial prompt version.
- Prompt versions and run snapshots are immutable. Update edits the selected dataset in place; Save as new dataset creates a separate copy. Existing run snapshots remain unchanged.
- Primary similarity counts all characters, normalizing CRLF/CR to LF only.
  Report the unchanged-input baseline alongside model scores.
- Compare identical dataset snapshots, selected cases, and scoring versions only.
- Holdout cases require explicit selection. Never start API calls on page load.
- Test with fake clients. Do not make paid API calls as part of automated tests.
- Run tests from the repository root: python -m pytest evaluation/tests -q

Use short, natural wording. Do not use em dashes.
