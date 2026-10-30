import json

import pytest

from evaluation.core import (
    parse_jsonl, parse_text_pairs, validate_cases, score, Store,
    create_run, execute_run, summary, compare_runs, comparison_csv, visible_diff,
)


def cases():
    return [{"id": "one", "input": "hello", "output": "Hello.", "split": "development"},
            {"id": "two", "input": "yes", "output": "Yes.", "split": "development"}]


def test_import_preserves_unicode_and_whitespace():
    raw = json.dumps({"id": "x", "input": "  café\r\n", "output": "  Café.\n"})
    assert parse_jsonl(raw)[0] == {
        "id": "x", "input": "  café\r\n", "output": "  Café.\n", "split": "development"}
    assert parse_text_pairs({"x.input.txt": "  café\r\n", "x.output.txt": "  Café.\n"}) == parse_jsonl(raw)


@pytest.mark.parametrize("record", [
    {"id": "x", "input": " ", "output": "ok"},
    {"id": "x", "input": 12, "output": "ok"},
    {"id": "x", "input": "ok", "output": "x\x00"},
    {"id": "x", "input": "ok", "output": "ok", "split": "test"},
    {"input": "ok", "output": "ok"},
])
def test_invalid_cases_rejected(record):
    with pytest.raises(ValueError):
        validate_cases([record])


def test_duplicate_and_unmatched_imports_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        validate_cases(cases() + cases())
    with pytest.raises(ValueError, match="partner"):
        parse_text_pairs({"x.input.txt": "hi"})
    with pytest.raises(ValueError, match="line 1"):
        parse_jsonl("{bad}")
    with pytest.raises(ValueError):
        parse_jsonl("[]")


def test_scores_count_formatting_and_baseline():
    result = score("abc", "ab", "abc")
    assert result["similarity"] == pytest.approx(200 / 3)
    assert result["baseline"] == 100
    assert result["improvement"] == pytest.approx(-100 / 3)
    assert not result["exact"]
    assert score("a\r\nb", "a\nb", "a\nb")["exact"]
    assert score("x", "  Hi.\n", "Hi.")["normalized_similarity"] == 100
    assert score("x", "  Hi.\n", "Hi.")["similarity"] == 50
    assert score("x", "", "abc")["similarity"] == 0
    assert score("x", "", "")["similarity"] == 100


def setup_run(tmp_path):
    store = Store(tmp_path)
    dataset = store.save_dataset("Test", cases())
    prompt = store.save_prompt("v1", "Edit", "Rules")
    run = create_run(store, dataset, prompt, "development", {"model": "fake", "temperature": 0})
    return store, dataset, prompt, run


class FakeClient:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def complete(self, text, system_prompt):
        self.calls.append(text)
        if self.fail and text == "yes":
            raise RuntimeError("Unavailable")
        return {"hello": "Hello.", "yes": "Yes."}[text]


def test_snapshots_are_immutable_and_paths_are_generated(tmp_path):
    store, dataset, prompt, run = setup_run(tmp_path)
    dataset["cases"][0]["input"] = "changed"
    prompt["instructions"] = "changed"
    saved = store.get("runs", run["id"])
    assert saved["dataset"]["cases"][0]["input"] == "hello"
    assert saved["prompt"]["instructions"] == "Edit"
    newer = store.save_dataset("../../outside", cases())
    assert newer["id"] != dataset["id"]
    assert store.get("datasets", dataset["id"])["cases"][0]["input"] == "hello"
    with pytest.raises(ValueError):
        store.get("runs", "../outside")


def test_run_persistence_failures_retry_and_no_duplicate_calls(tmp_path):
    store, _, _, run = setup_run(tmp_path)
    client = FakeClient(fail=True)
    execute_run(store, run["id"], client)
    saved = store.get("runs", run["id"])
    assert [r["status"] for r in saved["results"]] == ["success", "error"]
    assert saved["results"][0]["response"] == "Hello."
    assert summary(saved)["similarity"] is None
    execute_run(store, run["id"], client)
    assert len(client.calls) == 2
    client.fail = False
    execute_run(store, run["id"], client, retry=True)
    assert client.calls == ["hello", "yes", "yes"]
    saved = store.get("runs", run["id"])
    assert summary(saved)["similarity"] == 100
    assert summary(saved)["exact_match_rate"] == 100
    assert len(saved["results"][1]["attempts"]) == 2


