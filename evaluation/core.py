"""Dataset validation, immutable snapshots, scoring, and durable evaluation runs."""
from contextlib import contextmanager
from copy import deepcopy
import csv
from datetime import datetime, timezone
import difflib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from rapidfuzz.distance import Levenshtein

SCORING_VERSION = "character-levenshtein-lf-v1"
SEPARATOR = "\n\n---\n\n# COURT REPORTING RULES DOCUMENT\n\n"


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def valid_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text.")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError(f"{label} contains unsupported control characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} is not valid Unicode text.") from exc
    return value


def validate_cases(records):
    if not isinstance(records, list) or not records:
        raise ValueError("Supply at least one input/output pair.")
    result, seen = [], set()
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise ValueError(f"Case {index} must be an object.")
        identifier = valid_text(record.get("id"), f"Case {index} ID")
        if identifier != identifier.strip() or any(c in identifier for c in "\r\n\t"):
            raise ValueError("IDs must be single-line text without surrounding whitespace.")
        if identifier in seen:
            raise ValueError(f"Duplicate case ID: {identifier}")
        seen.add(identifier)
        split = record.get("split", "development")
        if split not in ("development", "holdout"):
            raise ValueError(f"Case {identifier}: split must be development or holdout.")
        result.append({"id": identifier,
                       "input": valid_text(record.get("input"), f"Case {identifier} input"),
                       "output": valid_text(record.get("output"), f"Case {identifier} output"),
                       "split": split})
    return result


def parse_jsonl(text):
    records = []
    for number, line in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            validate_cases([record])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid JSONL line {number}: {exc}") from exc
        records.append(record)
    return validate_cases(records)


def parse_text_pairs(files):
    pairs = {}
    for name, text in files.items():
        match = re.fullmatch(r"(.+)\.(input|output)\.txt", name)
        if not match:
            raise ValueError(f"Use <id>.input.txt or <id>.output.txt: {name}")
        identifier, kind = match.groups()
        pairs.setdefault(identifier, {"id": identifier})[kind] = text
    for identifier, pair in pairs.items():
        if "input" not in pair or "output" not in pair:
            raise ValueError(f"Missing input/output partner for {identifier}.")
    return validate_cases(list(pairs.values()))


