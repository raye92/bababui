"""Run with: python -m streamlit run evaluation/main.py (from repo root)."""
import json
import os
from pathlib import Path
import subprocess
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from evaluation.client import DeepSeekClient, load_config
from evaluation.core import (Store, SEPARATOR, parse_jsonl, create_run,
                             execute_run, summary, compare_runs, comparison_key,
                             comparison_csv, visible_diff, validate_cases, valid_text)
from evaluation.setups import (DEFAULT_FILTERS, DEFAULT_MODEL, LEGACY_FILTERS, MODELS,
                               expected_for_grading, formatted_transcript, grading_text)

from evaluation.imports import import_files, folder_files
from evaluation.storage import resolve
from evaluation.transcription import (AUDIO_MODELS, DEFAULT_AUDIO_MODEL, GeminiTranscriber,
                                      workload, retry_workload, preflight, has_key)


def label(record):
    return f"{record['name']} · {record['created_at'][:16]} · {record['id'][:8]}"


@st.fragment
def folder_label(title, folder):
    folder = folder.resolve()
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown(title, width="content")
        clicked = st.button(str(Path(folder.parent.name) / folder.name), icon=":material/folder_open:",
                            type="tertiary", key=f"open_folder_{title}", help=f"Open `{folder}`")
    if clicked:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, str(folder)])
        except OSError as exc:
            st.error(f"Could not open {folder}: {exc}")


def record_selector(title, folder, options, *, multiple=False, **kwargs):
    folder_label(title, folder)
    widget = st.multiselect if multiple else st.selectbox
    return widget(title, options, label_visibility="collapsed", **kwargs)