def test_comparisons_and_exports(tmp_path):
    store, dataset, prompt, first = setup_run(tmp_path)
    execute_run(store, first["id"], FakeClient())
    second = create_run(store, dataset, prompt, "development", {"model": "fake"})
    execute_run(store, second["id"], FakeClient())
    first, second = [store.get("runs", x["id"]) for x in [first, second]]
    rows = compare_runs(first, second)
    assert len(rows) == 2 and rows[0]["change_pp"] == 0
    assert "change_pp" in comparison_csv(rows)
    assert "one" in comparison_csv(rows)
    second["scoring_version"] = "different"
    with pytest.raises(ValueError, match="compatible"):
        compare_runs(first, second)
    second["scoring_version"] = first["scoring_version"]
    second["dataset"]["cases"][0]["output"] = "changed"
    with pytest.raises(ValueError, match="compatible"):
        compare_runs(first, second)


def test_holdout_requires_selection(tmp_path):
    store = Store(tmp_path)
    dataset = store.save_dataset("Held", [dict(cases()[0], split="holdout")])
    prompt = store.save_prompt("v1", "Edit", "Rules")
    with pytest.raises(ValueError, match="No cases"):
        create_run(store, dataset, prompt, "development", {})


def test_diff_escapes_html_and_shows_whitespace():
    rendered = visible_diff(" <script>\n", "x\t")
    assert "<script>" not in rendered
    assert "·" in rendered and "↵" in rendered and "→" in rendered


def test_run_lock_prevents_concurrent_execution(tmp_path):
    store, _, _, run = setup_run(tmp_path)
    client = FakeClient()
    with store.run_lock(run["id"]):
        with pytest.raises(ValueError, match="already executing"):
            execute_run(store, run["id"], client)
    assert client.calls == []
    assert store.get("runs", run["id"])["results"][0]["status"] == "pending"
    execute_run(store, run["id"], client)
    assert summary(store.get("runs", run["id"]))["complete"]


def test_interrupted_request_is_only_resumed_explicitly(tmp_path):
    store, _, _, run = setup_run(tmp_path)
    class Interrupted:
        def complete(self, *args):
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        execute_run(store, run["id"], Interrupted())
    saved = store.get("runs", run["id"])
    assert saved["results"][0]["status"] == "running"
    assert not summary(saved)["complete"]
    client = FakeClient()
    execute_run(store, run["id"], client, retry=True)
    assert summary(store.get("runs", run["id"]))["complete"]
    assert client.calls == ["hello", "yes"]


def test_completed_case_is_saved_before_next_request(tmp_path):
    store, _, _, run = setup_run(tmp_path)
    class Inspecting(FakeClient):
        def complete(self, text, system_prompt):
            if text == "yes":
                saved = store.get("runs", run["id"])
                assert saved["results"][0]["response"] == "Hello."
                assert saved["results"][1]["status"] == "running"
            return super().complete(text, system_prompt)
    execute_run(store, run["id"], Inspecting())
    assert summary(store.get("runs", run["id"]))["complete"]


def test_prompt_overwrite_is_rejected(tmp_path):
    store, _, prompt, _ = setup_run(tmp_path)
    prompt["instructions"] = "overwrite"
    with pytest.raises(ValueError, match="cannot be overwritten"):
        store.write("prompts", prompt)
    assert store.get("prompts", prompt["id"])["instructions"] == "Edit"


def test_csv_formula_injection_is_escaped():
    assert "'=SUM(1)" in comparison_csv([{"case_id": "=SUM(1)", "change_pp": -1.5}])
    assert "-1.5" in comparison_csv([{"case_id": "x", "change_pp": -1.5}])


def test_dataset_update_preserves_saved_run_snapshot(tmp_path):
    store, dataset, _, run = setup_run(tmp_path)
    changed = cases()
    changed[0]["output"] = "Hello again."
    updated = store.update_dataset(dataset["id"], changed)
    assert updated["id"] == dataset["id"]
    assert updated["hash"] != dataset["hash"]
    assert len(store.list("datasets")) == 1
    assert store.get("runs", run["id"])["dataset"]["cases"][0]["output"] == "Hello."
    with pytest.raises(ValueError):
        store.update_dataset(dataset["id"], [])
    assert store.get("datasets", dataset["id"])["cases"] == changed
