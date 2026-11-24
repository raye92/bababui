"""Named files for one desktop transcription run."""
from contextlib import contextmanager
from itertools import count
import json
from pathlib import PureWindowsPath
import re

from shared.storage import atomic_bytes, atomic_copy


class OutputError(OSError):
    pass


@contextmanager
def output_io():
    try:
        yield
    except (OSError, ValueError) as exc:
        raise OutputError(f'Could not save or load transcription files: {exc}') from exc


class RunOutput:
    def __init__(self, directory):
        self.directory = directory
        self.files = {}

    @classmethod
    def create(cls, parent, name):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip()[:80].rstrip('. ') or 'Transcript'
        if PureWindowsPath(name).is_reserved():
            name = '_' + name
        parent.mkdir(parents=True, exist_ok=True)
        for version in count(1):
            directory = parent / (name if version == 1 else f'{name} ({version})')
            try:
                directory.mkdir()
            except FileExistsError:
                continue
            return cls(directory)

    def path(self, suffix):
        name = self.directory.name + suffix
        if PureWindowsPath(name).name != name:
            raise ValueError('Invalid transcription filename.')
        return self.directory / name

    def save(self, suffix, data):
        path = self.path(suffix)
        with output_io():
            atomic_bytes(path, data)
        self.files[suffix] = path

    def copy(self, suffix, source):
        path = self.path(suffix)
        with output_io():
            atomic_copy(source, path)
        self.files[suffix] = path

    def save_text(self, text):
        atomic_bytes(self.path('.txt'), text.encode('utf-8'))


class SegmentOutput:
    """Keep each Gemini reply with the word cache entry it produced."""

    def __init__(self, run, label):
        self.run = run
        self.label = label
        self.responses = {}

    def response(self, kind, body):
        if self.run:
            suffix = f' - {self.label} - {kind}.json'
            self.run.save(suffix, body.encode('utf-8'))
        self.responses[kind] = body

    def restore_responses(self, cached):
        responses = cached.with_suffix('.responses')
        if self.run and responses.exists():
            with output_io():
                for kind, body in json.loads(responses.read_bytes()).items():
                    self.response(kind, body)

    def cache_responses(self, cached):
        with output_io():
            atomic_bytes(cached.with_suffix('.responses'), json.dumps(self.responses, ensure_ascii=False).encode('utf-8'))