def lf(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def similarity(left, right):
    left, right = lf(left), lf(right)
    length = max(len(left), len(right))
    return 100.0 if not length else 100 * (1 - Levenshtein.distance(left, right) / length)


def score(rough, generated, expected):
    primary = similarity(generated, expected)
    baseline = similarity(rough, expected)
    return {"similarity": primary, "baseline": baseline, "improvement": primary - baseline,
            "exact": lf(generated) == lf(expected),
            "normalized_similarity": similarity(" ".join(generated.split()), " ".join(expected.split()))}


class Store:
    """Names never become paths. Prompt versions and run snapshots stay immutable."""
    def __init__(self, root):
        self.root = Path(root)

    def path(self, kind, identifier):
        if kind not in ("datasets", "prompts", "runs") or not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise ValueError("Invalid storage identifier.")
        return self.root / kind / f"{identifier}.json"

    def write(self, kind, record):
        path = self.path(kind, record["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "prompts" and path.exists():
            raise ValueError("Saved prompt versions cannot be overwritten.")
        payload = json.dumps(record, ensure_ascii=False, indent=2)
        fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get(self, kind, identifier):
        return json.loads(self.path(kind, identifier).read_text(encoding="utf-8"))

    def list(self, kind):
        if kind not in ("datasets", "prompts", "runs"):
            raise ValueError("Invalid storage collection.")
        values = [self.get(kind, p.stem) for p in (self.root / kind).glob("*.json")]
        return sorted(values, key=lambda x: (x["created_at"], x["id"]), reverse=True)

    def save_dataset(self, name, cases):
        cases = validate_cases(cases)
        record = {"id": uuid.uuid4().hex, "name": valid_text(name, "Dataset name"),
                  "created_at": now(), "cases": cases, "hash": digest(cases)}
        self.write("datasets", record)
        return record

    def update_dataset(self, identifier, cases):
        cases = validate_cases(cases)
        record = self.get("datasets", identifier)
        record.update(cases=cases, hash=digest(cases), updated_at=now())
        self.write("datasets", record)
        return record

    def save_prompt(self, name, instructions, rules):
        content = {"instructions": valid_text(instructions, "Instructions"),
                   "rules": valid_text(rules, "Rules")}
        record = {"id": uuid.uuid4().hex, "name": valid_text(name, "Version name"),
                  "created_at": now(), **content,
                  "system_prompt": instructions + SEPARATOR + rules}
        record["hash"] = digest(record["system_prompt"])
        self.write("prompts", record)
        return record

    @contextmanager
    def run_lock(self, identifier):
        """OS lock releases on process exit, including crashes. Never wait/replay."""
        path = self.path("runs", identifier).with_suffix(".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("This run is already executing in another session.") from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def create_run(store, dataset, prompt, split, settings):
    selected = [c for c in dataset["cases"] if c["split"] == split]
    if not selected:
        raise ValueError("No cases in this split.")
    record = {"id": uuid.uuid4().hex, "created_at": now(), "dataset": deepcopy(dataset),
              "prompt": deepcopy(prompt), "split": split, "settings": deepcopy(settings),
              "scoring_version": SCORING_VERSION, "case_ids": [c["id"] for c in selected],
              "results": [{"case_id": c["id"], "status": "pending", "attempts": []} for c in selected]}
    store.write("runs", record)
    return record


def execute_run(store, identifier, client, retry=False, progress=None):
    with store.run_lock(identifier):
        run = store.get("runs", identifier)
        case_map = {c["id"]: c for c in run["dataset"]["cases"]}
        eligible = ("pending", "error", "running") if retry else ("pending",)
        for result in run["results"]:
            if result["status"] not in eligible:
                continue
            result["status"] = "running"
            attempt = {"started_at": now(), "status": "running"}
            result["attempts"].append(attempt)
            store.write("runs", run)
            case = case_map[result["case_id"]]
            started = time.perf_counter()
            try:
                response = client.complete(case["input"], run["prompt"]["system_prompt"])
                if not isinstance(response, str) or not response.strip():
                    raise ValueError("The model returned an empty response.")
                result.update(status="success", response=response,
                              scores=score(case["input"], response, case["output"]))
                result.pop("error", None)
                attempt["status"] = "success"
            except Exception as exc:
                result.update(status="error", error=str(exc))
                attempt.update(status="error", error=str(exc))
            attempt.update(finished_at=now(), latency_seconds=time.perf_counter() - started)
            result["latency_seconds"] = attempt["latency_seconds"]
            run["updated_at"] = now()
            store.write("runs", run)
            if progress:
                progress(deepcopy(run))
        return run


def summary(run):
    results = run["results"]
    successes = [r for r in results if r["status"] == "success"]
    complete = bool(results) and len(successes) == len(results)
    row = {"run_id": run["id"], "prompt": run["prompt"]["name"],
           "dataset": run["dataset"]["name"], "split": run["split"],
           "completed": len(successes), "total": len(results), "complete": complete}
    for key in ("similarity", "baseline", "improvement", "normalized_similarity"):
        row[key] = sum(r["scores"][key] for r in successes) / len(results) if complete else None
    row["exact_match_rate"] = 100 * sum(r["scores"]["exact"] for r in successes) / len(results) if complete else None
    return row


def comparison_key(run):
    return (digest(run["dataset"]["cases"]), tuple(run["case_ids"]), run["scoring_version"])


def compare_runs(reference, candidate):
    if comparison_key(reference) != comparison_key(candidate):
        raise ValueError("Runs are not compatible: dataset, selected cases, or scoring version differs.")
    if not summary(reference)["complete"] or not summary(candidate)["complete"]:
        raise ValueError("Only complete runs can be compared.")
    other = {r["case_id"]: r for r in candidate["results"]}
    return [{"case_id": r["case_id"], "reference_similarity": r["scores"]["similarity"],
             "candidate_similarity": other[r["case_id"]]["scores"]["similarity"],
             "change_pp": other[r["case_id"]]["scores"]["similarity"] - r["scores"]["similarity"]}
            for r in reference["results"]]


def comparison_csv(rows):
    output = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            # Prevent spreadsheet formula execution when opening imported IDs/names.
            writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
                             for k, v in row.items()})
    return output.getvalue()


def visible_diff(expected, generated):
    def lines(text):
        return [line.replace(" ", "·").replace("\t", "→") for line in lf(text).replace("\n", "↵\n").split("\n")]
    return difflib.HtmlDiff(wrapcolumn=100).make_table(
        lines(expected), lines(generated), "Expected", "Generated", context=True, numlines=3)
