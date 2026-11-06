"""All dataset entry paths validate complete text/text/WAV cases before persistence."""
import hashlib
import io
from pathlib import Path
import re
import tempfile

from evaluation.media import probe
from evaluation.storage import atomic_copy


def folder_files(folder):
    path = Path(folder).expanduser()
    if not path.is_dir():
        raise ValueError("Choose an existing local folder.")
    return {p.name: p for p in sorted(path.iterdir()) if p.is_file() and p.suffix.casefold() in (".txt", ".wav")}


def content(value):
    return value.read_bytes() if isinstance(value, Path) else value


def import_files(store, files, records=None):
    from evaluation.core import validate_cases
    names, errors = {}, []
    for name in files:
        if Path(name).name != name or "/" in name or "\\" in name:
            errors.append(f"Invalid filename: {name}")
        key = name.casefold()
        if key in names:
            errors.append(f"Filename collision: {names[key]}, {name}")
        names[key] = name
    if records is None:
        records, assigned = [], set()
        for key, name in names.items():
            if not key.endswith((".txt", ".wav")):
                errors.append(f"Unsupported file: {name}")
            if not key.endswith(".wav"):
                continue
            identifier = key[:-4]
            original = names.get(identifier + ".txt")
            reviewed = [n for k, n in names.items() if re.fullmatch(re.escape(identifier) + r"[_ .-]scoped\.txt", k)]
            if not original or not reviewed:
                errors.append(f"Missing text partner for {name}")
                continue
            if len(reviewed) != 1:
                errors.append(f"Ambiguous scoped partners for {name}: {', '.join(reviewed)}")
                continue
            group = {original, reviewed[0], name}
            if assigned.intersection(group):
                errors.append(f"Files match more than one case: {', '.join(sorted(assigned.intersection(group)))}")
            assigned.update(group)
            try:
                records.append({"id": Path(original).stem,
                                "input": content(files[original]).decode("utf-8-sig"),
                                "output": content(files[reviewed[0]]).decode("utf-8-sig")})
            except UnicodeError:
                errors.append(f"Invalid UTF-8 text: {identifier}")
        for name in names.values():
            if name not in assigned:
                errors.append(f"Missing or ambiguous partner for {name}")
    else:
        records = [dict(record) for record in records]
        expected = {str(r.get("id", "")).casefold() + ".wav" for r in records}
        for key, name in names.items():
            if key not in expected:
                errors.append(f"Unmatched audio file: {name}")
    staged = []
    with tempfile.TemporaryDirectory(prefix="evaluation-import-") as temporary:
        for index, record in enumerate(records):
            try:
                validate_cases([record], require_audio=False)
            except ValueError as exc:
                errors.append(str(exc))
            name = names.get(str(record.get("id", "")).casefold() + ".wav")
            if not name:
                errors.append(f"Missing WAV partner for {record.get('id')}")
                continue
            try:
                path = Path(temporary) / f"{index}.wav"
                source = files[name]
                digest = hashlib.sha256()
                with (source.open("rb") if isinstance(source, Path) else io.BytesIO(source)) as input_file, path.open("wb") as output:
                    while block := input_file.read(1024 * 1024):
                        digest.update(block)
                        output.write(block)
                duration = probe(path)
                sha = digest.hexdigest()
                record["audio"] = {"sha256": sha, "path": f"audio/{sha}.wav", "filename": name, "duration": duration}
                staged.append((record["audio"]["path"], path))
            except (ValueError, OSError, KeyError) as exc:
                errors.append(f"{name}: {exc}")
        if errors:
            raise ValueError("Import rejected:\n" + "\n".join(errors))
        validated = validate_cases(records)
        # All validation completes before any managed file is written.
        for relative, source in staged:
            target = store.root / relative
            if not target.exists():
                atomic_copy(source, target)
        return validated
