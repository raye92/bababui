"""Run with: python -m streamlit run evaluation/main.py (from repo root)."""
import json
import os
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from evaluation.client import DeepSeekClient, load_config
from evaluation.core import (Store, SEPARATOR, parse_jsonl, parse_text_pairs, create_run,
                             execute_run, summary, compare_runs, comparison_key,
                             comparison_csv, visible_diff)


def label(record):
    return f"{record['name']} · {record['created_at'][:16]} · {record['id'][:8]}"


def datasets_page(store):
    st.header("Datasets")
    st.caption("Each pair contains one self-contained rough excerpt and its reviewed expected output.")
    datasets = store.list("datasets")
    if not datasets:
        st.info("No datasets yet. Import pairs or add your first pair below.")
    with st.expander("Import a dataset", expanded=not datasets):
        st.caption("JSONL: id, input, output, optional split. Text files: <id>.input.txt and <id>.output.txt.")
        with st.form("import_dataset"):
            name = st.text_input("Dataset name", key="import_name")
            mode = st.radio("Import format", ["JSONL", "Text pairs"], horizontal=True)
            uploads = st.file_uploader("Choose files", type=["jsonl", "txt"], accept_multiple_files=True)
            submitted = st.form_submit_button("Import dataset")
        if submitted:
            if not uploads:
                raise ValueError("Choose files to import.")
            if len({file.name for file in uploads}) != len(uploads):
                raise ValueError("Duplicate filenames. Each input/output filename must be unique.")
            if mode == "JSONL":
                if len(uploads) != 1:
                    raise ValueError("Choose one JSONL file per dataset.")
                cases = parse_jsonl(uploads[0].getvalue().decode("utf-8-sig"))
            else:
                cases = parse_text_pairs({file.name: file.getvalue().decode("utf-8-sig") for file in uploads})
            saved = store.save_dataset(name, cases)
            st.session_state["dataset_navigation"] = (saved["id"], cases[0]["id"])
            st.rerun()
        st.download_button("Download synthetic JSONL template", (ROOT / "fixtures/synthetic.jsonl").read_bytes(),
                           "synthetic.jsonl", "application/x-ndjson")
        st.caption("Synthetic examples demonstrate the format. They are not reviewed benchmark data.")

    options = {"new": None, **{d["id"]: d for d in datasets}}
    if "dataset_navigation" in st.session_state:
        destination, pair = st.session_state.pop("dataset_navigation")
        st.session_state["dataset_selection"] = destination
        st.session_state[f"pair_{destination}"] = pair
    selected = st.selectbox("Dataset to view or extend", list(options),
                            format_func=lambda key: "New dataset" if key == "new" else label(options[key]),
                            key="dataset_selection")
    dataset = options[selected]
    if dataset:
        st.dataframe([{"id": c["id"], "split": c["split"], "input_characters": len(c["input"]),
                       "expected_characters": len(c["output"])} for c in dataset["cases"]], hide_index=True)
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
        updated = st.form_submit_button("Update", key="update_dataset", disabled=dataset is None)
        st.divider()
        name = st.text_input("New dataset name", value=f"{dataset['name']} (copy)" if dataset else "",
                             key="manual_name" if dataset is None else f"manual_name_{suffix}")
        saved = st.form_submit_button("Save as new dataset", key="save_dataset_as_new")
    if updated or saved:
        edited = {"id": identifier, "input": rough, "output": expected, "split": split}
        cases = [edited if c["id"] == choice else c for c in existing.values()]
        if choice is None:
            cases.append(edited)
        record = store.update_dataset(selected, cases) if updated else store.save_dataset(name, cases)
        st.session_state["dataset_navigation"] = (record["id"], identifier)
        st.rerun()


