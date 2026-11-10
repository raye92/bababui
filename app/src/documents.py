"""Per-tab documents, explicit saves, and local session recovery."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import uuid

from evaluation.storage import atomic_bytes, file_lock

SAVE_LOCK_DIR = Path(__file__).resolve().parents[1] / 'data' / 'save-locks'

@dataclass
class Document:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    original: str = ''
    incoming: str = ''
    wav_path: str | None = None
    save_path: str | None = None
    model: str = 'gemini-3.8-flash'
    transcription_model: str = 'gemini-3.5-transcribe'
    dirty: bool = True
    busy: bool = False
    status: str = ''
    warnings: list[str] = field(default_factory=list)
    view: int = 0
    center_line: int = 0

    @property
    def title(self):
        path = self.save_path or self.wav_path
        return Path(path).name if path else 'New tab'

    def duplicate(self):
        return Document(original=self.original, incoming=self.incoming, wav_path=self.wav_path,
                        model=self.model, transcription_model=self.transcription_model,
                        view=self.view, center_line=self.center_line, warnings=list(self.warnings))


def canonical(path):
    return os.path.normcase(str(Path(path).resolve()))


def companion(path):
    return Path(str(path) + '.bababui.json')


def pending(path):
    return Path(str(path) + '.bababui.pending')


def suggested_path(doc, directory):
    stem = Path(doc.wav_path).stem if doc.wav_path else 'Untitled'
    target = Path(directory) / f'{stem}.txt'
    version = 2
    while target.exists() or companion(target).exists() or pending(target).exists():
        target = Path(directory) / f'{stem} ({version}).txt'
        version += 1
    return target


def save_document(doc, path=None, *, save_as=False):
    if path is None and doc.save_path is None:
        raise ValueError('Choose a filename first.')
    target = Path(path or doc.save_path).resolve()
    if target.suffix.lower() != '.txt':
        raise ValueError('Save the document with a .txt extension.')
    owned = not save_as and doc.save_path is not None and canonical(target) == canonical(doc.save_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # A stable lock also prevents concurrent BABABUI windows racing on a new name.
    lock_name = hashlib.sha256(canonical(target).encode()).hexdigest() + '.lock'
    with file_lock(SAVE_LOCK_DIR / lock_name):
        if not owned and any(p.exists() for p in (target, companion(target), pending(target))):
            raise ValueError('That filename already exists. Choose a different version name.')
        doc.dirty = True
        data = doc.original.encode('utf-8')
        metadata = {'version': 1, 'text_sha256': hashlib.sha256(data).hexdigest(),
                    'wav_path': doc.wav_path, 'incoming': doc.incoming, 'model': doc.model,
                    'transcription_model': doc.transcription_model}
        # The marker makes a power loss between the two atomic writes detectable.
        atomic_bytes(pending(target), b'Incomplete BABABUI save')
        try:
            if not owned:
                # Exclusive creation protects files created by another application.
                with target.open('xb'):
                    pass
                with companion(target).open('xb'):
                    pass
            atomic_bytes(target, data)
            atomic_bytes(companion(target), json.dumps(metadata, ensure_ascii=False).encode('utf-8'))
        except Exception:
            # Keep the marker and dirty state. Recovery still contains both texts.
            raise
        pending(target).unlink()
    doc.save_path = str(target)
    doc.dirty = False


def open_document(path):
    target = Path(path).resolve()
    data = target.read_bytes()
    text = data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    doc = Document(original=text, incoming=text, save_path=str(target), dirty=False)
    if pending(target).exists():
        doc.warnings = ['An incomplete save was detected. Opened the text without pending revisions; check session recovery.']
        doc.dirty = True
        return doc
    if companion(target).exists():
        try:
            meta = json.loads(companion(target).read_text(encoding='utf-8'))
            if meta['version'] != 1 or meta['text_sha256'] != hashlib.sha256(data).hexdigest():
                raise ValueError('Metadata does not match the text file.')
            if not isinstance(meta['incoming'], str) or not isinstance(meta['model'], str):
                raise ValueError('Invalid document metadata.')
            if not isinstance(meta['transcription_model'], str):
                raise ValueError('Invalid transcription model.')
            if meta.get('wav_path') is not None and not isinstance(meta['wav_path'], str):
                raise ValueError('Invalid WAV reference.')
            doc.incoming, doc.wav_path, doc.model = meta['incoming'], meta.get('wav_path'), meta['model']
            doc.transcription_model = meta['transcription_model']
        except (ValueError, KeyError, TypeError, OSError):
            doc.warnings = ['Companion metadata is invalid or does not match this text. Pending revisions were not loaded.']
            doc.dirty = True
    return doc


def save_session(path, documents, active_id):
    record = {'version': 1, 'active_id': active_id, 'documents': [asdict(d) for d in documents]}
    atomic_bytes(path, json.dumps(record, ensure_ascii=False).encode('utf-8'))


def load_session(path):
    try:
        record = json.loads(Path(path).read_text(encoding='utf-8'))
        if record['version'] != 1 or not isinstance(record['documents'], list):
            raise ValueError('Unsupported session format.')
        docs = []
        ids, paths = set(), set()
        for raw in record['documents']:
            doc = Document(**raw)
            if (not isinstance(doc.id, str) or doc.id in ids
                    or not all(isinstance(v, str) for v in (doc.original, doc.incoming, doc.model, doc.status))
                    or doc.view not in (0, 1) or not isinstance(doc.center_line, int)
                    or not isinstance(doc.warnings, list)
                    or any(not isinstance(w, str) for w in doc.warnings)
                    or any(p is not None and not isinstance(p, str) for p in (doc.save_path, doc.wav_path))):
                raise ValueError('Invalid recovered document.')
            ids.add(doc.id)
            if doc.save_path:
                key = canonical(doc.save_path)
                if key in paths:
                    raise ValueError('Duplicate saved documents in recovery.')
                paths.add(key)
            if doc.busy:
                doc.busy = False
                doc.status = 'Processing was interrupted. Click BABABUI to retry explicitly.'
            docs.append(doc)
        return docs, record.get('active_id')
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('Could not read session recovery. The recovery file has been preserved.') from exc