def datasets_page(store):
    st.header("Datasets")
    st.caption("Each pair contains one self-contained rough excerpt and its reviewed expected output.")
    datasets = store.list("datasets")
    if not datasets:
        st.info("No datasets yet. Import pairs or add your first pair below.")
    with st.expander("Import a dataset", expanded=not datasets):
        st.caption("Each case requires <id>.txt, <id>_scoped.txt and <id>.wav. Separators: underscore, hyphen, period or space.")
        source = st.radio("Import source", ["Upload files", "Local folder"], horizontal=True)
        with st.form("import_dataset"):
            name = st.text_input("Dataset name", key="import_name")
            if source == "Local folder":
                folder = st.text_input("Local folder path")
                uploads = None
            else:
                mode = st.radio("Import format", ["Text pairs", "JSONL"], horizontal=True)
                uploads = st.file_uploader("Choose text and WAV files", type=["jsonl", "txt", "wav"],
                                           accept_multiple_files=True, max_upload_size=2048)
            submitted = st.form_submit_button("Import dataset")
        if submitted:
            if not name.strip():
                raise ValueError("Dataset name must be nonempty text.")
            if source == "Local folder":
                cases = import_files(store, folder_files(folder))
            else:
                if not uploads:
                    raise ValueError("Choose files to import.")
                if len({file.name.casefold() for file in uploads}) != len(uploads):
                    raise ValueError("Duplicate filenames. Every filename must be unique.")
                files = {file.name: file.getvalue() for file in uploads}
                records = None
                if mode == "JSONL":
                    documents = [n for n in files if n.lower().endswith(".jsonl")]
                    if len(documents) != 1:
                        raise ValueError("Choose one JSONL file plus matching WAV files.")
                    records = parse_jsonl(files.pop(documents[0]).decode("utf-8-sig"))
                cases = import_files(store, files, records)
            saved = store.save_dataset(name, cases)
            st.session_state["dataset_navigation"] = (saved["id"], cases[0]["id"])
            st.rerun()

    options = {"new": None, **{d["id"]: d for d in datasets}}
    if "dataset_navigation" in st.session_state:
        destination, pair = st.session_state.pop("dataset_navigation")
        st.session_state["dataset_selection"] = destination
        st.session_state[f"pair_{destination}"] = pair
    selected = record_selector("Dataset to view or extend", store.root / "datasets", list(options),
                               format_func=lambda key: "New dataset" if key == "new" else label(options[key]),
                               key="dataset_selection")
    dataset = options[selected]
    if dataset:
        st.dataframe([{"id": c["id"], "split": c["split"], "input_characters": len(c["input"]),
                       "expected_characters": len(c["output"]), "audio": c["audio"]["filename"],
                       "audio_minutes": round(c["audio"]["duration"] / 60, 2)} for c in dataset["cases"]], hide_index=True)
        st.download_button("Export dataset JSONL", "\n".join(json.dumps(c, ensure_ascii=False) for c in dataset["cases"]) + "\n",
                           f"dataset-{dataset['id'][:8]}.jsonl", "application/x-ndjson")
    existing = {c["id"]: c for c in dataset["cases"]} if dataset else {}
    choice = st.selectbox("Pair to edit", [*existing, None], format_func=lambda x: "Add a pair" if x is None else x,
                          key=f"pair_{selected}")
    initial = existing.get(choice, {})
    suffix = "new" if dataset is None else f"{selected}_{choice}_{dataset['hash']}"
    st.subheader("Add or edit a pair")
    with st.form(f"pair_form_{suffix}"):
        identifier = st.text_input("Case ID", value=initial.get("id", ""), key=f"case_id_{suffix}")
        left, right = st.columns(2)
        rough = left.text_area("Rough input", value=initial.get("input", ""), height=230, key=f"input_{suffix}")
        expected = right.text_area("Expected output", value=initial.get("output", ""), height=230, key=f"output_{suffix}")
        split = st.selectbox("Split", ["development", "holdout"], index=int(initial.get("split") == "holdout"))
        audio_upload = st.file_uploader("Matching WAV", type=["wav"], key=f"audio_{suffix}", max_upload_size=2048)
        if initial.get("audio"):
            st.caption(f"Saved audio: {initial['audio']['filename']}")
        updated = st.form_submit_button("Update", key="update_dataset", disabled=dataset is None)
        st.divider()
        name = st.text_input("New dataset name", value=f"{dataset['name']} (copy)" if dataset else "",
                             key="manual_name" if dataset is None else f"manual_name_{suffix}")
        saved = st.form_submit_button("Save as new dataset", key="save_dataset_as_new")
    if updated or saved:
        edited = {"id": identifier, "input": rough, "output": expected, "split": split}
        proposed = [edited if c["id"] == choice else c for c in existing.values()]
        if choice is None:
            proposed.append(edited)
        validate_cases(proposed, require_audio=False)
        if saved:
            valid_text(name, "Dataset name")
        if audio_upload is not None:
            edited = import_files(store, {audio_upload.name: audio_upload.getvalue()}, [edited])[0]
        elif initial.get("audio"):
            edited["audio"] = initial["audio"]
        else:
            raise ValueError("A matching WAV is required before saving a case.")
        cases = [edited if c["id"] == choice else c for c in existing.values()]
        if choice is None:
            cases.append(edited)
        record = store.update_dataset(selected, cases) if updated else store.save_dataset(name, cases)
        st.session_state["dataset_navigation"] = (record["id"], identifier)
        st.rerun()