def prompts_page(store):
    st.header("Prompt versions")
    st.caption("Each saved version contains both instructions and rules. Changes create a new version.")
    prompts = store.list("prompts")
    sources = {p["id"]: p for p in prompts}
    selected = st.selectbox("Copy from version", list(sources), format_func=lambda key: label(sources[key])) if sources else None
    source = sources.get(selected, {"instructions": "", "rules": ""})
    # Reset drafts only when the selected source changes; retain unsaved typing on reruns.
    if st.session_state.get("prompt_source") != selected or "instructions_edit" not in st.session_state:
        st.session_state["instructions_edit"] = source["instructions"]
        st.session_state["rules_edit"] = source["rules"]
        st.session_state["prompt_source"] = selected
    name = st.text_input("New version name", key="version_name")
    instructions = st.text_area("Instructions", height=280, key="instructions_edit")
    rules = st.text_area("Court-reporting rules", height=280, key="rules_edit")
    with st.expander("Combined system prompt preview"):
        st.code(instructions + SEPARATOR + rules, language=None)
    if st.button("Save new prompt version", key="save_version"):
        store.save_prompt(name, instructions, rules)
        st.success("I saved a new immutable prompt version.")


def run_label(run):
    return f"{run['prompt']['name']} · {run['split']} · {run['created_at'][:16]} · {run['id'][:8]}"


def execute_with_progress(store, run, config, retry=False):
    # Retries use the original settings, even if the current .env has changed.
    client = DeepSeekClient({**run["settings"], "api_key": config["api_key"]})
    bar = st.progress(0.0, text=f"Running {run['prompt']['name']}")
    def progress(current):
        done = sum(r["status"] in ("success", "error") for r in current["results"])
        bar.progress(done / len(current["results"]), text=f"{done}/{len(current['results'])} cases attempted")
    execute_run(store, run["id"], client, retry=retry, progress=progress)


