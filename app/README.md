# Transcript editor

The main app lives in this `app/` folder, with its code and data in `src/`. The sibling `../evaluation/` folder holds samples for a future evaluation app.

## Run

From the repository root, enter the app folder and install dependencies:

```sh
cd app
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and configure the DeepSeek settings to use the DeepSeek button.

Start the editor from the app folder:

```sh
python src/main.py
```

From the repository root, use `python app/src/main.py`. From another directory, use the absolute path to `app/src/main.py`.

## Files

- `src/`: Python app code, prompt documents, and local transcript data.
- `src/original.txt` and `src/incoming.txt`: the editor's working transcripts.
- `src/original/` and `src/stripped/`: batch formatting input and output.
- `../evaluation/`: sample JSON files and space for the future eval app.
- `.env` and `requirements.txt`: project configuration and dependencies.

Paths are resolved from the app location. Secrets, local transcript data, and Python caches are excluded from Git.
