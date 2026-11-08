from evaluation.tests.audio_helpers import save_dataset, update_dataset, original as extract_original, AUDIO, seed
import json

import pytest

from evaluation.core import (
    parse_jsonl, parse_text_pairs, validate_cases, score, Store,
    create_run, execute_run, summary, compare_runs, comparison_csv, visible_diff,
)


def cases():
    return [{"id": "one", "input": "hello", "output": "Hello.", "split": "development", "audio": AUDIO},
            {"id": "two", "input": "yes", "output": "Yes.", "split": "development", "audio": AUDIO}]


def test_import_preserves_unicode_and_whitespace():
    raw = json.dumps({"id": "x", "input": "  café\r\n", "output": "  Café.\n"})
    assert parse_jsonl(raw)[0] == {
        "id": "x", "input": "  café\r\n", "output": "  Café.\n", "split": "development"}
    assert parse_text_pairs({"x.txt": "  café\r\n", "x_scoped.txt": "  Café.\n"}) == parse_jsonl(raw)


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
        parse_text_pairs({"x.txt": "hi"})
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


@pytest.mark.parametrize(("output", "body", "warning"), [
    ("Notice\r\n    9    transcript of the proceeding.\r\n\r\n   10\r\n\r\n   11    EXAMINATION\r\n",
     "   11    EXAMINATION\r\n", None),
    ("Notice\n 9\t Transcript   of the proceeding.\n10\n11    THE COURT: Proceed.\n12    EXAMINATION",
     "11    THE COURT: Proceed.\n12    EXAMINATION", None),
    ("Notice\nTRANSCRIPT OF THE PROCEEDING.\n\n42\n", "42\n", None),
    ("They prepared a transcript of the proceeding.\nBody", None, "missing"),
    ("transcript of the proceeding.\nBody\ntranscript of the proceeding.\nEnd", None, "repeated"),
    (" 9    transcript of the proceeding.\n 10\n", None, "no proceeding text"),
])
def test_expected_heading_detection(output, body, warning):
    from evaluation.setups import expected_for_grading

    expected, notice = expected_for_grading(output, {"strip_formatting": False, "remove_heading": True})
    assert expected == (output if body is None else body)
    if warning:
        assert warning in notice
    else:
        assert notice is None


def test_heading_filter_scores_full_reply_and_flags_untrimmed_cases(tmp_path):
    store = Store(tmp_path)
    output = "Notice\n    9    transcript of the proceeding.\n   10\n   11    Hello."
    dataset = save_dataset(store, "Heading", [
        {"id": "one", "input": "Hello.", "output": output},
        {"id": "two", "input": "Yes.", "output": "Yes."},
    ])
    prompt = store.save_prompt("Trim", "Edit", "Rules", filters={"remove_heading": True})
    run = create_run(store, dataset, prompt, "development", {})

    class Reply:
        def complete(self, text, system_prompt):
            assert "omit prefatory notice information" in system_prompt
            return "Notice\nHello." if extract_original(text) == "Hello." else "Yes."

    graded = execute_run(store, run["id"], Reply())
    trimmed, flagged = graded["results"]
    assert trimmed["scores"] == score("Hello.", "Notice\nHello.", "Hello.")
    assert flagged["scores"]["exact"] and "missing" in flagged["heading_warning"]
    assert graded["dataset"]["cases"][0]["output"] == output
    old = create_run(store, dataset, store.save_prompt("Old", "Edit", "Rules"), "development", {})
    old["prompt"]["filters"].pop("remove_heading")
    with pytest.raises(ValueError, match="heading filter"):
        compare_runs(old, graded)
    assert score("x", "", "abc")["similarity"] == 0
    assert score("x", "", "")["similarity"] == 100


def setup_run(tmp_path):
    store = Store(tmp_path)
    dataset = save_dataset(store, "Test", cases())
    prompt = store.save_prompt("v1", "Edit", "Rules")
    run = create_run(store, dataset, prompt, "development", {"model": "fake", "temperature": 0})
    return store, dataset, prompt, run


class FakeClient:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def complete(self, text, system_prompt):
        text = extract_original(text)
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
    newer = save_dataset(store, "../../outside", cases())
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
    dataset = save_dataset(store, "Held", [dict(cases()[0], split="holdout")])
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
            if extract_original(text) == "yes":
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
    updated = update_dataset(store, dataset["id"], changed)
    assert updated["id"] == dataset["id"]
    assert updated["hash"] != dataset["hash"]
    assert len(store.list("datasets")) == 1
    assert store.get("runs", run["id"])["dataset"]["cases"][0]["output"] == "Hello."
    with pytest.raises(ValueError):
        update_dataset(store, dataset["id"], [])
    assert store.get("datasets", dataset["id"])["cases"] == changed


