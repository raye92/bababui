"""Per-tab documents, explicit saves, and local session recovery."""
from dataclasses import dataclass, field, fields
import hashlib
import json
import os
from pathlib import Path
import uuid

from shared.storage import atomic_bytes, file_lock
from app.src.casecat import archive, codec, project

SAVE_LOCK_DIR = Path(__file__).resolve().parents[1] / 'data' / 'save-locks'
NATIVE_ASSET_DIR = Path(__file__).resolve().parents[1] / 'data' / 'casecat'

@dataclass
class Document:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    wav_path: str | None = None
    audio_override: str | None = None
    save_path: str | None = None
    model: str = 'gemini-3.8-flash'
    transcription_model: str = 'gemini-3.5-transcribe'
    dirty: bool = False
    busy: bool = False
    status: str = ''
    warnings: list[str] = field(default_factory=list)
    view: int = 0
    center_line: int = 0
    native: project.NativeState | None = None

    @property
    def original(self):
        return self.native.original.text if self.native else ''

    @property
    def incoming(self):
        return self.native.incoming.text if self.native else ''

    @property
    def title(self):
        path = self.save_path or (self.native.bundle.name if self.native else self.wav_path)
        return Path(path).name if path else 'New tab'

    def duplicate(self):
        return Document(wav_path=self.wav_path, audio_override=self.audio_override, dirty=bool(self.native),
                        model=self.model, transcription_model=self.transcription_model,
                        view=self.view, center_line=self.center_line, warnings=list(self.warnings),
                        native=self.native.duplicate() if self.native else None)

    def update_warnings(self, warnings=()):
        native_warnings = self.native.job.warnings if self.native else ()
        self.warnings = list(dict.fromkeys(
            warning for warning in (*native_warnings, *warnings)
            if warning != codec.NO_WAV_NOTICE or not self.wav_path))

    def set_text(self, side, text, *, revision=None):
        if side not in ('original', 'incoming') or not isinstance(text, str):
            raise ValueError('Invalid document revision.')
        if not self.native:
            raise ValueError('Import a CaseCAT ZIP before editing.')
        if self.native:
            if revision is None:
                revision = getattr(self.native, side).revise(text)
                text = revision.text
            if revision.text != text:
                raise ValueError('Native revision and text projection disagree.')
            setattr(self.native, side, revision)
        self.dirty = True

    def export_casecat(self, target, *, overwrite=False, corrected_audio=True):
        if not self.native:
            raise ValueError('Import a CaseCAT ZIP before exporting.')
        archive.export_zip(self.native.bundle, self.native.job.with_revision(self.native.original),
                           target, overwrite=overwrite, ai_copy=True,
                           alignment=self.native.alignment if corrected_audio else None)


def import_casecat(source, key=None):
    bundle = source if isinstance(source, archive.Archive) else archive.inspect_archive(source)
    if key is None:
        if len(bundle.jobs) != 1:
            raise ValueError('Choose a job from this archive.')
        key = bundle.jobs[0]
    native = project.NativeState.load(bundle, key)
    wav = archive.materialize_audio(bundle, native.job, NATIVE_ASSET_DIR)
    return Document(native=native, dirty=True,
                    wav_path=str(wav) if wav else None, warnings=list(native.job.warnings),
                    status='CaseCAT ZIP imported.')


def _document_record(doc):
    return {f.name: getattr(doc, f.name) for f in fields(doc) if f.name != 'native'}


def _restore_document(raw, native=None):
    try:
        if not isinstance(raw, dict) or 'native' in raw:
            raise ValueError('Invalid document metadata.')
        raw = dict(raw)
        for side in ('original', 'incoming'):
            if side in raw:
                text = raw.pop(side)
                if text != (getattr(native, side).text if native else ''):
                    raise ValueError('Legacy text disagrees with the structured revision.')
        doc = Document(**raw, native=native)
        if (not all(isinstance(v, str) for v in
                    (doc.id, doc.original, doc.incoming, doc.model, doc.transcription_model, doc.status))
                or type(doc.view) is not int or doc.view not in (0, 1)
                or type(doc.center_line) is not int or doc.center_line < 0
                or any(type(value) is not bool for value in (doc.busy, doc.dirty))
                or not isinstance(doc.warnings, list) or any(not isinstance(w, str) for w in doc.warnings)
                or any(p is not None and (not isinstance(p, str) or '\0' in p) for p in (doc.save_path, doc.wav_path, doc.audio_override))):
            raise ValueError('Invalid document metadata.')
        if native:
            # This notice describes current capabilities, not saved user content.
            doc.warnings = list(dict.fromkeys(
                native.job.warnings[0] if warning.startswith('CaseCAT native editing.') else warning
                for warning in doc.warnings))
        return doc
    except TypeError as exc:
        raise ValueError('Invalid document metadata.') from exc


