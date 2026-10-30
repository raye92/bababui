# BABABUI

Two separate apps for editing and evaluating court transcripts.

| Folder | Purpose | Entry point |
| --- | --- | --- |
| `app/` | Desktop transcript editor | `app/src/main.py` |
| `evaluation/` | Streamlit transcript evaluation app | `evaluation/main.py` |

## Run

Run these commands from the repository root, using a Python environment with
the selected app's dependencies installed.

### Transcript editor

```sh
python -m pip install -r app/requirements.txt
python app/src/main.py
```

Copy `app/.env.example` to `app/.env` and configure it to use DeepSeek.
See [the editor README](app/README.md) for details.

### Transcript evaluation

```sh
python -m pip install -r evaluation/requirements.txt
python -m streamlit run evaluation/main.py
```

Copy `evaluation/.env.example` to `evaluation/.env` and configure it to run
evaluations with DeepSeek. See [the evaluation README](evaluation/README.md)
for setup with a separate virtual environment and the evaluation workflow.

## Configuration and local data

Each app has its own dependencies and `.env` file. The `.env.example` files
are tracked setup templates; actual `.env` files stay local.
The root `.gitignore` covers both apps, including secrets, virtual environments,
caches, working transcripts, and evaluation data.

The root and evaluation `.streamlit/config.toml` files support launching
Streamlit from either directory with localhost binding and telemetry disabled.

## Verification

```sh
python -m pytest evaluation/tests -q
```