@pytest.mark.parametrize(("narrow", "broad", "expected"), [
    (False, False, "A /#*abc\tkeep  /xyz\nB"),
    (True, False, "A \tkeep  /xyz\nB"),
    (False, True, "A \tkeep  \nB"),
    (True, True, "A \tkeep  \nB"),
])
def test_marker_filters_only_change_the_request(tmp_path, narrow, broad, expected):
    store = Store(tmp_path)
    original = "A /#*abc\tkeep  /xyz\nB"
    dataset = save_dataset(store, "Markers", [{"id": "x", "input": original, "output": original}])
    setup = store.save_prompt("Filters", "Edit", "Rules", filters={
        "strip_formatting": False, "remove_hash_marker": narrow, "remove_slash_marker": broad})
    run = create_run(store, dataset, setup, "development", {})
    class Echo:
        def complete(self, text, prompt):
            assert extract_original(text) == expected
            return extract_original(text)
    result = execute_run(store, run["id"], Echo())["results"][0]
    assert result["response"] == expected
    assert result["scores"] == score(original, expected, original)


@pytest.mark.parametrize("strip", [True, False])
def test_grading_precedes_numbering_and_covers_multiple_pages(tmp_path, strip):
    from transcript_formatting import TranscriptFormatter

    formatter = TranscriptFormatter()
    plain = "\n".join(f"    Q    Line {i}." for i in range(1, 28))
    numbered, pages = formatter.apply_formatting(plain)
    assert pages == 2 and "\f" in numbered
    store = Store(tmp_path)
    dataset = save_dataset(store, "Numbered", [{"id": "x", "input": numbered, "output": numbered}])
    setup = store.save_prompt("Numbering", "Edit", "Rules", filters={"strip_formatting": strip})
    run = create_run(store, dataset, setup, "development", {})
    class PlainReply:
        def complete(self, text, prompt):
            assert extract_original(text) == (plain if strip else numbered)
            return plain
    saved = execute_run(store, run["id"], PlainReply())
    result = saved["results"][0]
    assert result["status"] == "success"
    assert result["response"] == plain and result["formatted_output"] == numbered
    assert result["scores"]["exact"] is strip
    assert (result["scores"]["similarity"] == 100) is strip
    assert result["scores"]["baseline"] == 100


def test_legacy_history_and_grading_mode_compatibility(tmp_path):
    from copy import deepcopy

    store, dataset, _, _ = setup_run(tmp_path)
    setup = store.save_prompt("Strict", "Edit", "Rules",
                              filters={"strip_formatting": False, "remove_heading": False})
    strict = create_run(store, dataset, setup, "development", {})
    strict = execute_run(store, strict["id"], FakeClient())
    old = deepcopy(strict)
    old["prompt"].pop("filters")
    old["prompt"].pop("model")
    old["settings"] = {"model": "deepseek-chat"}
    old["results"][0]["scores"]["similarity"] = 42
    assert summary(old)["grading"] == "Original formatting"
    assert summary(old)["similarity"] == 71
    assert compare_runs(old, strict)[0]["change_pp"] == 58
    plain_setup = store.save_prompt("Plain", "Edit", "Rules")
    plain = create_run(store, dataset, plain_setup, "development", {})
    plain = execute_run(store, plain["id"], FakeClient())
    with pytest.raises(ValueError, match="grading mode"):
        compare_runs(old, plain)


def test_filters_preserve_whitespace_and_handle_short_tokens():
    from evaluation.setups import DEFAULT_FILTERS, model_input

    text = "Q /#*\t/#*a / /x\nA"
    assert model_input(text, DEFAULT_FILTERS) == "Q /#*\t / /x\nA"
    broad = {**DEFAULT_FILTERS, "remove_hash_marker": False, "remove_slash_marker": True}
    assert model_input("Q /#*\t/#*a / /x\nA/abc", broad) == "Q \t / \nA"


def test_plain_numeric_answers_and_addresses_survive_grading_and_export():
    from evaluation.setups import formatted_transcript, grading_text

    answer = "Q How many?\n42\n\n1821    Main Street"
    stripped = "Q How many?\n42\n1821    Main Street"
    assert grading_text(answer, True) == stripped
    missing_number = answer.replace("42", "")
    assert not score(answer, grading_text(missing_number, True), grading_text(answer, True))["exact"]
    numbered = formatted_transcript(answer)
    assert "          2    42\n" in numbered
    assert "          3    1821    Main Street\n" in numbered
    assert grading_text(numbered, True) == grading_text("\n\n" + answer + "\n", True) == stripped


@pytest.mark.parametrize("length", [25, 26, 50])
def test_numbered_export_only_breaks_between_pages(length):
    from transcript_formatting import TranscriptFormatter

    formatter = TranscriptFormatter()
    plain = "\n".join(f"    Q    Line {n}." for n in range(length))
    numbered, pages = formatter.apply_formatting(plain)
    assert pages == (length + 24) // 25
    assert numbered.count("\f") == pages - 1
    assert numbered.endswith(f"{pages:>72}")
    assert formatter.strip_formatting(numbered) == plain