def setup_page(store):
    st.header("Evaluation Setup")
    st.caption("Save a model, filters, and prompt together. Copy a setup to try a single change.")
    prompts = store.list("prompts")
    sources = {p["id"]: p for p in prompts}
    if "saved_setup" in st.session_state:
        st.session_state["copy_setup"] = st.session_state.pop("saved_setup")
        st.success("Setup saved.")
    selected = record_selector("Copy from setup", store.root / "prompts", list(sources),
                               format_func=lambda key: label(sources[key]), disabled=not sources, key="copy_setup")
    source = sources.get(selected, {"instructions": "", "rules": ""})
    if st.session_state.get("prompt_source") != selected or "setup_model" not in st.session_state:
        st.session_state["setup_model"] = source.get("model", DEFAULT_MODEL)
        st.session_state["transcription_model"] = source.get("transcription_model", DEFAULT_AUDIO_MODEL)
        st.session_state.update({**DEFAULT_FILTERS, **source.get("filters", {})})
        st.session_state["instructions_edit"] = source["instructions"]
        st.session_state["rules_edit"] = source["rules"]
        st.session_state["version_name"] = f"{source['name']} (copy)" if selected else ""
        st.session_state["prompt_source"] = selected
    st.subheader("Model")
    model = st.selectbox("Model to evaluate", list(MODELS), format_func=MODELS.__getitem__, key="setup_model")
    st.selectbox(
        "Google AI Studio transcription model",
        list(AUDIO_MODELS),
        key="transcription_model",
        help="Audio is transcribed once per model and reused across evaluations.",
    )
    st.subheader("Filters")
    strip = st.toggle("Strip formatting", key="strip_formatting",
                      help="Remove numbering before sending and grading. Turn off to grade the original formatting.")
    narrow = st.toggle("Remove `/#*…`", key="remove_hash_marker",
                       help="Remove input tokens such as /#*abc. Keep the surrounding whitespace.")
    broad = st.toggle("Remove `/…`", key="remove_slash_marker",
                      help="Remove all slash tokens, including /xyz and /#*abc, from the model input.")
    heading = st.toggle("Remove heading (notice info)", key="remove_heading",
                        help="Grade the expected text after ‘transcript of the proceeding.’ when the marker is clear.")
    st.subheader("Prompt")
    instructions = st.text_area("Instructions", height=280, key="instructions_edit")
    rules = st.text_area("Court-reporting rules", height=280, key="rules_edit")
    with st.expander("Combined request preview"):
        st.caption("System message: instructions and rules")
        st.code(instructions + SEPARATOR + rules, language=None)
        st.caption("User message: placeholders are filled for each case at run time")
        st.code("# AI transcription reference\n[AI transcription of the case audio]\n\n"
                "# Original transcript\n[Original input text after setup filters]", language=None)
    name = st.text_input("New setup name", key="version_name")
    if st.button("Save new setup", key="save_version"):
        saved = store.save_prompt(name, instructions, rules, model=model,
                                  transcription_model=st.session_state["transcription_model"], filters={
            "strip_formatting": strip, "remove_hash_marker": narrow, "remove_slash_marker": broad,
            "remove_heading": heading})
        st.session_state["saved_setup"] = saved["id"]
        st.rerun()


def run_label(run):
    return f"{run['prompt']['name']} · {run['split']} · {run['created_at'][:16]} · {run['id'][:8]}"


def execute_with_progress(store, run, config, retry=False, failures=None):
    # Retries use the original settings, even if the current .env has changed.
    client = DeepSeekClient({**run["settings"], "api_key": config["api_key"]})
    bar = st.progress(0.0, text=f"Running {run['prompt']['name']}")
    def progress(current):
        done = sum(r["status"] in ("success", "error") for r in current["results"])
        bar.progress(done / len(current["results"]), text=f"{done}/{len(current['results'])} cases attempted")
    transcriber = GeminiTranscriber(config["gemini_api_key"]) if has_key(config["gemini_api_key"]) else None
    execute_run(store, run["id"], client, retry=retry, progress=progress,
                transcriber=transcriber, transcription_failures=failures)


