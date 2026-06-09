from pathlib import Path

from transcript_pipeline.exporter import export_txt


def test_export_txt_writes_file(tmp_path: Path):
    target = tmp_path / "output.txt"
    export_txt(target, "MR. SMITH: Hello.")

    assert target.read_text(encoding="utf-8") == "MR. SMITH: Hello."