def runs_page(store):
    st.header("Runs and comparisons")
    config = load_config(ROOT)
    client = DeepSeekClient(config)
    st.caption(f"Model: {client.settings['model']} · Temperature: 0 · Sequential requests")
    if not client.ready:
        st.info("Add DEEPSEEK_API_KEY to evaluation/.env to enable API runs. Saved results remain available.")
    datasets, prompts = store.list("datasets"), store.list("prompts")
    dataset_map, prompt_map = {d["id"]: d for d in datasets}, {p["id"]: p for p in prompts}
    selected_dataset = st.selectbox("Evaluation dataset", list(dataset_map),
                                   format_func=lambda key: label(dataset_map[key]), disabled=not datasets)
    split = st.radio("Evaluation split", ["development", "holdout"], horizontal=True)
    if split == "holdout":
        st.info("Holdout selected explicitly. Keep these results separate from routine prompt tuning.")
    selected_prompts = st.multiselect("Prompt versions to run", list(prompt_map),
                                     default=list(prompt_map)[:1], format_func=lambda key: label(prompt_map[key]))
    dataset = dataset_map.get(selected_dataset)
    count = sum(c["split"] == split for c in dataset["cases"]) if dataset else 0
    st.write(f"{count} cases × {len(selected_prompts)} prompt versions = **{count * len(selected_prompts)} API calls**")
    st.caption("Starting sends the selected rough excerpts and prompts to the configured DeepSeek endpoint.")
    if st.button("Start evaluation", disabled=not (client.ready and count and selected_prompts)):
        # Persist the whole batch before starting so interrupted versions remain resumable.
        batch = [create_run(store, dataset, prompt_map[p], split, client.settings) for p in selected_prompts]
        for run in batch:
            execute_with_progress(store, run, config)
        st.rerun()

    runs = store.list("runs")
    if not runs:
        st.info("No runs yet. Import a dataset, save a prompt version, and start an evaluation.")
        return
    run_map = {r["id"]: r for r in runs}
    selected_run = st.selectbox("Inspect run", list(run_map), format_func=lambda key: run_label(run_map[key]))
    run = run_map[selected_run]
    st.subheader("Compare compatible runs")
    compatible = [r for r in runs if comparison_key(r) == comparison_key(run) and summary(r)["complete"]]
    if not summary(run)["complete"] or len(compatible) < 2:
        st.info("Select a complete run with another complete run on the same dataset snapshot and cases to compare.")
    else:
        st.dataframe(sorted([summary(r) for r in compatible], key=lambda row: row["similarity"], reverse=True), hide_index=True)
        candidates = {r["id"]: r for r in compatible if r["id"] != run["id"]}
        candidate_id = st.selectbox("Compare against inspected run", list(candidates),
                                   format_func=lambda key: run_label(candidates[key]))
        comparison = compare_runs(run, candidates[candidate_id])
        st.caption("Positive change means the candidate improved over the inspected run.")
        st.dataframe(comparison, hide_index=True)
        st.download_button("Export case comparison CSV", comparison_csv(comparison), "case-comparison.csv", "text/csv")

    st.subheader("Run history")
    st.caption("Similarity is not a probability of correctness. Incomplete runs are excluded from ranking.")
    st.dataframe([summary(r) for r in runs], hide_index=True)
    st.download_button("Export run summaries CSV", comparison_csv([summary(r) for r in runs]),
                       "run-summaries.csv", "text/csv")
    st.download_button("Export full run JSON", json.dumps(run, ensure_ascii=False, indent=2),
                       f"run-{run['id']}.json", "application/json")
    with st.expander("Saved configuration and hashes"):
        st.json({"settings": run["settings"], "dataset_hash": run["dataset"]["hash"],
                 "prompt_hash": run["prompt"]["hash"], "scoring_version": run["scoring_version"]})
    remaining = sum(r["status"] != "success" for r in run["results"])
    if remaining:
        st.warning(f"{remaining} cases need retry or resume. Successful cases will be skipped.")
        st.caption("If a previous request was interrupted, its response may have been lost. Retrying can incur another API charge.")
        if st.button(f"Retry or resume {remaining} cases", disabled=not client.ready):
            execute_with_progress(store, run, config, retry=True)
            st.rerun()
    results = {r["case_id"]: r for r in run["results"]}
    chosen_case = st.selectbox("Inspect case", list(results), key=f"inspect_case_{run['id']}")
    result = results[chosen_case]
    case = next(c for c in run["dataset"]["cases"] if c["id"] == chosen_case)
    if result.get("error"):
        st.error(result["error"])
    if result.get("scores"):
        st.dataframe([result["scores"]], hide_index=True)
    for column, title, text in zip(st.columns(3), ("Rough input", "Expected output", "Generated output"),
                                  (case["input"], case["output"], result.get("response", "No successful response yet."))):
        column.markdown(f"**{title}**")
        column.code(text, language=None)
    if "response" in result:
        st.caption("Diff: · = space, → = tab, ↵ = newline. Red marks removed text; green marks added text.")
        st.html("<style>.transcript-diff{font:13px monospace;overflow:auto;max-height:350px;color:#18212b;background:white}"
                ".transcript-diff table{border-collapse:collapse}.transcript-diff td{padding:3px}"
                ".transcript-diff .diff_add{background:#c6f6d5}.transcript-diff .diff_sub{background:#fed7d7}"
                ".transcript-diff .diff_chg{background:#fefcbf}</style><div class='transcript-diff'>"
                + visible_diff(case["output"], result["response"]) + "</div>")
    with st.expander("Attempt history"):
        st.json(result["attempts"])



def main():
    st.set_page_config(page_title="Transcript evaluation", page_icon="◈", layout="wide")
    st.title("Transcript evaluation")
    st.caption("Compare prompt versions against reviewed transcript excerpts.")
    store = Store(Path(os.environ.get("EVALUATION_DATA_DIR", str(ROOT / "data"))))
    if not store.list("prompts"):
        source = ROOT.parent / "app" / "src"
        if (source / "AI Quality Analysis Prompt.md").exists() and (source / "courtreportingrules.md").exists():
            store.save_prompt("Editor baseline", (source / "AI Quality Analysis Prompt.md").read_text(encoding="utf-8"),
                              (source / "courtreportingrules.md").read_text(encoding="utf-8"))
        else:
            st.info("Editor prompt documents were not found. Create your first prompt version manually.")
    page = st.sidebar.radio("Workspace", ["Datasets", "Prompt versions", "Runs and comparisons"])
    st.sidebar.caption("Local evaluation app. Data and results are stored separately from the transcript editor.")
    try:
        {"Datasets": datasets_page, "Prompt versions": prompts_page, "Runs and comparisons": runs_page}[page](store)
    except (ValueError, OSError, UnicodeError) as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
