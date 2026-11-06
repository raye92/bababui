"""WAV validation and deterministic speech-friendly segment preparation."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def executable(name):
    candidate = os.environ.get(name.upper() + "_PATH") or shutil.which(name)
    if not candidate:
        raise ValueError(f"Install {name} and add it to PATH, or set {name.upper()}_PATH.")
    return candidate


def command(name, args):
    result = subprocess.run([executable(name), "-hide_banner", *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise ValueError(f"{name} could not read or prepare the WAV audio.")
    return result


def probe(path):
    data = json.loads(command("ffprobe", ["-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]).stdout)
    if data.get("format", {}).get("format_name") != "wav" or not any(s.get("codec_type") == "audio" for s in data.get("streams", [])):
        raise ValueError("File is not WAV audio.")
    duration = float(data["format"]["duration"])
    if not 0 < duration < float("inf"):
        raise ValueError("WAV audio must have a positive duration.")
    # Decode the entire stream so a readable header cannot hide corrupt frames.
    command("ffmpeg", ["-v", "error", "-xerror", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"])
    return duration


def silences(path, start, end):
    output = command("ffmpeg", ["-ss", str(start), "-t", str(end - start), "-i", str(path),
                               "-af", "silencedetect=noise=-35dB:d=0.5", "-f", "null", "-"]).stderr
    intervals, beginning = [], None
    for kind, value in re.findall(r"silence_(start|end):\s*([0-9.]+)", output):
        if kind == "start":
            beginning = start + float(value)
        elif beginning is not None:
            intervals.append((beginning, min(end, start + float(value))))
            beginning = None
    if beginning is not None:
        intervals.append((beginning, end))
    return intervals


def plan_segments(duration, detect):
    segments, start, overlap = [], 0, False
    while start < duration:
        end = min(duration, start + 1800)
        next_overlap = False
        if end < duration:
            low = start + 1770
            candidates = [(max(low, a), min(end, b)) for a, b in detect(low, end)
                          if min(end, b) - max(low, a) >= 0.5]
            if candidates:
                a, b = candidates[-1]
                end = (a + b) / 2
            else:
                next_overlap = True
        segments.append({"start": start, "end": end, "overlap": overlap})
        start = end - 3 if next_overlap else end
        overlap = next_overlap
    return segments


def prepare(path, segment, destination):
    command("ffmpeg", ["-y", "-ss", str(segment["start"]), "-i", str(path),
                       "-t", str(segment["end"] - segment["start"]), "-map", "0:a:0",
                       "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination)])


def join_segments(texts, overlaps):
    combined, flags = texts[0], []
    for index, text in enumerate(texts[1:], 1):
        if overlaps[index]:
            left, right = list(re.finditer(r"\S+", combined)), list(re.finditer(r"\S+", text))
            normalize = lambda word: re.sub(r"[^\w]", "", word.group().casefold())
            matched = 0
            for size in range(min(30, len(left), len(right)), 2, -1):
                a, b = [normalize(w) for w in left[-size:]], [normalize(w) for w in right[:size]]
                if all(a) and len(set(a)) > 1 and a == b:
                    matched = size
                    break
            if matched:
                text = text[right[matched - 1].end():].lstrip()
            else:
                flags.append(index)
        if text:
            combined += "\n" + text
    return combined, flags