def canonical(path):
    return os.path.normcase(str(Path(path).resolve()))


def suggested_path(doc, directory):
    stem = Path(doc.native.bundle.name).stem if doc.native else Path(doc.wav_path).stem if doc.wav_path else 'Untitled'
    extension = '.bababui'
    target = Path(directory) / f'{stem}{extension}'
    version = 2
    while target.exists():
        target = Path(directory) / f'{stem} ({version}){extension}'
        version += 1
    return target


def save_document(doc, path=None, *, save_as=False):
    if path is None and doc.save_path is None:
        raise ValueError('Choose a filename first.')
    target = Path(path or doc.save_path).resolve()
    if doc.native:
        return _save_native(doc, target, save_as=save_as)
    raise ValueError('Import a CaseCAT ZIP before saving.')


def open_document(path):
    target = Path(path).resolve()
    data = target.read_bytes()
    if target.suffix.lower() == '.bababui':
        native, raw = project.read_project(data)
        doc = _restore_document(raw, native)
        doc.save_path, doc.dirty, doc.busy = str(target), False, False
        wav = archive.materialize_audio(native.bundle, native.job, NATIVE_ASSET_DIR)
        doc.wav_path = doc.audio_override or (str(wav) if wav else None)
        # Capability warnings are not trusted to the project file's metadata.
        doc.update_warnings(doc.warnings)
        return doc
    raise ValueError('Plain-text documents are no longer supported. Import a CaseCAT ZIP.')


def save_session(path, documents, active_id):
    records = []
    for doc in documents:
        raw = _document_record(doc)
        if doc.native:
            project.recovery_asset(path, doc.native)
            raw['native'] = doc.native.to_dict()
        records.append(raw)
    record = {'version': 2, 'active_id': active_id, 'documents': records}
    atomic_bytes(path, json.dumps(record, ensure_ascii=False).encode('utf-8'))


def load_session(path):
    try:
        record = json.loads(Path(path).read_text(encoding='utf-8'))
        if record['version'] not in (1, 2) or not isinstance(record['documents'], list):
            raise ValueError('Unsupported session format.')
        if record['version'] == 1:
            import shutil
            backup = Path(str(path) + '.legacy-backup')
            if not backup.exists():
                shutil.copy2(path, backup)
        docs, bundles = [], {}
        ids, paths = set(), set()
        for raw in record['documents']:
            native_record = raw.pop('native', None)
            native = project.recover_state(path, native_record, bundles) if native_record else None
            doc = _restore_document(raw, native)
            if native:
                wav = archive.materialize_audio(native.bundle, native.job, NATIVE_ASSET_DIR)
                doc.wav_path = doc.audio_override or (str(wav) if wav else None)
                doc.update_warnings(doc.warnings)
            if (not isinstance(doc.id, str) or doc.id in ids
                    or not all(isinstance(v, str) for v in (doc.original, doc.incoming, doc.model, doc.status))
                    or doc.view not in (0, 1) or not isinstance(doc.center_line, int)
                    or not isinstance(doc.warnings, list)
                    or any(not isinstance(w, str) for w in doc.warnings)
                    or any(p is not None and not isinstance(p, str) for p in (doc.save_path, doc.wav_path, doc.audio_override))):
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


def _save_native(doc, target, *, save_as=False):
    if target.suffix.lower() != '.bababui':
        raise ValueError('Save native jobs with a .bababui extension. Use Export for a CaseCAT ZIP.')
    owned = not save_as and doc.save_path is not None and canonical(target) == canonical(doc.save_path)
    lock_name = hashlib.sha256(canonical(target).encode()).hexdigest() + '.lock'
    with file_lock(SAVE_LOCK_DIR / lock_name):
        if target.exists() and not owned:
            raise ValueError('That filename already exists. Choose a different version name.')
        doc.dirty = True
        raw = _document_record(doc)
        raw.update(wav_path=None, save_path=None, busy=False)
        data = project.project_bytes(doc.native, raw)
        archive.atomic_publish(target, data, overwrite=owned)
    doc.save_path, doc.dirty = str(target), False
