from evaluation.tests.audio_helpers import save_dataset, update_dataset, original as extract_original, AUDIO, seed
from pathlib import Path

from streamlit.testing.v1 import AppTest

from evaluation.core import Store, create_run, execute_run

MAIN = Path(__file__).resolve().parents[1] / "main.py"


def start(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALUATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    return AppTest.from_file(str(MAIN), default_timeout=20).run()


def test_empty_app_and_no_automatic_calls(tmp_path, monkeypatch):
    app = start(tmp_path, monkeypatch)
    assert not app.exception
    assert any("No datasets" in message.value for message in app.info)
    app.sidebar.radio[0].set_value("Results").run()
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
    assert any("WAV is required" in e.value for e in app.error)
    assert Store(tmp_path).list("datasets") == []
    from evaluation.tests.audio_helpers import WAV
    app.file_uploader(key="audio_new").upload("one.wav", WAV, "audio/wav")
    app.button(key="save_dataset_as_new").click().run()
    assert not app.error
    assert Store(tmp_path).list("datasets")[0]["cases"][0]["output"] == "Hello."
    app.sidebar.radio[0].set_value("Evaluation Setup").run()
    assert app.selectbox(key="setup_model").value == "deepseek-v4-pro"
    assert app.toggle(key="remove_heading").value is True
    app.selectbox(key="setup_model").set_value("deepseek-flash")
    app.toggle(key="remove_slash_marker").set_value(True)
    app.toggle(key="remove_heading").set_value(False)
    app.text_input(key="version_name").set_value("My v2")
    app.text_area(key="instructions_edit").set_value("Edit punctuation only.")
    app.button(key="save_version").click().run()
    assert not app.exception
    setups = Store(tmp_path).list("prompts")
    assert len(setups) == 2
    saved = setups[0]
    assert saved["model"] == "deepseek-flash"
    assert saved["filters"] == {"strip_formatting": True, "remove_hash_marker": True, "remove_slash_marker": True,
                                "remove_heading": False}
    app.selectbox(key="copy_setup").set_value(saved["id"]).run()
    assert app.selectbox(key="setup_model").value == "deepseek-flash"
    assert app.toggle(key="remove_slash_marker").value
    assert app.toggle(key="remove_heading").value is False
    assert app.text_area(key="instructions_edit").value == "Edit punctuation only."
    app.text_input(key="version_name").set_value("Strict grading")
    app.toggle(key="strip_formatting").set_value(False)
    app.button(key="save_version").click().run()
    copy = Store(tmp_path).list("prompts")[0]
    assert copy["id"] != saved["id"] and copy["model"] == saved["model"]
    assert copy["filters"] == {**saved["filters"], "strip_formatting": False}
    assert Store(tmp_path).get("prompts", saved["id"])["filters"]["strip_formatting"] is True


def test_saved_runs_display_and_compare_without_requests(tmp_path, monkeypatch):
    store = Store(tmp_path)
    dataset = save_dataset(store, "Synthetic", [{"id": "x", "input": "hi", "output": "Hi."}])
    class Fake:
        def complete(self, text, system_prompt):
            return "Hi." if system_prompt.startswith("Correct") else text
    for name in ("Correct", "Unchanged"):
        prompt = store.save_prompt(name, name, "Synthetic rules")
        run = create_run(store, dataset, prompt, "development", {"model": "fake"})
        execute_run(store, run["id"], Fake())
    app = start(tmp_path, monkeypatch)
    app.sidebar.radio[0].set_value("Results").run()
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
    save_dataset(store, "Synthetic", [{"id": "x", "input": "hi", "output": "Hi."}])
    store.save_prompt("v1", "Correct", "Rules", model="deepseek-flash")
    calls = []
    def fake_complete(self, text, prompt):
        calls.append((extract_original(text), self.settings["model"]))
        return "Hi."
    monkeypatch.setattr(DeepSeekClient, "complete", fake_complete)
    app = start(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    app.sidebar.radio[0].set_value("Results").run()
    next(b for b in app.button if b.label == "Start evaluation").click().run()
    assert not app.exception
    assert calls == [("hi", "deepseek-flash")]
    assert store.list("runs")[0]["results"][0]["scores"]["similarity"] == 100
    app.run()
    assert calls == [("hi", "deepseek-flash")]
    assert not app.exception
    assert len(store.list("runs")) == 1


def test_upload_import_and_folder_import(tmp_path, monkeypatch):
    from evaluation.tests.audio_helpers import WAV
    source = tmp_path / "source"
    source.mkdir()
    for name, data in {"x.txt": b"hello", "x-scoped.txt": b"Hello.", "x.wav": WAV}.items():
        (source / name).write_bytes(data)
    app = start(tmp_path / "data", monkeypatch)
    app.text_input(key="import_name").set_value("Uploaded")
    uploads = next(u for u in app.file_uploader if u.label == "Choose text and WAV files")
    for path in source.iterdir():
        uploads.upload(path.name, path.read_bytes())
    next(b for b in app.button if b.label == "Import dataset").click().run()
    assert not app.error and not app.exception
    next(r for r in app.radio if r.label == "Import source").set_value("Local folder").run()
    app.text_input(key="import_name").set_value("Folder")
    next(t for t in app.text_input if t.label == "Local folder path").set_value(str(source))
    next(b for b in app.button if b.label == "Import dataset").click().run()
    assert not app.error and not app.exception
    records = Store(tmp_path / "data").list("datasets")
    assert len(records) == 2 and records[0]["cases"] == records[1]["cases"]


def test_uncached_counts_and_gemini_key_gate(tmp_path, monkeypatch):
    store = Store(tmp_path)
    dataset = save_dataset(store, "Test", [{"id": "x", "input": "hi", "output": "Hi"}])
    store.save_prompt("One", "Edit", "Rules")
    cache = store.root / "transcriptions" / "gemini-3.5-transcribe" / dataset["cases"][0]["audio"]["sha256"] / "complete.json"
    cache.unlink()
    app = start(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    app.sidebar.radio[0].set_value("Results").run()
    assert any("1 new transcription requests" in m.value for m in app.markdown)
    assert any("GEMINI_API_KEY" in w.value for w in app.warning)
    assert next(b for b in app.button if b.label == "Start evaluation").disabled
    assert not store.list("runs")


def test_manual_invalid_name_does_not_publish_audio(tmp_path, monkeypatch):
    from evaluation.tests.audio_helpers import WAV
    app = start(tmp_path, monkeypatch)
    app.text_input(key="case_id_new").set_value("x")
    app.text_area(key="input_new").set_value("hello")
    app.text_area(key="output_new").set_value("Hello.")
    app.file_uploader(key="audio_new").upload("x.wav", WAV, "audio/wav")
    app.button(key="save_dataset_as_new").click().run()
    assert app.error and not (tmp_path / "audio").exists()


def test_dataset_update_and_save_as_new(tmp_path, monkeypatch):
    store = Store(tmp_path)
    original = save_dataset(store, "Original", [{"id": "one", "input": "hi", "output": "Hi."}])
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


def test_retry_uses_saved_model_filters_and_dataset(tmp_path, monkeypatch):
    from evaluation.client import DeepSeekClient

    store = Store(tmp_path)
    case = {"id": "x", "input": "          1    /#*old say /xyz", "output": "          1    Say."}
    dataset = save_dataset(store, "Retry", [case])
    setup = store.save_prompt("Flash", "Correct", "Rules", model="deepseek-flash",
                              filters={"remove_slash_marker": True})
    run = create_run(store, dataset, setup, "development", {})
    class Unavailable:
        def complete(self, *args):
            raise OSError("Try again")
    execute_run(store, run["id"], Unavailable())
    update_dataset(store, dataset["id"], [{**case, "input": "Later edit"}])
    store.save_prompt("Different setup", "Leave unchanged", "Rules", filters={"strip_formatting": False})
    calls = []
    def complete(self, text, prompt):
        calls.append((self.settings["model"], extract_original(text), prompt))
        return "Say."
    monkeypatch.setattr(DeepSeekClient, "complete", complete)
    app = start(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "another-model")
    app.sidebar.radio[0].set_value("Results").run()
    next(b for b in app.button if b.label.startswith("Retry or resume")).click().run()
    assert not app.exception
    assert len(calls) == 1 and calls[0][:2] == ("deepseek-flash", " say ")
    assert calls[0][2].startswith(setup["system_prompt"])
    result = store.get("runs", run["id"])["results"][0]
    assert result["scores"]["exact"]
    assert [a["status"] for a in result["attempts"]] == ["error", "success"]
