from pathlib import Path


def export_txt(path: str | Path, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")
