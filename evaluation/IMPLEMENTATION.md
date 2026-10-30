# Implementation record

The approved plan is a standalone Streamlit evaluation app with immutable prompt
versions, input/output dataset revisions, durable sequential DeepSeek runs,
character similarity, unchanged-input baselines, and compatible-run comparisons.

Decisions:
- Keep the user's existing workspace and folder reorganization intact. No editor
  files are changed and no existing changes are committed.
- Use RapidFuzz for character Levenshtein distance, avoiding quadratic Python loops.
- Use an evaluation-owned HTTP adapter because the editor module has import-time
  configuration and prompt-loading side effects.
- Add a repository-level Streamlit config solely so the documented launch command
  binds to localhost. Include the same config inside evaluation for launching there.
- Use OS file locks for runs. A crash releases the lock; retries are always explicit.
- Update datasets in place when requested; Save as new dataset creates a separate record. Previous run snapshots remain unchanged.

Implementation checks are tracked in the tests. Real API calls are not part of
verification. Synthetic fixtures remain separate from reviewed benchmark data.