def results_page(store):
    st.header("Results")
    columns = {"prompt": "Setup", "model": "Model", "audio_model": "Audio model", "grading": "Grading mode",
               "transcription_seconds": st.column_config.NumberColumn("Transcription time (s)", format="%.2f"),
               "deepseek_seconds": st.column_config.NumberColumn("DeepSeek time (s)", format="%.2f"),
               "remove_hash_marker": "Remove /#*…", "remove_slash_marker": "Remove /…",
               "remove_heading": "Remove heading (notice info)",
               "similarity": "Similarity (%)", "baseline": "Baseline (%)", "improvement": "Gain (pp)",
               "normalized_similarity": "Normalized (%)", "exact_match_rate": "Exact match (%)"}
    config = load_config(ROOT)
    client = DeepSeekClient(config)
    st.caption("Evaluate saved setups on the same excerpts and compare their scores.")
    if not client.ready:
        st.info("Add DEEPSEEK_API_KEY to evaluation/.env to enable API runs. Saved results remain available.")
    datasets, prompts = store.list("datasets"), store.list("prompts")
    dataset_map, prompt_map = {d["id"]: d for d in datasets}, {p["id"]: p for p in prompts}
    selected_dataset = record_selector("Evaluation dataset", store.root / "datasets", list(dataset_map),
                                       format_func=lambda key: label(dataset_map[key]), disabled=not datasets)
    split = st.radio("Evaluation split", ["development", "holdout"], horizontal=True)
    if split == "holdout":
        st.info("Holdout selected explicitly. Keep these results separate from routine prompt tuning.")
    selected_prompts = record_selector("Setups to run", store.root / "prompts", list(prompt_map),
                                       multiple=True, default=list(prompt_map)[:1],
                                       format_func=lambda key: label(prompt_map[key]))
    dataset = dataset_map.get(selected_dataset)
    count = sum(c["split"] == split for c in dataset["cases"]) if dataset else 0
    ready = False
    if count and selected_prompts:
        try:
            cases = [c for c in dataset["cases"] if c["split"] == split]
            counts = workload(store, cases, [prompt_map[p] for p in selected_prompts])
            st.write(f"**{counts['recordings']} recordings** need transcription · "
                     f"**{counts['requests']} new transcription requests** · "
                     f"**{counts['cached']} cached transcriptions** · "
                     f"**{counts['prompts']} editing prompt calls**")
            preflight(counts, config)
            ready = True
        except (ValueError, OSError) as exc:
            st.warning(str(exc))
    st.caption("Editing uses the original text, AI transcription reference, instructions and court-reporting rules.")
    if st.button("Start evaluation", disabled=not ready):
        preflight(workload(store, cases, [prompt_map[p] for p in selected_prompts]), config)
        batch = [create_run(store, dataset, prompt_map[p], split, client.settings) for p in selected_prompts]
        failures = {}
        for run in batch:
            execute_with_progress(store, run, config, failures=failures)
        st.rerun()

    runs = store.list("runs")
    if not runs:
        st.info("No runs yet. Choose a dataset and a saved setup, then start an evaluation.")
        return
    run_map = {r["id"]: r for r in runs}
    selected_run = record_selector("Inspect run", store.root / "runs", list(run_map),
                                   format_func=lambda key: run_label(run_map[key]))
    run = run_map[selected_run]
    filters = run["prompt"].get("filters", LEGACY_FILTERS)
    info = summary(run)
    st.caption(f"{info['model']} · {info['audio_model']} · {info['grading']} · "
               f"Remove `/#*…` {'on' if filters['remove_hash_marker'] else 'off'} · "
               f"Remove `/…` {'on' if filters['remove_slash_marker'] else 'off'} · "
               f"Remove heading {'on' if info['remove_heading'] else 'off'}")
    st.subheader("Compare compatible runs")
    compatible = [r for r in runs if comparison_key(r) == comparison_key(run) and summary(r)["complete"]]
    if not summary(run)["complete"] or len(compatible) < 2:
        st.info("To compare, choose completed runs with the same dataset snapshot, cases, and grading settings.")
    else:
        st.dataframe(sorted([summary(r) for r in compatible], key=lambda row: row["similarity"], reverse=True),
                     column_config=columns, hide_index=True)
        candidates = {r["id"]: r for r in compatible if r["id"] != run["id"]}
        candidate_id = record_selector("Compare against inspected run", store.root / "runs", list(candidates),
                                       format_func=lambda key: run_label(candidates[key]))
        comparison = compare_runs(run, candidates[candidate_id])
        st.caption("Positive change means the candidate improved over the inspected run.")
        st.dataframe(comparison, hide_index=True)
        st.download_button("Export case comparison CSV", comparison_csv(comparison), "case-comparison.csv", "text/csv")

    st.subheader("Run history")
    st.caption("Similarity is not a probability of correctness. Incomplete runs are excluded from ranking.")
    st.caption("Times total API calls across cases and retries. Cached transcription adds 0 seconds. Older timings are unavailable.")
    st.dataframe([summary(r) for r in runs], column_config=columns, hide_index=True)
    st.download_button("Export run summaries CSV", comparison_csv([summary(r) for r in runs]),
                       "run-summaries.csv", "text/csv")
    st.download_button("Export full run JSON", json.dumps(run, ensure_ascii=False, indent=2),
                       f"run-{run['id']}.json", "application/json")
    with st.expander("Saved configuration and hashes"):
        st.json({"settings": run["settings"], "filters": filters, "dataset_hash": run["dataset"]["hash"],
                 "prompt_hash": run["prompt"]["hash"], "scoring_version": run["scoring_version"]})
    remaining = sum(r["status"] != "success" for r in run["results"])
    if remaining:
        st.warning(f"{remaining} cases need retry or resume. Successful cases will be skipped.")
        st.caption("If a previous request was interrupted, its response may have been lost. Retrying can incur another API charge.")
        if st.button(f"Retry or resume {remaining} cases", disabled=not client.ready):
            preflight(retry_workload(store, run), config)
            execute_with_progress(store, run, config, retry=True, failures={})
            st.rerun()
    results = {r["case_id"]: r for r in run["results"]}
    untrimmed = [f"{r['case_id']} ({r['heading_warning']})" for r in results.values() if r.get("heading_warning")]
    if untrimmed:
        st.warning("Expected output kept in full for " + ", ".join(untrimmed))
    chosen_case = st.selectbox("Inspect case", list(results), key=f"inspect_case_{run['id']}")
    result = results[chosen_case]
    case = next(c for c in run["dataset"]["cases"] if c["id"] == chosen_case)
    if result.get("error"):
        st.error(result["error"])
    if result.get("response_warning"):
        st.warning(result["response_warning"])
    elif "finish_reason" in result:
        st.caption(f"DeepSeek finish_reason={result['finish_reason']!r}")
    if "api_response" in result:
        with st.expander("Raw DeepSeek response"):
            st.json(resolve(store.root, result["api_response"]))
    if result.get("scores"):
        settings = {key: info[key] for key in ("prompt", "model", "audio_model", "grading", "remove_hash_marker",
                                              "remove_slash_marker", "remove_heading")}
        st.dataframe([{**settings, **result["scores"]}], column_config=columns, hide_index=True)
    if "transcription" in result:
        with st.expander("AI transcription reference"):
            transcription = resolve(store.root, result["transcription"])
            st.code(transcription["text"], language=None)
            for boundary in transcription.get("boundary_flags", []):
                st.warning(f"Inspect segment boundary {boundary}: overlap could not be matched safely.")
            for warning in transcription.get("warnings", []):
                st.warning(warning)
    if "request" in result:
        with st.expander("Exact submitted messages"):
            request = resolve(store.root, result["request"])
            st.code(request["system"], language=None)
            st.code(request["user"], language=None)
    if "response" in result:
        with st.expander("Numbered transcript"):
            numbered = result.get("formatted_output")
            if numbered is None:
                numbered = formatted_transcript(result["response"])
            st.code(numbered, language=None)
            st.download_button("Download numbered transcript", numbered, f"transcript-{run['id'][:8]}.txt", "text/plain")
        graded_expected, _ = expected_for_grading(case["output"], filters)
        st.caption(f"Graded diff ({info['grading']}). · = space, → = tab, ↵ = newline.")
        st.html("<style>.transcript-diff{font:13px monospace;overflow:auto;max-height:350px;color:#18212b;background:white}"
                ".transcript-diff table{border-collapse:collapse}.transcript-diff td{padding:3px}"
                ".transcript-diff .diff_add{background:#c6f6d5}.transcript-diff .diff_sub{background:#fed7d7}"
                ".transcript-diff .diff_chg{background:#fefcbf}</style><div class='transcript-diff'>"
                + visible_diff(graded_expected,
                               grading_text(result["response"], filters["strip_formatting"])) + "</div>")
    with st.expander("Attempt history"):
        st.json(result["attempts"])
    displayed_expected, _ = expected_for_grading(case["output"], filters)
    for column, title, text in zip(st.columns(3), ("Rough input", "Expected output", "Generated output"),
                                  (grading_text(case["input"], filters["strip_formatting"]), displayed_expected,
                                   grading_text(result.get("response", "No response text available."), filters["strip_formatting"]))):
        column.markdown(f"**{title}**")
        column.code(text, language=None)



def main():
    st.set_page_config(page_title="Transcript evaluation", page_icon="◈", layout="wide")
    st.sidebar.title("Transcript evaluation")
    st.sidebar.caption("Compare evaluation setups against reviewed transcript excerpts.")
    store = Store(Path(os.environ.get("EVALUATION_DATA_DIR", str(ROOT / "data"))))
    if not store.list("prompts"):
        st.info("Create your first evaluation setup to get started.")
    page = st.sidebar.radio("Workspace", ["Datasets", "Evaluation Setup", "Results"])
    st.sidebar.caption("Local evaluation app. Data and results are stored separately from the transcript editor.")
    try:
        {"Datasets": datasets_page, "Evaluation Setup": setup_page, "Results": results_page}[page](store)
    except (ValueError, OSError, UnicodeError) as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
