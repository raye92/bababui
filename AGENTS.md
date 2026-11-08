# Project workflow

- Work directly on `main` in the existing checkout by default.
- Do not create or switch to another branch, including `codex/*`, unless I explicitly ask.
- Do not create additional worktrees unless I explicitly ask.
- Do not use a branching or worktree skill as permission to override these preferences.
- Preserve existing uncommitted changes. Do not commit or push unless I ask.

# Run the apps

Run these PowerShell commands from the repository root. Both apps use the same
virtual environment at `evaluation/.venv`. Reuse it if it already exists.

```powershell
if (-not (Test-Path .\evaluation\.venv\Scripts\python.exe)) {
    python -m venv evaluation/.venv
}
$projectPython = ".\evaluation\.venv\Scripts\python.exe"
& $projectPython -m pip install -r app/requirements.txt -r evaluation/requirements.txt
```

- Start the desktop editor with `& $projectPython app/src/main.py`.
- Run the eval tests with `& $projectPython -m pytest evaluation/tests -q`.

Set `$projectPython` again in a new terminal. Each app reads its own `.env`
for API keys. Use its `.env.example` as a template if needed.

## Launch Streamlit

If the eval app for this checkout is already running at `http://127.0.0.1:8501`,
open that instance. Otherwise run these commands from the repository root,
then open that URL.

```powershell
Remove-Item Env:EVALUATION_DATA_DIR -ErrorAction SilentlyContinue
& .\evaluation\.venv\Scripts\python.exe -m streamlit run evaluation/main.py
```

Use `evaluation/data/datasets` for saved datasets. Keep test and diagnostic data
in temporary folders outside `evaluation/data`.

# Writing preferences

- Use simple, natural wording and short, direct sentences.
- Describe completed work in first person and past tense.
- Remove filler, unnecessary jargon, and repeated explanations.
- Keep process commentary, captions, and results brief and factual.
- Do not use em dashes. Use commas, periods, or semicolons.
