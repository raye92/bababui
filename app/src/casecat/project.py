"""Self-contained working projects, distinct from native CaseCAT exports."""
from dataclasses import dataclass, replace
import hashlib
import io
import json
from pathlib import Path
import zipfile
import zlib

from . import archive, codec
from .anchors import Revision
from app.src.speech_alignment import SpeechAlignment


# Only fingerprints live here, never archive bytes. Recovery loading still
# verifies the archive checksum independently of this process-local cache.
_verified_recovery_assets = {}


def _asset_fingerprint(target):
    try:
        value = target.stat()
    except FileNotFoundError:
        return None
    return (value.st_dev, value.st_ino, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


@dataclass
class NativeState:
    bundle: archive.Archive
    job: codec.NativeJob
    original: Revision
    incoming: Revision
    review: dict | None = None
    alignment: SpeechAlignment | None = None

    @classmethod
    def load(cls, bundle, key):
        job = codec.load_job(bundle, key)
        return cls(bundle, job, job.revision, job.revision)

    def duplicate(self):
        from copy import deepcopy
        return replace(self, review=deepcopy(self.review))

    def to_dict(self):
        return {'job': self.job.key, 'source_sha256': self.bundle.digest,
                'source_name': self.bundle.name, 'source_path': self.bundle.source_path,
                'original': self.original.to_dict(), 'incoming': self.incoming.to_dict(),
                'review': self.review, 'alignment': vars(self.alignment).copy() if self.alignment else None}

    @classmethod
    def restore(cls, bundle, record):
        try:
            if (not isinstance(record, dict) or not isinstance(record.get('job'), str)
                    or not isinstance(record.get('source_name'), str)
                    or (record.get('source_path') is not None and not isinstance(record['source_path'], str))):
                raise ValueError('Invalid native project metadata.')
            if bundle.digest != record['source_sha256']:
                raise ValueError('The original archive checksum does not match.')
            state = cls.load(bundle, record['job'])
            state.original = Revision.from_dict(record['original'])
            state.incoming = Revision.from_dict(record['incoming'])
            state.review = record.get('review')
            state.alignment = SpeechAlignment.restore(record.get('alignment'), len(state.job.stroke_clocks))
            if state.review is not None:
                from app.src.suggestion_filter import validate_review
                validate_review(state.review, state.incoming.text)
            for side in ('original', 'incoming'):
                if 'definitions' not in record[side]:
                    from .fields import field_values
                    values = dict(state.job.baseline.definitions)
                    values.update(field_values(getattr(state, side)))
                    setattr(state, side, replace(getattr(state, side), definitions=tuple(sorted(values.items()))))
                if 'all_caps' not in record[side]:
                    setattr(state, side, replace(getattr(state, side), all_caps=state.job.baseline.all_caps))
                if 'elements' not in record[side]:
                    revision = getattr(state, side)
                    restored = state.job.baseline._replace(0, len(state.job.text), revision.text)
                    setattr(state, side, replace(revision, elements=restored.elements))
            codec.validate_job(bundle, state.job.with_revision(state.original))
            codec.validate_job(bundle, state.job.with_revision(state.incoming))
            return state
        except (KeyError, TypeError) as exc:
            raise ValueError('Invalid native working project.') from exc


def project_bytes(state, document):
    out = io.BytesIO()
    record = {'version': 2, 'native': state.to_dict(), 'document': document}
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as result:
        result.writestr('source.zip', state.bundle.data, compress_type=zipfile.ZIP_STORED)
        result.writestr('document.json', json.dumps(record, ensure_ascii=False).encode('utf-8'))
    data = out.getvalue()
    # Verify the exact candidate before the existing working project is replaced.
    read_project(data)
    return data


def read_project(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as project:
            if sorted(project.namelist()) != ['document.json', 'source.zip']:
                raise ValueError('Invalid working project members.')
            if (project.getinfo('source.zip').file_size > archive.MAX_ARCHIVE_BYTES
                    or project.getinfo('document.json').file_size > 64 * 1024**2):
                raise ValueError('Working project exceeds the supported size limits.')
            record = json.loads(project.read('document.json'))
            if record['version'] not in (1, 2):
                raise ValueError('Unsupported working project version.')
            native = record['native']
            if (not isinstance(native, dict) or not isinstance(native.get('source_name'), str)
                    or (native.get('source_path') is not None and not isinstance(native['source_path'], str))):
                raise ValueError('Invalid native project metadata.')
            bundle = archive.inspect_archive(project.read('source.zip'), name=native['source_name'],
                                             source_path=native.get('source_path'))
            state = NativeState.restore(bundle, native)
            return state, record['document']
    except (zipfile.BadZipFile, KeyError, TypeError, UnicodeError, RuntimeError, zlib.error, EOFError) as exc:
        raise ValueError('Invalid native working project.') from exc


def recovery_asset(path, state):
    directory = Path(str(path) + '.assets')
    digest = state.bundle.digest
    target = (directory / f'{digest}.zip').resolve()
    before = _asset_fingerprint(target)
    if before is not None and _verified_recovery_assets.get(target) == (digest, before):
        return
    if before is None or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        archive.atomic_publish(target, state.bundle.data, overwrite=True)
        before = _asset_fingerprint(target)
    after = _asset_fingerprint(target)
    if before is not None and before == after:
        # Bound the cache without retaining closed documents or their audio.
        if target not in _verified_recovery_assets and len(_verified_recovery_assets) >= 256:
            _verified_recovery_assets.pop(next(iter(_verified_recovery_assets)))
        _verified_recovery_assets[target] = (digest, after)


def recover_state(path, record, bundles):
    digest = record['source_sha256']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid recovery asset identifier.')
    key = (digest, record['source_name'], record.get('source_path'))
    if key not in bundles:
        source = Path(str(path) + '.assets') / f'{digest}.zip'
        bundles[key] = archive.inspect_archive(source.read_bytes(), name=record['source_name'],
                                              source_path=record.get('source_path'))
    return NativeState.restore(bundles[key], record)
