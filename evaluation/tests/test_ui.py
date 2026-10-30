from pathlib import Path

from streamlit.testing.v1 import AppTest

from evaluation.core import Store, create_run, execute_run

MAIN = Path(__file__).resolve().parents[1] / "main.py"


def start(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALUATION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    return AppTest.from_file(str(MAIN), default_timeout=20).run()


def test_empty_app_and_no_automatic_calls(tmp_path, monkeypatch):
    app = start(tmp_path, monkeypatch)
    assert not app.exception
    assert any("No datasets" in message.value for message in app.info)
    app.sidebar.radio[0].set_value("Runs and comparisons").run()
    assert not app.exception
    assert next(b for b in app.button if b.label == "Start evaluation").disabled
    assert Store(tmp_path).list("runs") == []


def test_manual_pair_and_prompt_version(tmp_path, monkeypatch):
    app = start(tmp_path, monkeypatch)
    app.text_input(key="manual_name").set_value("My dataset")
    app.text_input(key="case_id_new").set_value("one")
    app.text_area(key="input_new").set_value("hello")
    app.text_area(key="output_new").set_value("Hello.")
    app.button(key="save_dataset_as_new").click().run()
    assert not app.exception
    assert Store(tmp_path).list("datasets")[0]["cases"][0]["output"] == "Hello."
    app.sidebar.radio[0].set_value("Prompt versions").run()
    app.text_input(key="version_name").set_value("My v2")
    app.text_area(key="instructions_edit").set_value("Edit punctuation only.")
    app.button(key="save_version").click().run()
    assert not app.exception
    assert len(Store(tmp_path).list("prompts")) == 2


def test_saved_runs_display_and_compare_without_requests(tmp_path, monkeypatch):
    store = Store(tmp_path)
    dataset = store.save_dataset("Synthetic", [{"id": "x", "input": "hi", "output": "Hi."}])
    class Fake:
        def complete(self, text, system_prompt):
            return "Hi." if system_prompt.startswith("Correct") else text
    for name in ("Correct", "Unchanged"):
        prompt = store.save_prompt(name, name, "Synthetic rules")
        run = create_run(store, dataset, prompt, "development", {"model": "fake"})
        execute_run(store, run["id"], Fake())
    app = start(tmp_path, monkeypatch)
    app.sidebar.radio[0].set_value("Runs and comparisons").run()
    assert not app.exception
    assert len(app.dataframe) >= 2
    assert [heading.value for heading in app.subheader] == ["Compare compatible runs", "Run history"]
    assert app.expander[-1].label == "Attempt history"
    assert len(Store(tmp_path).list("runs")) == 2
    app.run()
    assert not app.exception
    assert len(Store(tmp_path).list("runs")) == 2


def test_start_and_rerender_do_not_duplicate_calls(tmp_path, monkeypatch):
    from evaluation.client import DeepSeekClient
    store = Store(tmp_path)
    store.save_dataset("Synthetic", [{"id": "x", "input": "hi", "output": "Hi."}])
    store.save_prompt("v1", "Correct", "Rules")
    calls = []
    def fake_complete(self, text, prompt):
        calls.append(text)
        return "Hi."
    monkeypatch.setattr(DeepSeekClient, "complete", fake_complete)
    app = start(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    app.sidebar.radio[0].set_value("Runs and comparisons").run()
    next(b for b in app.button if b.label == "Start evaluation").click().run()
    assert not app.exception
    assert calls == ["hi"]
    assert store.list("runs")[0]["results"][0]["scores"]["similarity"] == 100
    app.run()
    assert calls == ["hi"]
    assert not app.exception
    assert len(store.list("runs")) == 1


def test_dataset_update_and_save_as_new(tmp_path, monkeypatch):
    store = Store(tmp_path)
    original = store.save_dataset("Original", [{"id": "one", "input": "hi", "output": "Hi."}])
    app = start(tmp_path, monkeypatch)
    app.selectbox(key="dataset_selection").set_value(original["id"]).run()
    app.selectbox(key=f"pair_{original['id']}").set_value("one").run()
    next(a for a in app.text_area if a.label == "Expected output").set_value("Hello.")
    app.button(key="update_dataset").click().run()
    assert not app.exception
    assert len(store.list("datasets")) == 1
    assert store.get("datasets", original["id"])["cases"][0]["output"] == "Hello."
    assert app.selectbox(key="dataset_selection").value == original["id"]
    next(a for a in app.text_area if a.label == "Expected output").set_value("Hello again.")
    next(t for t in app.text_input if t.label == "New dataset name").set_value("Copy")
    app.button(key="save_dataset_as_new").click().run()
    assert not app.exception
    assert len(store.list("datasets")) == 2
    assert store.get("datasets", original["id"])["cases"][0]["output"] == "Hello."
    copied = next(d for d in store.list("datasets") if d["id"] != original["id"])
    assert copied["cases"][0]["output"] == "Hello again."
    assert app.selectbox(key="dataset_selection").value == copied["id"]
